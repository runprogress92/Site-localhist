"""Endpoints Athlètes : fiche, profil physiologique, zones, synthèse."""
from __future__ import annotations

from datetime import date, timedelta

from .. import db, profiles
from ..ingest import pipeline
from ..science import hrv as HRV
from ..science import physiology as PH
from ..science import pmc as PMC
from ..science import power as PW
from ..science import readiness as RD
from ..science import running as RUN
from ..science import zones as Z
from ..server import ROUTER, bad_request, not_found

ATHLETE_FIELDS = (
    "first_name", "last_name", "sex", "birth_date", "height_cm", "weight_kg",
    "primary_sport", "discipline", "level", "team_id", "email", "phone",
    "country", "accent", "status", "joined_at", "notes",
)

PHYSIOLOGY_FIELDS = (
    "effective_date", "weight_kg", "body_fat_pct", "muscle_mass_kg", "hr_max",
    "hr_rest", "hr_lt1", "hr_lt2", "vo2max", "vvo2max", "ftp_w", "cp_w",
    "w_prime_j", "pmax_w", "threshold_pace_s_km", "critical_speed_ms",
    "d_prime_m", "vdot", "running_economy", "lactate_threshold_mmol",
    "max_hr_source", "source", "notes",
)


def _pick(payload: dict, fields) -> dict:
    return {k: payload[k] for k in fields if k in payload and payload[k] != ""}


def _today() -> str:
    return date.today().isoformat()


# --------------------------------------------------------------------- liste
@ROUTER.get("/api/athletes")
def list_athletes(request):
    """Roster avec l'état du jour de chaque athlète."""
    include_archived = request.q_bool("archived", False)
    sql = "SELECT a.*, t.name AS team_name, t.color AS team_color FROM athletes a" \
          " LEFT JOIN teams t ON t.id = a.team_id"
    if not include_archived:
        sql += " WHERE a.status != 'archived'"
    sql += " ORDER BY a.last_name, a.first_name"
    athletes = db.query(sql)
    today = _today()
    for athlete in athletes:
        athlete.update(athlete_state(athlete["id"], today))
    return {"athletes": athletes, "count": len(athletes)}


def athlete_state(athlete_id: int, on: str | None = None) -> dict:
    """État synthétique : forme, charge, disponibilité, alertes."""
    on = on or _today()
    load_row = db.query_one(
        "SELECT * FROM daily_load WHERE athlete_id = ? AND date <= ?"
        " ORDER BY date DESC LIMIT 1", (athlete_id, on))
    wellness_row = db.query_one(
        "SELECT * FROM wellness WHERE athlete_id = ? AND date <= ?"
        " ORDER BY date DESC LIMIT 1", (athlete_id, on))
    last_activity = db.query_one(
        "SELECT id, name, sport, local_date, duration_s, distance_m, load"
        " FROM activities WHERE athlete_id = ? ORDER BY start_time DESC LIMIT 1",
        (athlete_id,))
    alerts = db.query(
        "SELECT code, severity, title FROM alerts WHERE athlete_id = ?"
        " AND acknowledged = 0 ORDER BY CASE severity WHEN 'critical' THEN 0"
        " WHEN 'warning' THEN 1 ELSE 2 END LIMIT 5", (athlete_id,))
    week_start = (date.fromisoformat(on) - timedelta(days=date.fromisoformat(on).weekday()))
    week = db.query_one(
        "SELECT COALESCE(SUM(load),0) AS load, COALESCE(SUM(duration_s),0) AS duration_s,"
        " COALESCE(SUM(distance_m),0) AS distance_m, COUNT(*) AS sessions"
        " FROM activities WHERE athlete_id = ? AND local_date >= ?",
        (athlete_id, week_start.isoformat())) or {}

    tsb = load_row["tsb"] if load_row else None
    form, form_advice = PMC.form_state(tsb)
    return {
        "ctl": round(load_row["ctl"], 1) if load_row and load_row["ctl"] is not None else None,
        "atl": round(load_row["atl"], 1) if load_row and load_row["atl"] is not None else None,
        "tsb": round(tsb, 1) if tsb is not None else None,
        "form": form,
        "form_advice": form_advice,
        "acwr": load_row["acwr_ewma"] if load_row else None,
        "monotony": load_row["monotony"] if load_row else None,
        "ramp": load_row["ctl_ramp_7d"] if load_row else None,
        "readiness": wellness_row["readiness"] if wellness_row else None,
        "readiness_flag": wellness_row["readiness_flag"] if wellness_row else None,
        "hrv_rmssd": wellness_row["hrv_rmssd"] if wellness_row else None,
        "resting_hr": wellness_row["resting_hr"] if wellness_row else None,
        "sleep_total_min": wellness_row["sleep_total_min"] if wellness_row else None,
        "wellness_date": wellness_row["date"] if wellness_row else None,
        "last_activity": last_activity,
        "alerts": alerts,
        "alert_level": (alerts[0]["severity"] if alerts else "ok"),
        "week": week,
    }


