"""Endpoints Analyse : PMC, charge, calendrier, comparaison, vue équipe."""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from .. import db, profiles
from ..science import pmc as PMC
from ..science import zones as Z
from ..server import ROUTER, bad_request


@ROUTER.get("/api/athletes/<int:athlete_id>/pmc")
def pmc_series(request):
    """Série CTL/ATL/TSB + ACWR, avec projection optionnelle des séances planifiées."""
    athlete_id = request.params["athlete_id"]
    days = request.q_int("days", 180)
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = db.query(
        "SELECT * FROM daily_load WHERE athlete_id = ? AND date >= ? ORDER BY date",
        (athlete_id, since))
    if not rows:
        return {"pmc": [], "projection": [], "current": None}

    current = rows[-1]
    projection = []
    horizon = request.q_int("project", 21)
    if horizon > 0:
        today = date.today()
        planned = {p["date"]: p["target_load"] or 0 for p in db.query(
            "SELECT date, target_load FROM planned_workouts WHERE athlete_id = ?"
            " AND date > ? AND status = 'planned'", (athlete_id, today.isoformat()))}
        loads = [planned.get((today + timedelta(days=i + 1)).isoformat(), 0.0)
                 for i in range(horizon)]
        forecast = PMC.project_forward(current["ctl"] or 0, current["atl"] or 0, loads)
        for i, point in enumerate(forecast):
            point["date"] = (today + timedelta(days=i + 1)).isoformat()
            point["planned"] = loads[i] > 0
        projection = forecast

    form, advice = PMC.form_state(current["tsb"])
    acwr_state, acwr_advice = PMC.interpret_acwr(
        current.get("acwr_ewma") or current.get("acwr_rolling"))
    return {
        "pmc": rows,
        "projection": projection,
        "current": {**current, "form": form, "form_advice": advice,
                    "acwr_state": acwr_state, "acwr_advice": acwr_advice},
        "thresholds": {"acwr_sweet_spot": list(PMC.ACWR_SWEET_SPOT),
                       "acwr_danger": PMC.ACWR_DANGER,
                       "monotony_warn": PMC.MONOTONY_WARN,
                       "ramp_warn": PMC.RAMP_WARN},
    }


@ROUTER.get("/api/athletes/<int:athlete_id>/load")
def load_breakdown(request):
    """Charge agrégée par semaine ou par mois, ventilée par sport."""
    athlete_id = request.params["athlete_id"]
    group = request.q("group", "week")
    weeks = request.q_int("periods", 26)
    if group == "month":
        since = (date.today() - timedelta(days=weeks * 31)).isoformat()
        expression = "substr(local_date, 1, 7)"
    else:
        since = (date.today() - timedelta(weeks=weeks)).isoformat()
        # semaine ISO : le lundi comme premier jour
        expression = "date(local_date, 'weekday 0', '-6 days')"
    rows = db.query(
        f"SELECT {expression} AS period, sport, COUNT(*) AS sessions,"
        " COALESCE(SUM(duration_s),0) AS duration_s,"
        " COALESCE(SUM(distance_m),0) AS distance_m,"
        " COALESCE(SUM(elevation_gain_m),0) AS elevation_m,"
        " COALESCE(SUM(load),0) AS load"
        " FROM activities WHERE athlete_id = ? AND local_date >= ?"
        " GROUP BY period, sport ORDER BY period", (athlete_id, since))

    periods: dict[str, dict] = {}
    for row in rows:
        bucket = periods.setdefault(row["period"], {
            "period": row["period"], "load": 0.0, "duration_s": 0.0,
            "distance_m": 0.0, "elevation_m": 0.0, "sessions": 0, "by_sport": {}})
        bucket["load"] += row["load"]
        bucket["duration_s"] += row["duration_s"]
        bucket["distance_m"] += row["distance_m"]
        bucket["elevation_m"] += row["elevation_m"]
        bucket["sessions"] += row["sessions"]
        bucket["by_sport"][row["sport"]] = round(row["load"], 1)

    series = sorted(periods.values(), key=lambda p: p["period"])
    loads = [p["load"] for p in series]
    for i, point in enumerate(series):
        previous = loads[i - 1] if i > 0 else None
        point["load"] = round(point["load"], 1)
        point["delta_pct"] = (round(100 * (point["load"] - previous) / previous, 1)
                              if previous and previous > 0 else None)
    return {"group": group, "periods": series,
            "mean_load": round(statistics.fmean(loads), 1) if loads else 0}


