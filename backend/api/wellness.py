"""Endpoints Bien-être : relevés quotidiens, VFC, disponibilité."""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from .. import db, settings
from ..ingest import pipeline
from ..science import hrv as HRV
from ..science import readiness as RD
from ..server import ROUTER, bad_request, not_found

WELLNESS_FIELDS = (
    "hrv_rmssd", "hrv_sdnn", "hrv_ln_rmssd", "resting_hr", "sleep_total_min",
    "sleep_deep_min", "sleep_rem_min", "sleep_light_min", "sleep_awake_min",
    "sleep_score", "sleep_onset", "sleep_wake", "spo2_avg", "respiration_avg",
    "body_battery_max", "body_battery_min", "stress_avg", "steps", "active_kcal",
    "total_kcal", "weight_kg", "body_fat_pct", "hydration_ml", "soreness",
    "fatigue", "mood", "stress_subj", "sleep_quality", "motivation", "illness",
    "menstrual_phase", "source", "notes",
)


@ROUTER.get("/api/athletes/<int:athlete_id>/wellness")
def list_wellness(request):
    athlete_id = request.params["athlete_id"]
    days = request.q_int("days", 120)
    since = request.q("from") or (date.today() - timedelta(days=days)).isoformat()
    until = request.q("to") or date.today().isoformat()
    rows = db.query(
        "SELECT * FROM wellness WHERE athlete_id = ? AND date BETWEEN ? AND ?"
        " ORDER BY date", (athlete_id, since, until))
    ln = [r.get("hrv_ln_rmssd") for r in rows]
    baseline = HRV.rolling_baseline(ln, 7)
    for row, base in zip(rows, baseline):
        row["hrv_baseline_7d"] = base
    low, mean, high = HRV.normal_range(ln)
    return {
        "wellness": rows,
        "hrv_band": {"low": low, "mean": mean, "high": high},
        "cv": HRV.coefficient_of_variation(ln),
        "status": HRV.hrv_status(baseline[-1] if baseline else None, low, high,
                                 HRV.coefficient_of_variation(ln)),
    }


@ROUTER.post("/api/athletes/<int:athlete_id>/wellness")
def save_wellness(request):
    """Enregistre (ou met à jour) le relevé d'un jour et recalcule la disponibilité."""
    athlete_id = request.params["athlete_id"]
    if not db.query_one("SELECT id FROM athletes WHERE id = ?", (athlete_id,)):
        raise not_found("Athlète introuvable.")
    payload = request.json
    day = payload.get("date") or date.today().isoformat()
    data = {k: payload[k] for k in WELLNESS_FIELDS
            if k in payload and payload[k] not in ("", None)}
    if not data:
        raise bad_request("Aucune donnée de bien-être fournie.")
    data["athlete_id"] = athlete_id
    data["date"] = day
    data.setdefault("source", "manual")

    if data.get("hrv_rmssd") and not data.get("hrv_ln_rmssd"):
        data["hrv_ln_rmssd"] = HRV.ln_rmssd(data["hrv_rmssd"])
    data["hooper_index"] = RD.hooper_index(
        data.get("fatigue"), data.get("soreness"), data.get("mood"),
        data.get("stress_subj"), data.get("sleep_quality"))

    existing = db.query_one(
        "SELECT * FROM wellness WHERE athlete_id = ? AND date = ?", (athlete_id, day))
    merged = {**(existing or {}), **data}
    score = compute_readiness(athlete_id, day, merged)
    data["readiness"] = score["score"]
    data["readiness_flag"] = score["flag"]

    db.upsert("wellness", data, ["athlete_id", "date"])
    pipeline.refresh_alerts(athlete_id)
    return {"date": day, "readiness": score}, 201


def compute_readiness(athlete_id: int, day: str, row: dict) -> dict:
    """Calcule le score de disponibilité en resituant le jour dans l'historique."""
    history = db.query(
        "SELECT date, hrv_ln_rmssd, resting_hr FROM wellness"
        " WHERE athlete_id = ? AND date < ? ORDER BY date DESC LIMIT 60",
        (athlete_id, day))
    ln_values = [h["hrv_ln_rmssd"] for h in history if h.get("hrv_ln_rmssd")]
    rhr_values = [h["resting_hr"] for h in history if h.get("resting_hr")]
    hrv_baseline = statistics.fmean(ln_values) if len(ln_values) >= 7 else None
    hrv_sd = statistics.pstdev(ln_values) if len(ln_values) >= 7 else None
    rhr_baseline = statistics.fmean(rhr_values) if len(rhr_values) >= 7 else None

    load_row = db.query_one(
        "SELECT tsb, acwr_ewma FROM daily_load WHERE athlete_id = ? AND date <= ?"
        " ORDER BY date DESC LIMIT 1", (athlete_id, day))
    weights = settings.load().get("readiness_weights")
    return RD.readiness(
        ln_rmssd=row.get("hrv_ln_rmssd"), hrv_baseline=hrv_baseline, hrv_sd=hrv_sd,
        rhr=row.get("resting_hr"), rhr_baseline=rhr_baseline,
        sleep_min=row.get("sleep_total_min"), sleep_quality=row.get("sleep_quality"),
        fatigue=row.get("fatigue"), soreness=row.get("soreness"),
        mood=row.get("mood"), stress=row.get("stress_subj"),
        motivation=row.get("motivation"),
        tsb=load_row["tsb"] if load_row else None,
        acwr=load_row["acwr_ewma"] if load_row else None,
        weights=weights)