# ------------------------------------------------------------------- fiche
@ROUTER.post("/api/athletes")
def create_athlete(request):
    payload = request.json
    data = _pick(payload, ATHLETE_FIELDS)
    if not data.get("first_name") or not data.get("last_name"):
        raise bad_request("Le prénom et le nom sont obligatoires.")
    data.setdefault("joined_at", _today())
    athlete_id = db.insert("athletes", data)

    physio = _pick(payload.get("physiology") or {}, PHYSIOLOGY_FIELDS)
    if not physio:
        age = profiles.age_at(data.get("birth_date")) or 32
        physio = profiles.default_physiology(data.get("sex", "M"), age)
    physio["athlete_id"] = athlete_id
    physio.setdefault("effective_date", _today())
    physio.setdefault("weight_kg", data.get("weight_kg"))
    physio.setdefault("source", "déclaratif")
    db.insert("physiology", physio)
    return {"id": athlete_id, "athlete": get_athlete_row(athlete_id)}, 201


def get_athlete_row(athlete_id: int) -> dict:
    row = db.query_one(
        "SELECT a.*, t.name AS team_name, t.color AS team_color FROM athletes a"
        " LEFT JOIN teams t ON t.id = a.team_id WHERE a.id = ?", (athlete_id,))
    if not row:
        raise not_found(f"Athlète {athlete_id} introuvable.")
    return row


@ROUTER.get("/api/athletes/<int:athlete_id>")
def get_athlete(request):
    athlete_id = request.params["athlete_id"]
    athlete = get_athlete_row(athlete_id)
    athlete["age"] = profiles.age_at(athlete.get("birth_date"))
    physio = profiles.physiology_at(athlete_id)
    ctx = profiles.athlete_context(athlete_id)
    athlete["physiology"] = physio
    athlete["physiology_history"] = db.query(
        "SELECT * FROM physiology WHERE athlete_id = ? ORDER BY effective_date DESC",
        (athlete_id,))
    athlete["zones"] = ctx["zones"]
    athlete["state"] = athlete_state(athlete_id)
    athlete["devices"] = db.query(
        "SELECT pa.provider, pa.status, pa.last_sync_at, pa.last_error,"
        " pa.provider_user_id FROM provider_accounts pa WHERE pa.athlete_id = ?",
        (athlete_id,))
    athlete["totals"] = db.query_one(
        "SELECT COUNT(*) AS sessions, COALESCE(SUM(duration_s),0) AS duration_s,"
        " COALESCE(SUM(distance_m),0) AS distance_m,"
        " COALESCE(SUM(elevation_gain_m),0) AS elevation_m,"
        " COALESCE(SUM(load),0) AS load, MIN(local_date) AS first_date"
        " FROM activities WHERE athlete_id = ?", (athlete_id,))
    if physio.get("vo2max") and athlete.get("age"):
        athlete["vo2max_rating"] = PH.vo2max_percentile(
            physio["vo2max"], athlete["age"], athlete.get("sex", "M"))
    if physio.get("vdot"):
        athlete["daniels_paces"] = RUN.daniels_paces(physio["vdot"])
    return athlete


