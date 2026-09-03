"""Endpoints Tests : laboratoire, terrain, courbe lactate, prédictions."""
from __future__ import annotations

import json
import math
from datetime import date

from .. import db, profiles
from ..science import physiology as PH
from ..science import power as PW
from ..science import running as RUN
from ..server import ROUTER, bad_request, not_found

TEST_TYPES = {
    "vo2max": "Test d'effort maximal (VO2max)",
    "lactate": "Test lactate par paliers",
    "ftp20": "Test FTP 20 minutes",
    "cp_test": "Test de puissance critique (3 efforts)",
    "cooper": "Test de Cooper (12 minutes)",
    "vameval": "Test VAMEVAL / VMA",
    "conconi": "Test de Conconi",
    "dexa": "Composition corporelle (DEXA)",
    "force": "Évaluation de force",
    "field": "Test de terrain",
}


@ROUTER.get("/api/athletes/<int:athlete_id>/tests")
def list_tests(request):
    athlete_id = request.params["athlete_id"]
    rows = db.query(
        "SELECT * FROM lab_tests WHERE athlete_id = ? ORDER BY date DESC", (athlete_id,))
    for row in rows:
        if row.get("results"):
            try:
                row["results"] = json.loads(row["results"])
            except (json.JSONDecodeError, TypeError):
                pass
        row["type_label"] = TEST_TYPES.get(row["type"], row["type"])
        row["points"] = db.query(
            "SELECT * FROM lactate_points WHERE test_id = ? ORDER BY stage", (row["id"],))
    return {"tests": rows, "types": TEST_TYPES}


@ROUTER.post("/api/athletes/<int:athlete_id>/tests")
def create_test(request):
    athlete_id = request.params["athlete_id"]
    payload = request.json
    data = {k: payload[k] for k in ("date", "type", "protocol", "lab",
                                    "conclusion", "notes") if k in payload}
    if not data.get("type"):
        raise bad_request("Le type de test est obligatoire.")
    data.setdefault("date", date.today().isoformat())
    data["athlete_id"] = athlete_id
    if payload.get("results"):
        data["results"] = json.dumps(payload["results"], ensure_ascii=False)
    test_id = db.insert("lab_tests", data)

    for i, point in enumerate(payload.get("points") or [], start=1):
        row = {k: point[k] for k in ("stage", "intensity", "speed_ms", "power_w",
                                     "hr", "lactate", "vo2", "vco2", "rer", "rpe")
               if k in point and point[k] is not None}
        row["test_id"] = test_id
        row.setdefault("stage", i)
        db.insert("lactate_points", row)
    return {"id": test_id, "analysis": analyze_test(test_id)}, 201


@ROUTER.get("/api/tests/<int:test_id>/analysis")
def test_analysis(request):
    return analyze_test(request.params["test_id"])


def analyze_test(test_id: int) -> dict:
    """Analyse un test : seuils lactiques, ajustements, recommandations."""
    test = db.query_one("SELECT * FROM lab_tests WHERE id = ?", (test_id,))
    if not test:
        raise not_found("Test introuvable.")
    points = db.query(
        "SELECT * FROM lactate_points WHERE test_id = ? ORDER BY stage", (test_id,))
    out: dict = {"test": test, "points": points, "thresholds": {}}

    lactate_points = [p for p in points if p.get("lactate") is not None]
    if len(lactate_points) >= 4:
        out["thresholds"] = lactate_thresholds(lactate_points)

    if test["type"] == "cp_test":
        efforts = [(p.get("intensity") or 0, p.get("power_w") or 0) for p in points]
        model = PW.critical_power([(t, w) for t, w in efforts if t and w])
        if model:
            out["critical_power"] = model
    if test["type"] == "cooper":
        try:
            results = json.loads(test.get("results") or "{}")
        except (json.JSONDecodeError, TypeError):
            results = {}
        distance = results.get("distance_m")
        if distance:
            out["vo2max_estimate"] = PH.vo2max_cooper(distance)
            out["vma_ms"] = round(distance / 720, 3)
    if test["type"] == "ftp20":
        try:
            results = json.loads(test.get("results") or "{}")
        except (json.JSONDecodeError, TypeError):
            results = {}
        best20 = results.get("mean_power_w")
        if best20:
            out["ftp_estimate_w"] = round(best20 * 0.95, 1)
            out["note"] = ("La FTP est estimée à 95 % de la puissance moyenne sur "
                           "20 minutes. Ce coefficient suppose un échauffement "
                           "complet et un effort réellement maximal ; il surestime "
                           "les profils très anaérobies.")
    return out


