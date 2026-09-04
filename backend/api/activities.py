"""Endpoints Activités : liste, détail, flux, import de fichiers, export."""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta

from .. import db, profiles
from ..ingest import pipeline
from ..science import power as PW
from ..science import running as RUN
from ..science import zones as Z
from ..server import ROUTER, Response, bad_request, not_found

SPORT_LABELS = pipeline.SPORT_LABELS


@ROUTER.get("/api/activities")
def list_activities(request):
    """Liste filtrable et paginée."""
    where = []
    params: list = []
    if request.q_int("athlete_id"):
        where.append("a.athlete_id = ?")
        params.append(request.q_int("athlete_id"))
    if request.q("sport"):
        where.append("a.sport = ?")
        params.append(request.q("sport"))
    if request.q("from"):
        where.append("a.local_date >= ?")
        params.append(request.q("from"))
    if request.q("to"):
        where.append("a.local_date <= ?")
        params.append(request.q("to"))
    if request.q("search"):
        where.append("(a.name LIKE ? OR a.notes LIKE ? OR a.tags LIKE ?)")
        needle = f"%{request.q('search')}%"
        params += [needle, needle, needle]
    if request.q("provider"):
        where.append("a.provider = ?")
        params.append(request.q("provider"))
    if request.q_float("min_duration"):
        where.append("a.duration_s >= ?")
        params.append(request.q_float("min_duration") * 60)

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = db.scalar(f"SELECT COUNT(*) FROM activities a{clause}", params, 0)
    limit = min(500, request.q_int("limit", 50))
    offset = request.q_int("offset", 0)
    sort = request.q("sort", "start_time")
    if sort not in ("start_time", "duration_s", "distance_m", "load", "avg_hr",
                    "np_w", "elevation_gain_m"):
        sort = "start_time"
    direction = "ASC" if request.q("order", "desc").lower() == "asc" else "DESC"

    rows = db.query(
        "SELECT a.*, ath.first_name, ath.last_name, ath.accent"
        " FROM activities a JOIN athletes ath ON ath.id = a.athlete_id"
        f"{clause} ORDER BY a.{sort} {direction} LIMIT ? OFFSET ?",
        params + [limit, offset])
    for row in rows:
        row["sport_label"] = SPORT_LABELS.get(row["sport"], row["sport"])
        if row.get("avg_speed_ms") and row["sport"] in ("running", "trail_running"):
            row["pace_s_km"] = RUN.speed_to_pace(row["avg_speed_ms"])
    return {"activities": rows, "total": total, "limit": limit, "offset": offset}


@ROUTER.get("/api/activities/<int:activity_id>")
def get_activity(request):
    activity_id = request.params["activity_id"]
    activity = db.query_one(
        "SELECT a.*, ath.first_name, ath.last_name, ath.sex, ath.accent"
        " FROM activities a JOIN athletes ath ON ath.id = a.athlete_id"
        " WHERE a.id = ?", (activity_id,))
    if not activity:
        raise not_found("Activité introuvable.")
    activity["sport_label"] = SPORT_LABELS.get(activity["sport"], activity["sport"])
    activity["laps"] = db.query(
        "SELECT * FROM activity_laps WHERE activity_id = ? ORDER BY idx", (activity_id,))
    activity["zone_times"] = db.query(
        "SELECT kind, zone_idx, seconds FROM activity_zone_time"
        " WHERE activity_id = ? ORDER BY kind, zone_idx", (activity_id,))
    ctx = profiles.athlete_context(activity["athlete_id"], activity["local_date"])
    activity["zones"] = ctx["zones"]
    activity["context"] = {
        "ftp_w": ctx["ftp_w"], "lthr": ctx["lthr"], "hr_max": ctx["hr_max"],
        "hr_rest": ctx["hr_rest"], "weight_kg": ctx["weight_kg"],
        "threshold_pace_s_km": ctx["threshold_pace_s_km"],
        "cp_w": ctx["cp_w"], "w_prime_j": ctx["w_prime_j"],
    }
    activity["best_efforts"] = db.query(
        "SELECT kind, duration_s, value, value_per_kg, start_offset_s"
        " FROM best_efforts WHERE activity_id = ? ORDER BY kind, duration_s",
        (activity_id,))
    if activity.get("avg_speed_ms") and activity["sport"] in ("running", "trail_running"):
        activity["pace_s_km"] = RUN.speed_to_pace(activity["avg_speed_ms"])

    # comparaison à la moyenne des 90 derniers jours pour le même sport
    since = (date.fromisoformat(activity["local_date"]) - timedelta(days=90)).isoformat()
    activity["baseline"] = db.query_one(
        "SELECT AVG(load) AS load, AVG(duration_s) AS duration_s,"
        " AVG(distance_m) AS distance_m, AVG(efficiency_factor) AS efficiency_factor,"
        " AVG(avg_hr) AS avg_hr, COUNT(*) AS n FROM activities"
        " WHERE athlete_id = ? AND sport = ? AND local_date BETWEEN ? AND ?"
        " AND id != ?", (activity["athlete_id"], activity["sport"], since,
                         activity["local_date"], activity_id))
    return activity


