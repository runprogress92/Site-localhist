"""Endpoints Planification : séances prévues, blocs, objectifs, affûtage."""
from __future__ import annotations

import json
from datetime import date, timedelta

from .. import db
from ..science import pmc as PMC
from ..server import ROUTER, bad_request, not_found

WORKOUT_FIELDS = ("date", "sport", "name", "description", "structure",
                  "target_load", "target_duration_s", "target_distance_m",
                  "intensity", "status", "coach_notes")

# Charge produite par une séance ENTIÈRE de ce type, par heure — échauffement
# et retour au calme compris. Ce n'est pas l'intensité du bloc principal :
# une séance « au seuil » ne se court pas au seuil de bout en bout, et retenir
# 95 points/heure produirait des séances deux fois trop courtes.
# Valeurs mesurées sur les séances de référence du générateur.
INTENSITY_TEMPLATES = {
    "récupération": {"load_per_hour": 32, "color": "#5b8fd6"},
    "endurance": {"load_per_hour": 51, "color": "#3fb98c"},
    "tempo": {"load_per_hour": 65, "color": "#c9c04a"},
    "seuil": {"load_per_hour": 74, "color": "#e08d3c"},
    "VO2max": {"load_per_hour": 70, "color": "#d8543f"},
    "neuromusculaire": {"load_per_hour": 58, "color": "#7b56c9"},
    "compétition": {"load_per_hour": 100, "color": "#b1418b"},
}


@ROUTER.get("/api/athletes/<int:athlete_id>/planned")
def list_planned(request):
    athlete_id = request.params["athlete_id"]
    start = request.q("from") or date.today().isoformat()
    end = request.q("to") or (date.today() + timedelta(days=28)).isoformat()
    rows = db.query(
        "SELECT p.*, a.name AS completed_name, a.load AS completed_load,"
        " a.duration_s AS completed_duration FROM planned_workouts p"
        " LEFT JOIN activities a ON a.id = p.completed_activity_id"
        " WHERE p.athlete_id = ? AND p.date BETWEEN ? AND ? ORDER BY p.date",
        (athlete_id, start, end))
    for row in rows:
        if row.get("structure"):
            try:
                row["structure"] = json.loads(row["structure"])
            except (json.JSONDecodeError, TypeError):
                pass
    return {"planned": rows, "templates": INTENSITY_TEMPLATES}


@ROUTER.post("/api/athletes/<int:athlete_id>/planned")
def create_planned(request):
    athlete_id = request.params["athlete_id"]
    payload = request.json
    data = {k: payload[k] for k in WORKOUT_FIELDS if k in payload}
    if not data.get("date") or not data.get("name"):
        raise bad_request("La date et le nom de la séance sont obligatoires.")
    data.setdefault("sport", "running")
    if isinstance(data.get("structure"), (list, dict)):
        data["structure"] = json.dumps(data["structure"], ensure_ascii=False)
    if not data.get("target_load") and data.get("target_duration_s") and data.get("intensity"):
        template = INTENSITY_TEMPLATES.get(data["intensity"])
        if template:
            data["target_load"] = round(
                template["load_per_hour"] * data["target_duration_s"] / 3600, 1)
    data["athlete_id"] = athlete_id
    workout_id = db.insert("planned_workouts", data)
    return {"id": workout_id}, 201


@ROUTER.patch("/api/planned/<int:workout_id>")
def update_planned(request):
    workout_id = request.params["workout_id"]
    if not db.query_one("SELECT id FROM planned_workouts WHERE id = ?", (workout_id,)):
        raise not_found("Séance planifiée introuvable.")
    payload = request.json
    data = {k: payload[k] for k in WORKOUT_FIELDS if k in payload}
    if isinstance(data.get("structure"), (list, dict)):
        data["structure"] = json.dumps(data["structure"], ensure_ascii=False)
    if "completed_activity_id" in payload:
        data["completed_activity_id"] = payload["completed_activity_id"]
    if not data:
        raise bad_request("Aucun champ modifiable fourni.")
    db.update("planned_workouts", workout_id, data)
    return {"updated": workout_id}


@ROUTER.delete("/api/planned/<int:workout_id>")
def delete_planned(request):
    db.delete("planned_workouts", request.params["workout_id"])
    return {"deleted": request.params["workout_id"]}


