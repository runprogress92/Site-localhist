"""Endpoints Système : réglages, équipes, état, sauvegarde, jeu de démonstration."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from .. import db, settings
from ..ingest import pipeline
from ..server import ROUTER, Response, bad_request

ROOT = Path(__file__).resolve().parent.parent.parent


@ROUTER.get("/api/health")
def health(request):
    return {
        "status": "ok",
        "app": "Athlytics",
        "version": "1.0.0",
        "python": sys.version.split()[0],
        "time": db.now_iso(),
        "database": db.db_stats(),
    }


@ROUTER.get("/api/config")
def get_config(request):
    return {"config": settings.public_config(),
            "sports": pipeline.SPORT_LABELS}


@ROUTER.patch("/api/config")
def update_config(request):
    """Modifie les réglages persistés en base (seuils, pondérations, identité)."""
    payload = request.json
    updated = {}
    for key in ("coach_name", "week_start", "units", "timezone"):
        if key in payload:
            db.set_setting(key, payload[key])
            updated[key] = payload[key]
    if "thresholds" in payload:
        db.set_setting("thresholds", payload["thresholds"])
        updated["thresholds"] = payload["thresholds"]
    if "readiness_weights" in payload:
        weights = payload["readiness_weights"]
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            got = f"{total:.2f}".replace(".", ",")
            raise bad_request("La somme des pondérations doit valoir 1,00 "
                              f"(reçu {got}).")
        db.set_setting("readiness_weights", weights)
        updated["readiness_weights"] = weights
    return {"updated": updated}


# ------------------------------------------------------------------ équipes
@ROUTER.get("/api/teams")
def list_teams(request):
    rows = db.query(
        "SELECT t.*, COUNT(a.id) AS athletes FROM teams t"
        " LEFT JOIN athletes a ON a.team_id = t.id AND a.status != 'archived'"
        " GROUP BY t.id ORDER BY t.name")
    return {"teams": rows}


@ROUTER.post("/api/teams")
def create_team(request):
    payload = request.json
    if not payload.get("name"):
        raise bad_request("Le nom de l'équipe est obligatoire.")
    data = {k: payload[k] for k in ("name", "sport", "coach", "season", "color", "notes")
            if k in payload}
    return {"id": db.insert("teams", data)}, 201


@ROUTER.delete("/api/teams/<int:team_id>")
def delete_team(request):
    db.delete("teams", request.params["team_id"])
    return {"deleted": request.params["team_id"]}


# ------------------------------------------------------------- maintenance
@ROUTER.post("/api/admin/rebuild")
def rebuild(request):
    """Recalcule agrégats quotidiens et alertes pour tous les athlètes."""
    athlete_id = request.json.get("athlete_id") or request.q_int("athlete_id")
    targets = ([athlete_id] if athlete_id else
               [a["id"] for a in db.query("SELECT id FROM athletes")])
    results = {}
    for target in targets:
        try:
            results[target] = pipeline.rebuild_daily(target)
        except Exception as exc:
            results[target] = {"error": str(exc)}
    return {"rebuilt": len(results), "results": results}


@ROUTER.post("/api/admin/reanalyze")
def reanalyze_all(request):
    """Réanalyse toutes les séances d'un athlète depuis leurs flux stockés."""
    athlete_id = request.json.get("athlete_id") or request.q_int("athlete_id")
    if not athlete_id:
        raise bad_request("Paramètre athlete_id obligatoire.")
    since = request.json.get("since") or "1970-01-01"
    activities = db.query(
        "SELECT id FROM activities WHERE athlete_id = ? AND has_streams = 1"
        " AND local_date >= ? ORDER BY local_date", (athlete_id, since))
    done, failed = 0, []
    for activity in activities:
        try:
            pipeline.reanalyze_activity(activity["id"])
            done += 1
        except Exception as exc:
            failed.append({"id": activity["id"], "error": str(exc)})
    pipeline.rebuild_daily(athlete_id)
    return {"reanalyzed": done, "failed": failed, "total": len(activities)}


@ROUTER.get("/api/admin/backup")
def backup(request):
    """Télécharge une copie cohérente de la base (VACUUM INTO)."""
    target = ROOT / "data" / f"athlytics-sauvegarde-{date.today().isoformat()}.db"
    if target.exists():
        target.unlink()
    db.connection().execute("VACUUM INTO ?", (str(target),))
    blob = target.read_bytes()
    target.unlink(missing_ok=True)
    return Response(blob, "application/vnd.sqlite3", headers={
        "Content-Disposition": f'attachment; filename="{target.name}"'})


@ROUTER.get("/api/admin/routes")
def list_routes(request):
    from ..server import ROUTER as router
    return {"routes": sorted(router.list_routes(), key=lambda r: r["pattern"])}


@ROUTER.post("/api/admin/seed")
def seed(request):
    """(Re)génère le jeu de données de démonstration."""
    from ..seed.generate import generate
    payload = request.json
    if db.scalar("SELECT COUNT(*) FROM athletes", default=0) and not payload.get("force"):
        raise bad_request("La base contient déjà des athlètes. "
                          "Passez force: true pour la réinitialiser.")
    result = generate(
        athletes=int(payload.get("athletes", 8)),
        days=int(payload.get("days", 400)),
        stream_days=int(payload.get("stream_days", 120)),
        reset=True, verbose=False)
    return {"seeded": result}


@ROUTER.delete("/api/admin/reset")
def reset(request):
    """Vide toutes les données (conserve le schéma)."""
    if not request.q_bool("confirm"):
        raise bad_request("Ajoutez ?confirm=true pour confirmer l'effacement total.")
    tables = ["best_efforts", "activity_zone_time", "activity_laps",
              "activity_streams", "activities", "wellness", "daily_load",
              "planned_workouts", "training_blocks", "events", "lactate_points",
              "lab_tests", "injuries", "alerts", "coach_notes", "sync_log",
              "provider_accounts", "devices", "oauth_states", "physiology",
              "zones", "zone_models", "athletes", "teams"]
    for table in tables:
        db.execute(f"DELETE FROM {table}")
    db.execute("VACUUM")
    return {"reset": True, "tables": len(tables)}


@ROUTER.get("/api/admin/stats")
def stats(request):
    """Statistiques globales pour la page Réglages."""
    volume = db.query_one(
        "SELECT COUNT(*) AS activities, COALESCE(SUM(duration_s),0) AS duration_s,"
        " COALESCE(SUM(distance_m),0) AS distance_m,"
        " COALESCE(SUM(elevation_gain_m),0) AS elevation_m,"
        " MIN(local_date) AS first_date, MAX(local_date) AS last_date"
        " FROM activities")
    by_provider = db.query(
        "SELECT provider, COUNT(*) AS n FROM activities GROUP BY provider ORDER BY n DESC")
    by_sport = db.query(
        "SELECT sport, COUNT(*) AS n, COALESCE(SUM(duration_s),0) AS duration_s"
        " FROM activities GROUP BY sport ORDER BY n DESC")
    streams = db.query_one(
        "SELECT COUNT(*) AS series, COALESCE(SUM(LENGTH(data)),0) AS bytes,"
        " COALESCE(SUM(n_samples),0) AS samples FROM activity_streams")
    return {"database": db.db_stats(), "volume": volume, "by_provider": by_provider,
            "by_sport": by_sport, "streams": streams}