@ROUTER.get("/api/athletes/<int:athlete_id>/calendar")
def calendar(request):
    """Calendrier fusionné : séances réalisées, planifiées, bien-être, objectifs."""
    athlete_id = request.params["athlete_id"]
    start = request.q("from") or (date.today() - timedelta(days=35)).isoformat()
    end = request.q("to") or (date.today() + timedelta(days=21)).isoformat()

    activities = db.query(
        "SELECT id, name, sport, local_date AS date, start_time, duration_s,"
        " distance_m, load, load_source, avg_hr, np_w, intensity_factor, rpe,"
        " elevation_gain_m FROM activities WHERE athlete_id = ?"
        " AND local_date BETWEEN ? AND ? ORDER BY start_time",
        (athlete_id, start, end))
    planned = db.query(
        "SELECT * FROM planned_workouts WHERE athlete_id = ? AND date BETWEEN ? AND ?"
        " ORDER BY date", (athlete_id, start, end))
    wellness = db.query(
        "SELECT date, readiness, readiness_flag, hrv_rmssd, resting_hr,"
        " sleep_total_min, fatigue, soreness FROM wellness"
        " WHERE athlete_id = ? AND date BETWEEN ? AND ?", (athlete_id, start, end))
    loads = db.query(
        "SELECT date, load, ctl, atl, tsb, acwr_ewma FROM daily_load"
        " WHERE athlete_id = ? AND date BETWEEN ? AND ?", (athlete_id, start, end))
    events = db.query(
        "SELECT * FROM events WHERE athlete_id = ? AND date BETWEEN ? AND ?",
        (athlete_id, start, end))
    blocks = db.query(
        "SELECT * FROM training_blocks WHERE athlete_id = ?"
        " AND NOT (end_date < ? OR start_date > ?)", (athlete_id, start, end))

    days: dict[str, dict] = {}
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while cursor <= stop:
        key = cursor.isoformat()
        days[key] = {"date": key, "activities": [], "planned": [], "events": [],
                     "wellness": None, "load": None,
                     "weekday": cursor.weekday(), "is_today": key == date.today().isoformat()}
        cursor += timedelta(days=1)
    for activity in activities:
        days.setdefault(activity["date"], {"date": activity["date"], "activities": [],
                                           "planned": [], "events": []})["activities"].append(activity)
    for item in planned:
        if item["date"] in days:
            days[item["date"]]["planned"].append(item)
    for item in events:
        if item["date"] in days:
            days[item["date"]]["events"].append(item)
    for item in wellness:
        if item["date"] in days:
            days[item["date"]]["wellness"] = item
    for item in loads:
        if item["date"] in days:
            days[item["date"]]["load"] = item
    return {"start": start, "end": end, "days": list(days.values()),
            "blocks": blocks}


@ROUTER.get("/api/athletes/<int:athlete_id>/zone-distribution")
def zone_distribution(request):
    """Répartition du temps par zone, et test de polarisation."""
    athlete_id = request.params["athlete_id"]
    days = request.q_int("days", 90)
    since = (date.today() - timedelta(days=days)).isoformat()
    kind = request.q("kind", "hr")
    rows = db.query(
        "SELECT azt.zone_idx, SUM(azt.seconds) AS seconds FROM activity_zone_time azt"
        " JOIN activities a ON a.id = azt.activity_id WHERE a.athlete_id = ?"
        " AND a.local_date >= ? AND azt.kind = ? GROUP BY azt.zone_idx"
        " ORDER BY azt.zone_idx", (athlete_id, since, kind))
    ctx = profiles.athlete_context(athlete_id)
    zones = ctx["zones"].get(kind) or []
    total = sum(r["seconds"] for r in rows) or 1
    distribution = []
    for zone in zones:
        seconds = next((r["seconds"] for r in rows if r["zone_idx"] == zone["idx"]), 0)
        distribution.append({**zone, "seconds": round(seconds),
                             "pct": round(100 * seconds / total, 1)})

    # test de polarisation sur 3 zones (LT1 / LT2)
    three = db.query(
        "SELECT azt.zone_idx, SUM(azt.seconds) AS seconds FROM activity_zone_time azt"
        " JOIN activities a ON a.id = azt.activity_id WHERE a.athlete_id = ?"
        " AND a.local_date >= ? AND azt.kind = 'hr' GROUP BY azt.zone_idx", (athlete_id, since))
    # Z1-Z3 = sous LT1, Z4 = zone grise, Z5+ = au-dessus de LT2 (modèle Friel 7 zones)
    buckets = [0.0, 0.0, 0.0]
    for row in three:
        idx = row["zone_idx"]
        target = 0 if idx <= 3 else (1 if idx == 4 else 2)
        buckets[target] += row["seconds"]
    pi = Z.polarization_index(*buckets)
    total3 = sum(buckets) or 1
    return {
        "kind": kind, "days": days, "total_seconds": round(total),
        "distribution": distribution,
        "three_zone": {
            "low": round(100 * buckets[0] / total3, 1),
            "threshold": round(100 * buckets[1] / total3, 1),
            "high": round(100 * buckets[2] / total3, 1),
            "seconds": [round(b) for b in buckets],
        },
        "polarization_index": pi,
        "verdict": _polarization_verdict(pi, buckets, total3),
    }