def lactate_thresholds(points: list[dict]) -> dict:
    """Détermine LT1 et LT2 depuis une courbe lactate par paliers.

    * **LT1** — premier seuil : première hausse de 0,4 mmol/L au-dessus de la
      valeur de base (méthode du « delta 0,4 », robuste au bruit analytique).
    * **LT2** — second seuil, deux méthodes :
      « OBLA » (concentration fixe à 4 mmol/L, interpolation linéaire entre
      paliers) et « Dmax modifiée » (point de la courbe le plus éloigné de la
      droite joignant LT1 au dernier palier), moins dépendante du protocole.
    """
    lactates = [p["lactate"] for p in points]
    intensities = [p.get("power_w") or p.get("speed_ms") or p.get("intensity") or 0
                   for p in points]
    hrs = [p.get("hr") for p in points]
    baseline = min(lactates[:2]) if len(lactates) >= 2 else lactates[0]

    def interpolate(target: float):
        for i in range(1, len(lactates)):
            if lactates[i - 1] < target <= lactates[i]:
                span = lactates[i] - lactates[i - 1]
                ratio = (target - lactates[i - 1]) / span if span else 0
                intensity = intensities[i - 1] + ratio * (intensities[i] - intensities[i - 1])
                hr = None
                if hrs[i - 1] is not None and hrs[i] is not None:
                    hr = hrs[i - 1] + ratio * (hrs[i] - hrs[i - 1])
                return {"intensity": round(intensity, 1),
                        "hr": round(hr) if hr else None,
                        "lactate": target}
        return None

    out: dict = {}
    lt1 = interpolate(baseline + 0.4)
    if lt1:
        out["lt1"] = {**lt1, "method": "Base + 0,4 mmol/L"}
    obla = interpolate(4.0)
    if obla:
        out["lt2_obla"] = {**obla, "method": "OBLA — 4 mmol/L fixe"}

    # Dmax modifiée : distance maximale à la corde LT1 → dernier palier
    if lt1 and len(points) >= 4:
        x0, y0 = lt1["intensity"], lt1["lactate"]
        x1, y1 = intensities[-1], lactates[-1]
        denom = math.hypot(x1 - x0, y1 - y0)
        if denom > 0:
            best, best_i = -1.0, None
            for i, (x, y) in enumerate(zip(intensities, lactates)):
                if x < x0:
                    continue
                distance = abs((y1 - y0) * x - (x1 - x0) * y + x1 * y0 - y1 * x0) / denom
                if distance > best:
                    best, best_i = distance, i
            if best_i is not None:
                out["lt2_dmax"] = {
                    "intensity": round(intensities[best_i], 1),
                    "hr": hrs[best_i], "lactate": lactates[best_i],
                    "method": "Dmax modifiée (Bishop et al., 1998)",
                }
    out["curve"] = [{"intensity": i, "lactate": l, "hr": h}
                    for i, l, h in zip(intensities, lactates, hrs)]
    out["interpretation"] = (
        "LT1 marque la fin de l'endurance purement aérobie : c'est la borne "
        "haute des sorties longues. LT2 est l'intensité maximale soutenable en "
        "état stable (≈ 30 à 60 min). L'écart entre les deux définit la largeur "
        "de la zone « tempo » — plus il est grand, plus l'athlète dispose de "
        "marge de progression par le travail au seuil.")
    return out


@ROUTER.delete("/api/tests/<int:test_id>")
def delete_test(request):
    db.delete("lab_tests", request.params["test_id"])
    return {"deleted": request.params["test_id"]}


@ROUTER.get("/api/athletes/<int:athlete_id>/predictions")
def predictions(request):
    """Prédictions de performance en course, depuis le VDOT ou une performance."""
    athlete_id = request.params["athlete_id"]
    ctx = profiles.athlete_context(athlete_id)
    distance = request.q_float("distance_m")
    time_s = request.q_float("time_s")

    if not (distance and time_s):
        best = db.query_one(
            "SELECT be.duration_s, be.value, be.local_date, a.name FROM best_efforts be"
            " JOIN activities a ON a.id = be.activity_id"
            " WHERE be.athlete_id = ? AND be.kind = 'speed' AND be.duration_s >= 600"
            " ORDER BY (be.value * be.duration_s) DESC LIMIT 1", (athlete_id,))
        if best:
            distance = best["value"] * best["duration_s"]
            time_s = best["duration_s"]
            source = f"Meilleur effort continu du {best['local_date']} ({best['name']})"
        elif ctx.get("threshold_speed_ms"):
            distance = ctx["threshold_speed_ms"] * 3600
            time_s = 3600
            source = "Extrapolé depuis l'allure seuil du profil"
        else:
            raise bad_request("Aucune performance de référence disponible : "
                              "renseignez une allure seuil ou importez une séance.")
    else:
        source = "Performance saisie"

    vdot = RUN.vdot(distance, time_s) or ctx.get("vdot")
    return {
        "source": source,
        "reference": {"distance_m": round(distance), "time_s": round(time_s),
                      "pace_s_km": RUN.speed_to_pace(distance / time_s)},
        "vdot": vdot,
        "predictions": RUN.race_predictions(distance, time_s),
        "training_paces": RUN.daniels_paces(vdot) if vdot else None,
        "caveat": ("Les prédictions de Riegel (exposant 1,06) supposent une "
                   "préparation adaptée à la distance visée. Elles surestiment "
                   "régulièrement le marathon d'un coureur qui n'a pas construit "
                   "le volume correspondant : traitez le résultat comme un "
                   "potentiel, pas comme une garantie."),
    }