@ROUTER.patch("/api/athletes/<int:athlete_id>")
def update_athlete(request):
    athlete_id = request.params["athlete_id"]
    get_athlete_row(athlete_id)
    data = _pick(request.json, ATHLETE_FIELDS)
    if not data:
        raise bad_request("Aucun champ modifiable fourni.")
    data["updated_at"] = db.now_iso()
    db.update("athletes", athlete_id, data)
    return {"athlete": get_athlete_row(athlete_id)}


@ROUTER.delete("/api/athletes/<int:athlete_id>")
def delete_athlete(request):
    athlete_id = request.params["athlete_id"]
    get_athlete_row(athlete_id)
    if request.q_bool("hard"):
        db.delete("athletes", athlete_id)
        return {"deleted": athlete_id}
    db.update("athletes", athlete_id, {"status": "archived", "updated_at": db.now_iso()})
    return {"archived": athlete_id}


# ------------------------------------------------------- profil physiologique
@ROUTER.post("/api/athletes/<int:athlete_id>/physiology")
def add_physiology(request):
    athlete_id = request.params["athlete_id"]
    get_athlete_row(athlete_id)
    data = _pick(request.json, PHYSIOLOGY_FIELDS)
    if not data:
        raise bad_request("Aucune valeur physiologique fournie.")
    data["athlete_id"] = athlete_id
    data.setdefault("effective_date", _today())
    # cohérence : vitesse critique ↔ allure seuil
    if data.get("threshold_pace_s_km") and not data.get("critical_speed_ms"):
        data["critical_speed_ms"] = round(1000 / float(data["threshold_pace_s_km"]), 4)
    if data.get("critical_speed_ms") and not data.get("threshold_pace_s_km"):
        data["threshold_pace_s_km"] = round(1000 / float(data["critical_speed_ms"]), 1)
    row_id = db.insert("physiology", data)
    if data.get("weight_kg"):
        db.update("athletes", athlete_id, {"weight_kg": data["weight_kg"]})

    recomputed = 0
    if request.json.get("reanalyze"):
        activities = db.query(
            "SELECT id FROM activities WHERE athlete_id = ? AND local_date >= ?"
            " AND has_streams = 1", (athlete_id, data["effective_date"]))
        for activity in activities:
            try:
                pipeline.reanalyze_activity(activity["id"])
                recomputed += 1
            except Exception:
                pass
        pipeline.rebuild_daily(athlete_id)
    return {"id": row_id, "physiology": profiles.physiology_at(athlete_id),
            "reanalyzed": recomputed}, 201


@ROUTER.get("/api/athletes/<int:athlete_id>/zones")
def get_zones(request):
    athlete_id = request.params["athlete_id"]
    on = request.q("date")
    ctx = profiles.athlete_context(athlete_id, on)
    return {
        "zones": ctx["zones"],
        "basis": {
            "lthr": ctx["lthr"], "hr_max": ctx["hr_max"], "hr_rest": ctx["hr_rest"],
            "ftp_w": ctx["ftp_w"], "threshold_pace_s_km": ctx["threshold_pace_s_km"],
            "threshold_speed_ms": ctx["threshold_speed_ms"],
        },
        "models": {
            "hr": ["friel_lthr", "hrmax", "karvonen", "seiler3"],
            "power": ["coggan"], "pace": ["daniels_like"],
        },
    }


@ROUTER.get("/api/athletes/<int:athlete_id>/zones/<kind>")
def get_zones_model(request):
    athlete_id = request.params["athlete_id"]
    kind = request.params["kind"]
    model = request.q("model", "friel_lthr")
    ctx = profiles.athlete_context(athlete_id, request.q("date"))
    if kind == "hr":
        zones = Z.hr_zones(model, lthr=ctx["lthr"], hr_max=ctx["hr_max"],
                           hr_rest=ctx["hr_rest"])
    elif kind == "power":
        zones = Z.power_zones(ctx["ftp_w"] or 0)
    elif kind == "pace":
        zones = Z.pace_zones(ctx["threshold_speed_ms"] or 0)
    else:
        raise bad_request("Type de zones inconnu (hr, power ou pace).")
    return {"kind": kind, "model": model, "zones": zones}