@ROUTER.get("/api/athletes/<int:athlete_id>/readiness")
def readiness_detail(request):
    """Détail du score du jour : contributions et leviers."""
    athlete_id = request.params["athlete_id"]
    day = request.q("date") or date.today().isoformat()
    row = db.query_one("SELECT * FROM wellness WHERE athlete_id = ? AND date = ?",
                       (athlete_id, day))
    if not row:
        row = db.query_one(
            "SELECT * FROM wellness WHERE athlete_id = ? AND date <= ?"
            " ORDER BY date DESC LIMIT 1", (athlete_id, day)) or {}
    score = compute_readiness(athlete_id, row.get("date") or day, row)
    labels = {"hrv": "Variabilité cardiaque", "rhr": "FC de repos",
              "sleep": "Sommeil", "subjective": "Ressenti déclaré",
              "load": "Bilan de charge"}
    for driver in score.get("drivers", []):
        driver["label"] = labels.get(driver["key"], driver["key"])
    return {"date": row.get("date") or day, "readiness": score, "raw": row}


@ROUTER.delete("/api/athletes/<int:athlete_id>/wellness/<day>")
def delete_wellness(request):
    athlete_id = request.params["athlete_id"]
    day = request.params["day"]
    db.execute("DELETE FROM wellness WHERE athlete_id = ? AND date = ?",
               (athlete_id, day))
    return {"deleted": day}


@ROUTER.get("/api/wellness/today")
def wellness_today(request):
    """Tableau de suivi : qui a rempli son questionnaire, et dans quel état."""
    day = request.q("date") or date.today().isoformat()
    athletes = db.query(
        "SELECT id, first_name, last_name, accent, status FROM athletes"
        " WHERE status != 'archived' ORDER BY last_name")
    for athlete in athletes:
        entry = db.query_one(
            "SELECT * FROM wellness WHERE athlete_id = ? AND date = ?",
            (athlete["id"], day))
        athlete["wellness"] = entry
        athlete["submitted"] = entry is not None
        athlete["readiness"] = entry["readiness"] if entry else None
        athlete["flag"] = entry["readiness_flag"] if entry else "inconnu"
    submitted = sum(1 for a in athletes if a["submitted"])
    return {"date": day, "athletes": athletes, "submitted": submitted,
            "total": len(athletes)}


@ROUTER.get("/api/athletes/<int:athlete_id>/hrv")
def hrv_analysis(request):
    """Analyse VFC complète : ligne de base, plage normale, tendance."""
    athlete_id = request.params["athlete_id"]
    days = request.q_int("days", 180)
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = db.query(
        "SELECT date, hrv_rmssd, hrv_ln_rmssd, resting_hr, sleep_total_min"
        " FROM wellness WHERE athlete_id = ? AND date >= ? ORDER BY date",
        (athlete_id, since))
    ln = [r.get("hrv_ln_rmssd") for r in rows]
    baseline7 = HRV.rolling_baseline(ln, 7)
    baseline30 = HRV.rolling_baseline(ln, 30)
    low, mean, high = HRV.normal_range(ln)
    cv_series = []
    for i in range(len(ln)):
        cv_series.append(HRV.coefficient_of_variation(ln[:i + 1]))
    cv_baseline = None
    valid_cv = [c for c in cv_series[:-7] if c is not None]
    if len(valid_cv) >= 10:
        cv_baseline = round(statistics.fmean(valid_cv), 2)

    rhr = [r.get("resting_hr") for r in rows]
    rhr_baseline = HRV.rolling_baseline(rhr, 14)
    points = []
    for i, row in enumerate(rows):
        points.append({
            "date": row["date"],
            "rmssd": row.get("hrv_rmssd"),
            "ln_rmssd": ln[i],
            "baseline_7d": baseline7[i],
            "baseline_30d": baseline30[i],
            "cv_7d": cv_series[i],
            "resting_hr": rhr[i],
            "rhr_baseline_14d": rhr_baseline[i],
        })
    return {
        "points": points,
        "normal_range": {"low": low, "mean": mean, "high": high},
        "cv": cv_series[-1] if cv_series else None,
        "cv_baseline": cv_baseline,
        "status": HRV.hrv_status(baseline7[-1] if baseline7 else None, low, high,
                                 cv_series[-1] if cv_series else None, cv_baseline),
        "rhr_deviation": HRV.rhr_deviation(
            rhr[-1] if rhr else None, rhr_baseline[-1] if rhr_baseline else None),
        "method": ("Suivi sur la moyenne glissante 7 jours de ln(RMSSD), comparée à "
                   "une plage normale de ±0,5 écart-type calculée sur 60 jours "
                   "(Plews, Laursen & Buchheit). La valeur d'un jour isolé est trop "
                   "bruitée pour décider quoi que ce soit."),
    }