@ROUTER.get("/api/activities/<int:activity_id>/streams")
def get_streams(request):
    """Flux temporels, éventuellement rééchantillonnés pour l'affichage."""
    activity_id = request.params["activity_id"]
    activity = db.query_one("SELECT * FROM activities WHERE id = ?", (activity_id,))
    if not activity:
        raise not_found("Activité introuvable.")
    requested = request.q("kinds")
    kinds = requested.split(",") if requested else None
    streams = db.load_streams(activity_id, kinds)
    if not streams:
        return {"streams": {}, "n": 0, "resolution": 0}

    length = max(len(v) for v in streams.values())
    target = min(request.q_int("points", 2000), 20000)
    step = max(1, length // target) if target else 1
    if step > 1:
        streams = {k: _downsample(v, step) for k, v in streams.items()}

    ctx = profiles.athlete_context(activity["athlete_id"], activity["local_date"])
    derived = {}
    if request.q_bool("derived", True):
        raw = db.load_streams(activity_id)
        power = raw.get("power")
        if power and ctx.get("cp_w") and ctx.get("w_prime_j"):
            balance = PW.w_bal(power, ctx["cp_w"], ctx["w_prime_j"])
            derived["w_bal"] = _downsample(balance, step)
        if power:
            derived["power_30s"] = _downsample(
                [round(v, 1) for v in PW.rolling_mean(
                    [p or 0 for p in power], 30)], step)
        if raw.get("speed") and activity["sport"] in ("running", "trail_running"):
            gap = RUN.gap_speed_series(raw["speed"], raw.get("altitude") or [],
                                       raw.get("distance"))
            derived["gap_speed"] = _downsample([round(v, 3) for v in gap], step)
    return {"streams": streams, "derived": derived, "n": length,
            "step": step, "resolution": step}


def _downsample(values: list, step: int) -> list:
    """Sous-échantillonnage par moyenne de bloc (préserve la forme du signal)."""
    if step <= 1:
        return values
    out = []
    for i in range(0, len(values), step):
        chunk = [v for v in values[i:i + step] if v is not None]
        if not chunk:
            out.append(None)
        elif isinstance(chunk[0], (int, float)):
            out.append(round(sum(chunk) / len(chunk), 4))
        else:
            out.append(chunk[0])
    return out


@ROUTER.patch("/api/activities/<int:activity_id>")
def update_activity(request):
    activity_id = request.params["activity_id"]
    activity = db.query_one("SELECT * FROM activities WHERE id = ?", (activity_id,))
    if not activity:
        raise not_found("Activité introuvable.")
    payload = request.json
    fields = ("name", "notes", "tags", "rpe", "feel", "sport", "sub_sport", "weather")
    data = {k: payload[k] for k in fields if k in payload}
    if "rpe" in data and data["rpe"]:
        from ..science import load as L
        data["session_rpe"] = L.session_rpe(activity["duration_s"], data["rpe"])
        if not activity.get("load"):
            data["load"] = L.rpe_to_tss_equivalent(activity["duration_s"], data["rpe"])
            data["load_source"] = "rpe"
    if not data:
        raise bad_request("Aucun champ modifiable fourni.")
    data["updated_at"] = db.now_iso()
    db.update("activities", activity_id, data)
    if "load" in data or "sport" in data:
        pipeline.rebuild_daily(activity["athlete_id"])
    return {"updated": activity_id}


@ROUTER.delete("/api/activities/<int:activity_id>")
def delete_activity(request):
    activity_id = request.params["activity_id"]
    activity = db.query_one("SELECT athlete_id FROM activities WHERE id = ?",
                            (activity_id,))
    if not activity:
        raise not_found("Activité introuvable.")
    db.delete("activities", activity_id)
    pipeline.rebuild_daily(activity["athlete_id"])
    return {"deleted": activity_id}


@ROUTER.post("/api/activities/<int:activity_id>/reanalyze")
def reanalyze(request):
    activity_id = request.params["activity_id"]
    result = pipeline.reanalyze_activity(activity_id)
    activity = db.query_one("SELECT athlete_id FROM activities WHERE id = ?",
                            (activity_id,))
    if activity:
        pipeline.rebuild_daily(activity["athlete_id"])
    return result


# ---------------------------------------------------------------- import
@ROUTER.post("/api/activities/upload")
def upload(request):
    """Import de un ou plusieurs fichiers .fit, .tcx ou .gpx."""
    athlete_id = request.q_int("athlete_id")
    if not athlete_id:
        raise bad_request("Paramètre athlete_id obligatoire.")
    if not db.query_one("SELECT id FROM athletes WHERE id = ?", (athlete_id,)):
        raise not_found(f"Athlète {athlete_id} introuvable.")
    files = request.files()
    if not files:
        raise bad_request("Aucun fichier reçu (champ multipart « file » attendu).")

    results, errors = [], []
    for item in files:
        try:
            outcome = pipeline.import_file(
                athlete_id, item["data"], item["filename"],
                provider=request.q("provider", "manual"))
            results.append({"filename": item["filename"], **outcome})
        except Exception as exc:
            errors.append({"filename": item["filename"], "error": str(exc)})
    if results:
        pipeline.rebuild_daily(athlete_id)
    status = 201 if results else 400
    return {"imported": len(results), "results": results, "errors": errors}, status


# ---------------------------------------------------------------- exports
@ROUTER.get("/api/activities/<int:activity_id>/export.csv")
def export_streams_csv(request):
    activity_id = request.params["activity_id"]
    activity = db.query_one("SELECT * FROM activities WHERE id = ?", (activity_id,))
    if not activity:
        raise not_found("Activité introuvable.")
    streams = db.load_streams(activity_id)
    if not streams:
        raise bad_request("Cette activité ne contient pas de flux détaillé.")
    order = [k for k in ("time", "distance", "heart_rate", "power", "speed",
                         "cadence", "altitude", "temperature", "lat", "lon")
             if k in streams]
    order += [k for k in streams if k not in order]
    length = max(len(v) for v in streams.values())
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(order)
    for i in range(length):
        writer.writerow([streams[k][i] if i < len(streams[k]) else "" for k in order])
    filename = f"activite-{activity_id}-{activity['local_date']}.csv"
    return Response(buffer.getvalue().encode("utf-8"), "text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@ROUTER.get("/api/activities/export.csv")
def export_activities_csv(request):
    """Export tabulaire de la liste des séances (filtres identiques à /api/activities)."""
    athlete_id = request.q_int("athlete_id")
    where, params = [], []
    if athlete_id:
        where.append("a.athlete_id = ?")
        params.append(athlete_id)
    if request.q("from"):
        where.append("a.local_date >= ?")
        params.append(request.q("from"))
    if request.q("to"):
        where.append("a.local_date <= ?")
        params.append(request.q("to"))
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    rows = db.query(
        "SELECT ath.last_name, ath.first_name, a.local_date, a.start_time, a.sport,"
        " a.name, a.duration_s, a.distance_m, a.elevation_gain_m, a.avg_hr, a.max_hr,"
        " a.avg_power_w, a.np_w, a.intensity_factor, a.load, a.load_source,"
        " a.trimp_banister, a.efficiency_factor, a.decoupling_pct, a.rpe, a.calories"
        f" FROM activities a JOIN athletes ath ON ath.id = a.athlete_id{clause}"
        " ORDER BY a.start_time DESC", params)
    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    return Response(buffer.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             'attachment; filename="activites.csv"'})


@ROUTER.get("/api/activities/<int:activity_id>/export.fit")
def export_fit(request):
    """Réencode une activité en FIT (portable vers un autre outil)."""
    from ..ingest.fit_writer import FitWriter
    activity_id = request.params["activity_id"]
    activity = db.query_one("SELECT * FROM activities WHERE id = ?", (activity_id,))
    if not activity:
        raise not_found("Activité introuvable.")
    streams = db.load_streams(activity_id)
    if not streams:
        raise bad_request("Aucun flux à exporter pour cette activité.")
    start = datetime.fromisoformat(activity["start_time"].replace("Z", "+00:00"))
    writer = FitWriter()
    writer.write_file_id(start)
    writer.write_records(start, streams)
    sport_codes = {"running": 1, "cycling": 2, "swimming": 5, "walking": 11,
                   "hiking": 17, "rowing": 15, "training": 10}
    writer.write_session(
        start, activity["duration_s"], activity["distance_m"] or 0,
        sport=sport_codes.get(activity["sport"], 0),
        avg_hr=activity["avg_hr"] and int(activity["avg_hr"]),
        max_hr=activity["max_hr"] and int(activity["max_hr"]),
        avg_power=activity["avg_power_w"] and int(activity["avg_power_w"]),
        max_power=activity["max_power_w"] and int(activity["max_power_w"]),
        np=activity["np_w"] and int(activity["np_w"]),
        avg_speed=activity["avg_speed_ms"], max_speed=activity["max_speed_ms"],
        avg_cadence=activity["avg_cadence"] and int(activity["avg_cadence"]),
        calories=activity["calories"] and int(activity["calories"]),
        ascent=activity["elevation_gain_m"] and int(activity["elevation_gain_m"]),
        descent=activity["elevation_loss_m"] and int(activity["elevation_loss_m"]))
    blob = writer.build()
    filename = f"activite-{activity_id}.fit"
    return Response(blob, "application/vnd.ant.fit",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@ROUTER.get("/api/activities/<int:activity_id>/gpx")
def export_gpx(request):
    """Trace GPS au format GPX (extensions Garmin pour FC et cadence)."""
    activity_id = request.params["activity_id"]
    activity = db.query_one("SELECT * FROM activities WHERE id = ?", (activity_id,))
    if not activity:
        raise not_found("Activité introuvable.")
    streams = db.load_streams(activity_id, ["lat", "lon", "altitude",
                                            "heart_rate", "cadence"])
    if not streams.get("lat"):
        raise bad_request("Cette activité ne contient pas de trace GPS.")
    start = datetime.fromisoformat(activity["start_time"].replace("Z", "+00:00"))
    parts = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<gpx version="1.1" creator="Athlytics"'
             ' xmlns="http://www.topografix.com/GPX/1/1"'
             ' xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">',
             f'<trk><name>{_xml_escape(activity["name"] or "Activité")}</name>'
             f'<type>{activity["sport"]}</type><trkseg>']
    lat, lon = streams["lat"], streams["lon"]
    for i in range(len(lat)):
        if lat[i] is None or lon[i] is None:
            continue
        stamp = (start + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        parts.append(f'<trkpt lat="{lat[i]:.7f}" lon="{lon[i]:.7f}">')
        altitude = (streams.get("altitude") or [None] * len(lat))[i]
        if altitude is not None:
            parts.append(f"<ele>{altitude:.1f}</ele>")
        parts.append(f"<time>{stamp}</time>")
        hr = (streams.get("heart_rate") or [None] * len(lat))[i]
        cad = (streams.get("cadence") or [None] * len(lat))[i]
        if hr is not None or cad is not None:
            parts.append("<extensions><gpxtpx:TrackPointExtension>")
            if hr is not None:
                parts.append(f"<gpxtpx:hr>{int(hr)}</gpxtpx:hr>")
            if cad is not None:
                parts.append(f"<gpxtpx:cad>{int(cad)}</gpxtpx:cad>")
            parts.append("</gpxtpx:TrackPointExtension></extensions>")
        parts.append("</trkpt>")
    parts.append("</trkseg></trk></gpx>")
    body = "".join(parts).encode("utf-8")
    return Response(body, "application/gpx+xml",
                    headers={"Content-Disposition":
                             f'attachment; filename="activite-{activity_id}.gpx"'})


def _xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