# ------------------------------------------------------------------ synthèse
@ROUTER.get("/api/athletes/<int:athlete_id>/summary")
def athlete_summary(request):
    """Charge utile complète du tableau de bord d'un athlète."""
    athlete_id = request.params["athlete_id"]
    days = request.q_int("days", 120)
    athlete = get_athlete_row(athlete_id)
    end = date.today()
    start = end - timedelta(days=days)

    pmc_rows = db.query(
        "SELECT * FROM daily_load WHERE athlete_id = ? AND date >= ? ORDER BY date",
        (athlete_id, start.isoformat()))
    wellness = db.query(
        "SELECT * FROM wellness WHERE athlete_id = ? AND date >= ? ORDER BY date",
        (athlete_id, start.isoformat()))
    activities = db.query(
        "SELECT id, name, sport, sub_sport, local_date, start_time, duration_s,"
        " distance_m, elevation_gain_m, avg_hr, max_hr, avg_power_w, np_w, load,"
        " load_source, intensity_factor, tss, rtss, hrtss, decoupling_pct,"
        " efficiency_factor, rpe, avg_speed_ms, gap_pace_s_km, has_gps, calories"
        " FROM activities WHERE athlete_id = ? AND local_date >= ?"
        " ORDER BY start_time DESC", (athlete_id, start.isoformat()))

    # répartition par zone sur la période
    zone_rows = db.query(
        "SELECT azt.kind, azt.zone_idx, SUM(azt.seconds) AS seconds"
        " FROM activity_zone_time azt JOIN activities a ON a.id = azt.activity_id"
        " WHERE a.athlete_id = ? AND a.local_date >= ?"
        " GROUP BY azt.kind, azt.zone_idx ORDER BY azt.kind, azt.zone_idx",
        (athlete_id, start.isoformat()))
    zone_summary: dict[str, list] = {}
    for row in zone_rows:
        zone_summary.setdefault(row["kind"], []).append(
            {"zone": row["zone_idx"], "seconds": round(row["seconds"], 0)})

    # répartition par sport
    sports = db.query(
        "SELECT sport, COUNT(*) AS sessions, SUM(duration_s) AS duration_s,"
        " SUM(distance_m) AS distance_m, SUM(load) AS load"
        " FROM activities WHERE athlete_id = ? AND local_date >= ?"
        " GROUP BY sport ORDER BY duration_s DESC", (athlete_id, start.isoformat()))

    ln_series = [w.get("hrv_ln_rmssd") for w in wellness]
    baseline = HRV.rolling_baseline(ln_series, 7)
    low, mean, high = HRV.normal_range(ln_series)
    cv = HRV.coefficient_of_variation(ln_series)
    hrv_state = HRV.hrv_status(baseline[-1] if baseline else None, low, high, cv)

    alerts = db.query(
        "SELECT * FROM alerts WHERE athlete_id = ? AND acknowledged = 0"
        " ORDER BY date DESC, CASE severity WHEN 'critical' THEN 0"
        " WHEN 'warning' THEN 1 ELSE 2 END", (athlete_id,))

    upcoming = db.query(
        "SELECT * FROM planned_workouts WHERE athlete_id = ? AND date >= ?"
        " AND status = 'planned' ORDER BY date LIMIT 10", (athlete_id, end.isoformat()))
    events = db.query(
        "SELECT * FROM events WHERE athlete_id = ? AND date >= ? ORDER BY date LIMIT 5",
        (athlete_id, end.isoformat()))
    for event in events:
        event["days_out"] = (date.fromisoformat(event["date"]) - end).days

    return {
        "athlete": athlete,
        "state": athlete_state(athlete_id),
        "pmc": pmc_rows,
        "wellness": wellness,
        "hrv": {
            "baseline": [{"date": w["date"], "value": b}
                         for w, b in zip(wellness, baseline)],
            "normal_low": low, "normal_mean": mean, "normal_high": high,
            "cv": cv, "status": hrv_state,
        },
        "activities": activities,
        "zone_summary": zone_summary,
        "zones": profiles.athlete_context(athlete_id)["zones"],
        "sports": sports,
        "alerts": alerts,
        "upcoming": upcoming,
        "events": events,
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
    }