def _polarization_verdict(pi, buckets, total) -> str:
    # Verdict rédigé en français : la virgule sépare les décimales.
    index = f"{pi:.2f}".replace(".", ",") if pi is not None else "—"
    low = 100 * buckets[0] / total
    high = 100 * buckets[2] / total
    if pi is None:
        return "Historique insuffisant pour qualifier la distribution."
    if pi > 2.0 and low > 70:
        return (f"Distribution polarisée (indice {index} > 2,00) : {low:.0f} % du "
                f"temps en aisance et {high:.0f} % en haute intensité. C'est le "
                "profil le mieux documenté chez les athlètes d'endurance de haut niveau.")
    if low > 80 and high < 5:
        return (f"Distribution pyramidale à dominante basse : {low:.0f} % en zone 1-3. "
                "Excellente base aérobie, mais peu de stimulus de haute intensité — "
                "à corriger si une échéance approche.")
    if buckets[1] / total > 0.30:
        return (f"Distribution « seuil » : {100 * buckets[1] / total:.0f} % du temps "
                "dans la zone intermédiaire. C'est la zone la plus coûteuse en "
                "récupération pour un rendement adaptatif modéré — à surveiller.")
    return (f"Distribution pyramidale (indice {index}) : volume majoritairement "
            "facile avec une pointe d'intensité, profil classique de préparation.")


# ------------------------------------------------------------------- équipe
@ROUTER.get("/api/team/overview")
def team_overview(request):
    """Vue d'ensemble du groupe : état de chaque athlète et agrégats."""
    from .athletes import athlete_state
    today = date.today().isoformat()
    athletes = db.query(
        "SELECT a.*, t.name AS team_name FROM athletes a"
        " LEFT JOIN teams t ON t.id = a.team_id"
        " WHERE a.status != 'archived' ORDER BY a.last_name")
    rows = []
    for athlete in athletes:
        state = athlete_state(athlete["id"], today)
        rows.append({**athlete, **state})

    def collect(key):
        return [r[key] for r in rows if r.get(key) is not None]

    ctl_values = collect("ctl")
    readiness_values = collect("readiness")
    alerts = db.query(
        "SELECT al.*, a.first_name, a.last_name, a.accent FROM alerts al"
        " JOIN athletes a ON a.id = al.athlete_id WHERE al.acknowledged = 0"
        " ORDER BY CASE al.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1"
        " ELSE 2 END, al.date DESC LIMIT 40")

    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    week = db.query_one(
        "SELECT COUNT(*) AS sessions, COALESCE(SUM(duration_s),0) AS duration_s,"
        " COALESCE(SUM(distance_m),0) AS distance_m, COALESCE(SUM(load),0) AS load"
        " FROM activities WHERE local_date >= ?", (week_start,))
    recent = db.query(
        "SELECT a.id, a.name, a.sport, a.local_date, a.start_time, a.duration_s,"
        " a.distance_m, a.load, ath.first_name, ath.last_name, ath.accent,"
        " ath.id AS athlete_id FROM activities a"
        " JOIN athletes ath ON ath.id = a.athlete_id"
        " ORDER BY a.start_time DESC LIMIT 15")
    upcoming_events = db.query(
        "SELECT e.*, a.first_name, a.last_name, a.accent FROM events e"
        " JOIN athletes a ON a.id = e.athlete_id WHERE e.date >= ?"
        " ORDER BY e.date LIMIT 10", (today,))
    for event in upcoming_events:
        event["days_out"] = (date.fromisoformat(event["date"]) - date.today()).days

    return {
        "athletes": rows,
        "totals": {
            "athletes": len(rows),
            "active": sum(1 for r in rows if r["status"] == "active"),
            "injured": sum(1 for r in rows if r["status"] == "injured"),
            "mean_ctl": round(statistics.fmean(ctl_values), 1) if ctl_values else None,
            "mean_readiness": round(statistics.fmean(readiness_values), 1)
            if readiness_values else None,
            "flags": {
                "vert": sum(1 for r in rows if r.get("readiness_flag") == "vert"),
                "ambre": sum(1 for r in rows if r.get("readiness_flag") == "ambre"),
                "rouge": sum(1 for r in rows if r.get("readiness_flag") == "rouge"),
            },
        },
        "week": week,
        "alerts": alerts,
        "recent": recent,
        "events": upcoming_events,
    }