@ROUTER.post("/api/athletes/<int:athlete_id>/planned/match")
def match_planned(request):
    """Rapproche automatiquement séances prévues et séances réalisées.

    Une séance planifiée est considérée réalisée si une activité du même
    sport existe le même jour ; la conformité compare la charge obtenue à la
    charge visée.
    """
    athlete_id = request.params["athlete_id"]
    start = request.q("from") or (date.today() - timedelta(days=60)).isoformat()
    planned = db.query(
        "SELECT * FROM planned_workouts WHERE athlete_id = ? AND date >= ?"
        " AND status IN ('planned','missed')", (athlete_id, start))
    matched = 0
    for workout in planned:
        candidate = db.query_one(
            "SELECT id, load, duration_s FROM activities WHERE athlete_id = ?"
            " AND local_date = ? AND sport = ? ORDER BY duration_s DESC LIMIT 1",
            (athlete_id, workout["date"], workout["sport"]))
        if candidate:
            compliance = None
            if workout.get("target_load") and candidate.get("load"):
                compliance = round(100 * candidate["load"] / workout["target_load"], 1)
            db.update("planned_workouts", workout["id"], {
                "status": "completed", "completed_activity_id": candidate["id"],
                "compliance_pct": compliance})
            matched += 1
        elif workout["date"] < date.today().isoformat():
            db.update("planned_workouts", workout["id"], {"status": "missed"})
    return {"matched": matched, "reviewed": len(planned)}


@ROUTER.get("/api/athletes/<int:athlete_id>/compliance")
def compliance(request):
    """Taux de réalisation du plan sur les dernières semaines."""
    athlete_id = request.params["athlete_id"]
    weeks = request.q_int("weeks", 12)
    since = (date.today() - timedelta(weeks=weeks)).isoformat()
    rows = db.query(
        "SELECT date(date, 'weekday 0', '-6 days') AS week,"
        " COUNT(*) AS planned,"
        " SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,"
        " SUM(CASE WHEN status = 'missed' THEN 1 ELSE 0 END) AS missed,"
        " AVG(compliance_pct) AS mean_compliance,"
        " SUM(target_load) AS target_load"
        " FROM planned_workouts WHERE athlete_id = ? AND date >= ?"
        " GROUP BY week ORDER BY week", (athlete_id, since))
    actual = {r["week"]: r["load"] for r in db.query(
        "SELECT date(local_date, 'weekday 0', '-6 days') AS week,"
        " SUM(load) AS load FROM activities WHERE athlete_id = ? AND local_date >= ?"
        " GROUP BY week", (athlete_id, since))}
    for row in rows:
        row["actual_load"] = round(actual.get(row["week"], 0) or 0, 1)
        row["rate"] = (round(100 * row["completed"] / row["planned"], 1)
                       if row["planned"] else None)
    # Les séances encore à venir ne peuvent pas être « manquées » : les
    # inclure dans le dénominateur ferait chuter le taux sans raison.
    today = date.today().isoformat()
    past = db.query_one(
        "SELECT COUNT(*) AS planned,"
        " SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed"
        " FROM planned_workouts WHERE athlete_id = ? AND date >= ? AND date < ?",
        (athlete_id, since, today)) or {}
    total_planned = past.get("planned") or 0
    total_done = past.get("completed") or 0
    return {"weeks": rows,
            "overall_rate": round(100 * total_done / total_planned, 1) if total_planned else None,
            "planned": total_planned, "completed": total_done,
            "upcoming": sum(r["planned"] for r in rows) - total_planned}


# -------------------------------------------------------------------- blocs
@ROUTER.get("/api/athletes/<int:athlete_id>/blocks")
def list_blocks(request):
    athlete_id = request.params["athlete_id"]
    return {"blocks": db.query(
        "SELECT * FROM training_blocks WHERE athlete_id = ? ORDER BY start_date DESC",
        (athlete_id,))}


@ROUTER.post("/api/athletes/<int:athlete_id>/blocks")
def create_block(request):
    athlete_id = request.params["athlete_id"]
    payload = request.json
    fields = ("name", "phase", "focus", "start_date", "end_date", "target_ctl",
              "target_weekly_load", "notes")
    data = {k: payload[k] for k in fields if k in payload}
    if not data.get("name") or not data.get("start_date") or not data.get("end_date"):
        raise bad_request("Nom, date de début et date de fin sont obligatoires.")
    data["athlete_id"] = athlete_id
    return {"id": db.insert("training_blocks", data)}, 201