# --------------------------------------------------------- courbe de puissance
@ROUTER.get("/api/athletes/<int:athlete_id>/power-curve")
def power_curve(request):
    """Courbe record (MMP) sur une ou plusieurs périodes, plus modèle CP/W'."""
    athlete_id = request.params["athlete_id"]
    kind = request.q("kind", "power")
    sport = request.q("sport")
    windows = {
        "42j": 42, "90j": 90, "1 an": 365,
        "Historique": 100000,
    }
    custom = request.q_int("days")
    if custom:
        windows = {f"{custom}j": custom}
    today = date.today()

    curves = {}
    for label, days in windows.items():
        since = (today - timedelta(days=days)).isoformat()
        sql = ("SELECT duration_s, MAX(value) AS value, MAX(value_per_kg) AS value_per_kg"
               " FROM best_efforts WHERE athlete_id = ? AND kind = ? AND local_date >= ?")
        params = [athlete_id, kind, since]
        if sport:
            sql += " AND sport = ?"
            params.append(sport)
        sql += " GROUP BY duration_s ORDER BY duration_s"
        rows = db.query(sql, params)
        if rows:
            curves[label] = rows

    reference = curves.get("90j") or curves.get("Historique") or {}
    model = None
    if kind == "power" and reference:
        model = PW.critical_power([(r["duration_s"], r["value"]) for r in reference])
    elif kind == "speed" and reference:
        efforts = [(r["duration_s"], r["value"] * r["duration_s"]) for r in reference]
        model = RUN.critical_speed(efforts)

    ctx = profiles.athlete_context(athlete_id)
    profile_labels = {}
    if kind == "power" and ctx.get("weight_kg") and reference:
        by_duration = {r["duration_s"]: r["value"] for r in reference}
        for duration in (5, 60, 300, 1200):
            if duration in by_duration:
                w_kg = by_duration[duration] / ctx["weight_kg"]
                profile_labels[duration] = {
                    "w_per_kg": round(w_kg, 2),
                    "rating": PW.power_profile(w_kg, duration, ctx["sex"]),
                }
        phenotype = PW.phenotype(by_duration, ctx["weight_kg"], ctx["sex"])
    else:
        phenotype = None

    return {"kind": kind, "curves": curves, "model": model,
            "profile": profile_labels, "phenotype": phenotype,
            "weight_kg": ctx.get("weight_kg")}


@ROUTER.get("/api/athletes/<int:athlete_id>/records")
def personal_records(request):
    """Meilleures performances, avec la séance et la date où elles ont été réalisées."""
    athlete_id = request.params["athlete_id"]
    kind = request.q("kind", "power")
    rows = db.query(
        "SELECT be.duration_s, be.value, be.value_per_kg, be.local_date, be.sport,"
        " a.id AS activity_id, a.name AS activity_name FROM best_efforts be"
        " JOIN activities a ON a.id = be.activity_id"
        " WHERE be.athlete_id = ? AND be.kind = ?"
        " AND be.value = (SELECT MAX(b2.value) FROM best_efforts b2"
        "   WHERE b2.athlete_id = be.athlete_id AND b2.kind = be.kind"
        "   AND b2.duration_s = be.duration_s)"
        " GROUP BY be.duration_s ORDER BY be.duration_s", (athlete_id, kind))
    for row in rows:
        if kind == "speed":
            row["pace_s_km"] = RUN.speed_to_pace(row["value"])
            row["distance_m"] = round(row["value"] * row["duration_s"])
    return {"kind": kind, "records": rows}


@ROUTER.get("/api/athletes/<int:athlete_id>/progression")
def progression(request):
    """Évolution mensuelle des indicateurs clés (volume, charge, efficacité)."""
    athlete_id = request.params["athlete_id"]
    months = request.q_int("months", 18)
    since = (date.today() - timedelta(days=months * 31)).isoformat()
    rows = db.query(
        "SELECT substr(local_date,1,7) AS month, COUNT(*) AS sessions,"
        " SUM(duration_s) AS duration_s, SUM(distance_m) AS distance_m,"
        " SUM(elevation_gain_m) AS elevation_m, SUM(load) AS load,"
        " AVG(efficiency_factor) AS efficiency_factor, AVG(avg_hr) AS avg_hr,"
        " AVG(decoupling_pct) AS decoupling_pct"
        " FROM activities WHERE athlete_id = ? AND local_date >= ?"
        " GROUP BY month ORDER BY month", (athlete_id, since))
    physio = db.query(
        "SELECT effective_date, vo2max, ftp_w, weight_kg, threshold_pace_s_km, vdot"
        " FROM physiology WHERE athlete_id = ? AND effective_date >= ?"
        " ORDER BY effective_date", (athlete_id, since))
    ctl = db.query(
        "SELECT date, ctl, atl, tsb FROM daily_load WHERE athlete_id = ? AND date >= ?"
        " ORDER BY date", (athlete_id, since))
    return {"months": rows, "physiology": physio, "ctl": ctl}