@ROUTER.get("/api/athletes/<int:athlete_id>/estimates")
def estimates(request):
    """Estimations physiologiques de terrain à partir des données disponibles."""
    athlete_id = request.params["athlete_id"]
    ctx = profiles.athlete_context(athlete_id)
    athlete = ctx["athlete"]
    out: dict = {"available": {}, "notes": []}

    if ctx.get("age"):
        out["hr_max_formulas"] = {
            key: PH.estimate_hr_max(ctx["age"], ctx["sex"], key)
            for key in ("tanaka", "gellish", "nes", "fox")
        }
    if ctx.get("hr_max") and ctx.get("hr_rest"):
        out["available"]["vo2max_uth"] = PH.vo2max_uth_sorensen(
            ctx["hr_max"], ctx["hr_rest"])
        out["notes"].append(
            "VO2max estimée par le rapport FCmax/FCrepos (Uth et al., 2004) : "
            "erreur type d'environ 10 %, valable chez les sujets entraînés.")
    if ctx.get("ftp_w") and ctx.get("weight_kg"):
        out["available"]["vo2max_from_ftp"] = PH.vo2max_from_ftp(
            ctx["ftp_w"], ctx["weight_kg"])
        out["available"]["ftp_w_per_kg"] = round(ctx["ftp_w"] / ctx["weight_kg"], 2)
    if ctx.get("vvo2max"):
        out["available"]["vo2max_from_vma"] = PH.vo2max_from_vma(ctx["vvo2max"])
    if ctx.get("vo2max") and ctx.get("age"):
        out["available"]["percentile"] = PH.vo2max_percentile(
            ctx["vo2max"], ctx["age"], ctx["sex"])
    if ctx.get("weight_kg") and athlete.get("height_cm") and ctx.get("age"):
        bmr = PH.bmr_mifflin(ctx["weight_kg"], athlete["height_cm"],
                             ctx["age"], ctx["sex"])
        out["available"]["bmr_kcal"] = bmr
        week_load = db.scalar(
            "SELECT COALESCE(SUM(calories),0) FROM activities WHERE athlete_id = ?"
            " AND local_date >= date('now','-7 days')", (athlete_id,), 0)
        if bmr:
            out["available"]["tdee_kcal"] = round(bmr * 1.4 + (week_load or 0) / 7)
    return out


@ROUTER.get("/api/athletes/<int:athlete_id>/fueling")
def fueling(request):
    """Plan nutritionnel et hydrique pour une séance ou une course."""
    athlete_id = request.params["athlete_id"]
    duration_s = request.q_float("duration_s", 7200)
    temp = request.q_float("temp_c")
    humidity = request.q_float("humidity_pct", 55)
    ctx = profiles.athlete_context(athlete_id)
    plan = PH.carb_needs(duration_s)
    out = {"duration_s": duration_s, "carbs": plan}
    if temp is not None:
        wbgt = PH.wbgt_estimate(temp, humidity)
        out["heat"] = {
            "wbgt": wbgt, "risk": PH.heat_risk(wbgt),
            "pace_penalty_pct": PH.heat_pace_penalty(temp, humidity),
            "extra_fluid_ml_h": 250 if (wbgt or 0) > 23 else 0,
        }
    if ctx.get("weight_kg"):
        out["hydration"] = {
            "baseline_ml_h": round(ctx["weight_kg"] * 7),
            "note": ("À défaut de test de sudation, viser 6 à 8 ml par kg et par "
                     "heure, et ajuster sur la perte de poids réelle : une perte "
                     "supérieure à 2 % du poids corporel dégrade la performance "
                     "aérobie et la thermorégulation."),
        }
    return out