@ROUTER.delete("/api/blocks/<int:block_id>")
def delete_block(request):
    db.delete("training_blocks", request.params["block_id"])
    return {"deleted": request.params["block_id"]}


# ---------------------------------------------------------------- objectifs
@ROUTER.get("/api/athletes/<int:athlete_id>/events")
def list_events(request):
    athlete_id = request.params["athlete_id"]
    rows = db.query("SELECT * FROM events WHERE athlete_id = ? ORDER BY date DESC",
                    (athlete_id,))
    today = date.today()
    for row in rows:
        row["days_out"] = (date.fromisoformat(row["date"]) - today).days
    return {"events": rows}


@ROUTER.post("/api/athletes/<int:athlete_id>/events")
def create_event(request):
    athlete_id = request.params["athlete_id"]
    payload = request.json
    fields = ("name", "date", "sport", "priority", "location", "distance_m",
              "target_time_s", "result_time_s", "result_rank", "result_notes", "notes")
    data = {k: payload[k] for k in fields if k in payload}
    if not data.get("name") or not data.get("date"):
        raise bad_request("Le nom et la date de l'objectif sont obligatoires.")
    data["athlete_id"] = athlete_id
    return {"id": db.insert("events", data)}, 201


@ROUTER.patch("/api/events/<int:event_id>")
def update_event(request):
    event_id = request.params["event_id"]
    fields = ("name", "date", "sport", "priority", "location", "distance_m",
              "target_time_s", "result_time_s", "result_rank", "result_notes", "notes")
    data = {k: request.json[k] for k in fields if k in request.json}
    if not data:
        raise bad_request("Aucun champ modifiable fourni.")
    db.update("events", event_id, data)
    return {"updated": event_id}


@ROUTER.delete("/api/events/<int:event_id>")
def delete_event(request):
    db.delete("events", request.params["event_id"])
    return {"deleted": request.params["event_id"]}


# ---------------------------------------------------------------- affûtage
@ROUTER.get("/api/athletes/<int:athlete_id>/taper")
def taper(request):
    """Simule un affûtage jusqu'à une date cible et une fenêtre de forme visée.

    Cherche la charge quotidienne constante qui amène le TSB à la valeur
    demandée le jour J, puis renvoie la trajectoire complète CTL/ATL/TSB.
    """
    athlete_id = request.params["athlete_id"]
    target_date = request.q("date")
    target_tsb = request.q_float("tsb", 15.0)

    # Ne pas avoir d'objectif ni d'historique est un état normal pour un
    # athlète qu'on vient de créer, pas une erreur de la requête : on répond
    # 200 avec la raison, que l'interface peut afficher telle quelle.
    def unavailable(reason: str) -> dict:
        return {"available": False, "reason": reason, "trajectory": [],
                "target_date": target_date}

    if not target_date:
        event = db.query_one(
            "SELECT date, name FROM events WHERE athlete_id = ? AND date >= ?"
            " AND priority = 'A' ORDER BY date LIMIT 1",
            (athlete_id, date.today().isoformat()))
        if not event:
            return unavailable("Aucun objectif de priorité A à venir. Ajoutez un "
                               "objectif, ou indiquez une date cible.")
        target_date = event["date"]

    days = (date.fromisoformat(target_date) - date.today()).days
    if days < 1:
        return unavailable("La date cible doit être dans le futur.")
    if days > 120:
        return unavailable("L'horizon de simulation est limité à 120 jours : "
                           "au-delà, la projection n'a plus de valeur pratique.")

    current = db.query_one(
        "SELECT ctl, atl, tsb FROM daily_load WHERE athlete_id = ?"
        " ORDER BY date DESC LIMIT 1", (athlete_id,))
    if not current or not current.get("ctl"):
        return unavailable("Historique de charge insuffisant : il faut quelques "
                           "semaines de séances pour simuler un affûtage.")

    taper_days = min(days, request.q_int("taper_days", 14))
    loads = PMC.taper_plan(current["ctl"] or 0, current["atl"] or 0, days,
                           target_tsb, taper_days)
    trajectory = PMC.project_forward(current["ctl"] or 0, current["atl"] or 0, loads)
    for i, point in enumerate(trajectory):
        point["date"] = (date.today() + timedelta(days=i + 1)).isoformat()

    weekly = round(loads[-1] * 7, 1) if loads else 0
    baseline_weekly = round((current["ctl"] or 0) * 7, 1)
    reduction = (round(100 * (1 - weekly / baseline_weekly), 1)
                 if baseline_weekly else None)
    return {
        "available": True,
        "target_date": target_date, "target_tsb": target_tsb, "days": days,
        "taper_days": taper_days,
        "hold_days": days - taper_days,
        "hold_daily_load": loads[0] if loads else 0,
        "daily_load": loads[-1] if loads else 0,
        "weekly_load": weekly, "baseline_weekly_load": baseline_weekly,
        "reduction_pct": reduction,
        "trajectory": trajectory,
        "final": trajectory[-1] if trajectory else None,
        "ctl_cost": round((trajectory[-1]["ctl"] - (current["ctl"] or 0)), 1)
        if trajectory else None,
        "guidance": ("La littérature sur l'affûtage (Bosquet et al., 2007) situe le "
                     "gain optimal autour de −40 à −60 % de volume sur 8 à 14 jours, "
                     "à intensité maintenue et fréquence des séances conservée. "
                     "Réduisez la durée des séances, pas leur qualité."),
    }