# ----------------------------------------------------------- notes, blessures
@ROUTER.get("/api/athletes/<int:athlete_id>/notes")
def list_notes(request):
    athlete_id = request.params["athlete_id"]
    return {"notes": db.query(
        "SELECT * FROM coach_notes WHERE athlete_id = ?"
        " ORDER BY pinned DESC, date DESC LIMIT 200", (athlete_id,))}


@ROUTER.post("/api/athletes/<int:athlete_id>/notes")
def add_note(request):
    athlete_id = request.params["athlete_id"]
    payload = request.json
    if not payload.get("text"):
        raise bad_request("Le texte de la note est obligatoire.")
    note_id = db.insert("coach_notes", {
        "athlete_id": athlete_id, "date": payload.get("date") or _today(),
        "author": payload.get("author") or "coach",
        "category": payload.get("category"), "text": payload["text"],
        "pinned": 1 if payload.get("pinned") else 0})
    return {"id": note_id}, 201


@ROUTER.delete("/api/notes/<int:note_id>")
def delete_note(request):
    db.delete("coach_notes", request.params["note_id"])
    return {"deleted": request.params["note_id"]}


@ROUTER.get("/api/athletes/<int:athlete_id>/injuries")
def list_injuries(request):
    athlete_id = request.params["athlete_id"]
    return {"injuries": db.query(
        "SELECT * FROM injuries WHERE athlete_id = ? ORDER BY date DESC", (athlete_id,))}


@ROUTER.post("/api/athletes/<int:athlete_id>/injuries")
def add_injury(request):
    athlete_id = request.params["athlete_id"]
    payload = request.json
    fields = ("date", "body_part", "side", "type", "mechanism", "severity",
              "status", "days_lost", "return_date", "diagnosis", "treatment", "notes")
    data = _pick(payload, fields)
    if not data.get("body_part"):
        raise bad_request("La zone corporelle est obligatoire.")
    data["athlete_id"] = athlete_id
    data.setdefault("date", _today())
    injury_id = db.insert("injuries", data)
    if data.get("status") != "résolue":
        db.update("athletes", athlete_id, {"status": "injured"})
    pipeline.refresh_alerts(athlete_id)
    return {"id": injury_id}, 201


@ROUTER.patch("/api/injuries/<int:injury_id>")
def update_injury(request):
    injury_id = request.params["injury_id"]
    injury = db.query_one("SELECT * FROM injuries WHERE id = ?", (injury_id,))
    if not injury:
        raise not_found("Blessure introuvable.")
    fields = ("body_part", "side", "type", "mechanism", "severity", "status",
              "days_lost", "return_date", "diagnosis", "treatment", "notes")
    db.update("injuries", injury_id, _pick(request.json, fields))
    remaining = db.scalar(
        "SELECT COUNT(*) FROM injuries WHERE athlete_id = ? AND status != 'résolue'",
        (injury["athlete_id"],), 0)
    if not remaining:
        athlete = db.query_one("SELECT status FROM athletes WHERE id = ?",
                               (injury["athlete_id"],))
        if athlete and athlete["status"] == "injured":
            db.update("athletes", injury["athlete_id"], {"status": "active"})
    pipeline.refresh_alerts(injury["athlete_id"])
    return {"updated": injury_id}


@ROUTER.post("/api/alerts/<int:alert_id>/acknowledge")
def acknowledge_alert(request):
    db.update("alerts", request.params["alert_id"], {"acknowledged": 1})
    return {"acknowledged": request.params["alert_id"]}