@ROUTER.get("/api/team/matrix")
def team_matrix(request):
    """Matrice charge × jour pour l'ensemble du groupe (carte de chaleur)."""
    days = request.q_int("days", 42)
    since = (date.today() - timedelta(days=days)).isoformat()
    athletes = db.query(
        "SELECT id, first_name, last_name, accent FROM athletes"
        " WHERE status != 'archived' ORDER BY last_name")
    rows = db.query(
        "SELECT athlete_id, date, load, ctl, atl, tsb, acwr_ewma FROM daily_load"
        " WHERE date >= ? ORDER BY date", (since,))
    by_athlete: dict[int, dict] = {a["id"]: {} for a in athletes}
    for row in rows:
        if row["athlete_id"] in by_athlete:
            by_athlete[row["athlete_id"]][row["date"]] = row
    dates = [(date.today() - timedelta(days=days - 1 - i)).isoformat()
             for i in range(days)]
    matrix = []
    for athlete in athletes:
        cells = [by_athlete[athlete["id"]].get(d) for d in dates]
        matrix.append({
            "athlete": athlete,
            "cells": [{"date": d, "load": (c or {}).get("load", 0),
                       "tsb": (c or {}).get("tsb")} for d, c in zip(dates, cells)],
            "total": round(sum((c or {}).get("load", 0) or 0 for c in cells), 1),
        })
    return {"dates": dates, "matrix": matrix}


@ROUTER.get("/api/compare")
def compare(request):
    """Compare une métrique entre plusieurs athlètes sur une période."""
    ids_param = request.q("athletes", "")
    try:
        athlete_ids = [int(x) for x in ids_param.split(",") if x.strip()]
    except ValueError:
        raise bad_request("Paramètre « athletes » : liste d'identifiants séparés par des virgules.")
    if not athlete_ids:
        raise bad_request("Aucun athlète à comparer.")
    metric = request.q("metric", "ctl")
    allowed = {"ctl", "atl", "tsb", "load", "acwr_ewma", "monotony", "strain"}
    days = request.q_int("days", 120)
    since = (date.today() - timedelta(days=days)).isoformat()

    series = []
    for athlete_id in athlete_ids:
        athlete = db.query_one(
            "SELECT id, first_name, last_name, accent FROM athletes WHERE id = ?",
            (athlete_id,))
        if not athlete:
            continue
        if metric in allowed:
            points = db.query(
                f"SELECT date, {metric} AS value FROM daily_load"
                " WHERE athlete_id = ? AND date >= ? ORDER BY date",
                (athlete_id, since))
        elif metric in ("readiness", "hrv_ln_rmssd", "resting_hr", "sleep_total_min"):
            points = db.query(
                f"SELECT date, {metric} AS value FROM wellness"
                " WHERE athlete_id = ? AND date >= ? ORDER BY date",
                (athlete_id, since))
        else:
            raise bad_request(f"Métrique « {metric} » non comparable.")
        values = [p["value"] for p in points if p["value"] is not None]
        series.append({
            "athlete": athlete, "points": points,
            "stats": {
                "mean": round(statistics.fmean(values), 2) if values else None,
                "max": round(max(values), 2) if values else None,
                "min": round(min(values), 2) if values else None,
                "last": values[-1] if values else None,
            },
        })
    return {"metric": metric, "days": days, "series": series}


@ROUTER.get("/api/search")
def global_search(request):
    """Recherche transverse : athlètes, séances, objectifs."""
    needle = (request.q("q") or "").strip()
    if len(needle) < 2:
        return {"results": []}
    like = f"%{needle}%"
    results = []
    for row in db.query(
            "SELECT id, first_name, last_name, primary_sport FROM athletes"
            " WHERE (first_name || ' ' || last_name) LIKE ? AND status != 'archived'"
            " LIMIT 8", (like,)):
        results.append({"type": "athlete", "id": row["id"],
                        "title": f"{row['first_name']} {row['last_name']}",
                        "subtitle": row["primary_sport"]})
    for row in db.query(
            "SELECT a.id, a.name, a.local_date, ath.first_name, ath.last_name"
            " FROM activities a JOIN athletes ath ON ath.id = a.athlete_id"
            " WHERE a.name LIKE ? OR a.notes LIKE ? ORDER BY a.start_time DESC LIMIT 10",
            (like, like)):
        results.append({"type": "activity", "id": row["id"], "title": row["name"],
                        "subtitle": f"{row['first_name']} {row['last_name']} — {row['local_date']}"})
    for row in db.query(
            "SELECT e.id, e.name, e.date, e.athlete_id FROM events e"
            " WHERE e.name LIKE ? ORDER BY e.date DESC LIMIT 5", (like,)):
        results.append({"type": "event", "id": row["id"], "title": row["name"],
                        "subtitle": row["date"], "athlete_id": row["athlete_id"]})
    return {"results": results, "query": needle}