@ROUTER.post("/api/athletes/<int:athlete_id>/planned/generate")
def generate_week(request):
    """Génère une semaine type à partir d'une charge hebdomadaire cible.

    Répartition polarisée : deux séances de qualité, le reste en aisance,
    un jour de repos, et la séance longue le week-end.
    """
    athlete_id = request.params["athlete_id"]
    payload = request.json
    target = float(payload.get("weekly_load") or 0)
    if target <= 0:
        current = db.query_one(
            "SELECT ctl FROM daily_load WHERE athlete_id = ? ORDER BY date DESC LIMIT 1",
            (athlete_id,))
        target = round((current["ctl"] or 40) * 7 * 1.05, 1) if current else 300
    start = date.fromisoformat(payload.get("start") or date.today().isoformat())
    start = start - timedelta(days=start.weekday())      # lundi
    sport = payload.get("sport") or "running"
    replace = bool(payload.get("replace"))

    # part de charge par jour : L repos, Ma qualité, Me facile, J seuil,
    # V facile, S longue, D récup
    shape = [
        (0, None, None),
        (1, "VO2max", 0.16), (2, "endurance", 0.12), (3, "seuil", 0.18),
        (4, "récupération", 0.08), (5, "endurance", 0.32), (6, "endurance", 0.14),
    ]
    names = {
        "VO2max": "Intervalles courts — VO2max",
        "seuil": "Séance au seuil",
        "endurance": "Endurance fondamentale",
        "récupération": "Footing de récupération",
    }
    if replace:
        db.execute(
            "DELETE FROM planned_workouts WHERE athlete_id = ? AND date BETWEEN ? AND ?"
            " AND status = 'planned'",
            (athlete_id, start.isoformat(), (start + timedelta(days=6)).isoformat()))

    created = []
    for offset, intensity, share in shape:
        if intensity is None:
            continue
        day = start + timedelta(days=offset)
        load = round(target * share, 1)
        template = INTENSITY_TEMPLATES[intensity]
        duration = round(load / template["load_per_hour"] * 3600)
        workout_id = db.insert("planned_workouts", {
            "athlete_id": athlete_id, "date": day.isoformat(), "sport": sport,
            "name": names[intensity], "intensity": intensity,
            "target_load": load, "target_duration_s": duration,
            "description": _describe(intensity, duration),
            "status": "planned"})
        created.append({"id": workout_id, "date": day.isoformat(),
                        "name": names[intensity], "target_load": load,
                        "target_duration_s": duration})
    return {"created": created, "weekly_load": target,
            "rest_day": start.isoformat()}, 201


def _describe(intensity: str, duration_s: float) -> str:
    minutes = round(duration_s / 60)
    if intensity == "VO2max":
        return (f"Échauffement 20 min · 6 à 8 × 3 min en zone 5 avec 2 min de "
                f"récupération trottinée · retour au calme 10 min (≈ {minutes} min).")
    if intensity == "seuil":
        return (f"Échauffement 20 min · 2 × 15 min au seuil (zone 4) avec 5 min "
                f"de récupération · retour au calme 10 min (≈ {minutes} min).")
    if intensity == "récupération":
        return f"Footing très souple en zone 1, {minutes} min, aucune intensité."
    return (f"Sortie continue en zone 2, {minutes} min. Terminer aussi frais "
            "qu'au départ : c'est le critère de réussite d'une séance d'endurance.")
