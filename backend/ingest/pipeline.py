"""Pipeline d'analyse : du fichier brut à la séance entièrement qualifiée.

Étapes
------
1. **Lecture** — FIT, TCX ou GPX, détectés par signature puis par extension.
2. **Normalisation** — séries à 1 Hz, unités SI, nettoyage des aberrations.
3. **Analyse** — toutes les métriques dérivées : NP, IF, TSS, TRIMP,
   découplage, GAP/NGP, temps en zones, courbe record, W'bal.
4. **Persistance** — activité, flux compressés, tours, temps en zones,
   meilleures performances.
5. **Reconstruction** — agrégats quotidiens et PMC pour l'athlète.

Chaque étape est indépendante : réanalyser une séance après une mise à jour
de FTP ne nécessite pas de relire le fichier source.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import db, profiles
from ..science import load as L
from ..science import physiology as PH
from ..science import pmc as PMC
from ..science import power as PW
from ..science import risk as RISK
from ..science import running as RUN
from ..science import zones as Z
from . import fit as FIT
from . import xmlformats as XML

MMP_KEY_DURATIONS = [5, 10, 30, 60, 120, 300, 480, 600, 1200, 1800, 3600, 5400]


# ------------------------------------------------------------------ lecture
def sniff_format(data: bytes, filename: str = "") -> str:
    """Identifie le format par signature binaire, puis par extension."""
    if len(data) >= 12 and data[8:12] == b".FIT":
        return "fit"
    head = data[:512].lstrip()
    if head[:1] == b"<":
        lowered = head.lower()
        if b"trainingcenterdatabase" in lowered:
            return "tcx"
        if b"<gpx" in lowered:
            return "gpx"
        return "xml"
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext in ("fit", "tcx", "gpx"):
        return ext
    raise ValueError("Format non reconnu : attendu .fit, .tcx ou .gpx.")


def parse_file(data: bytes, filename: str = "") -> dict:
    """Lit un fichier d'activité et renvoie une structure normalisée."""
    from io import BytesIO
    kind = sniff_format(data, filename)
    if kind == "fit":
        decoded = FIT.decode(BytesIO(data))
        streams = FIT.to_streams(decoded["records"])
        session = decoded["sessions"][0] if decoded["sessions"] else {}
        start = FIT.fit_timestamp(session.get("start_time")) or \
            FIT.fit_timestamp(decoded["file_id"].get("time_created")) or \
            datetime.now(timezone.utc)
        sport = FIT.SPORT_NAMES.get(session.get("sport"), "other")
        sub = FIT.SUB_SPORT_NAMES.get(session.get("sub_sport"))
        manufacturer = FIT.MANUFACTURERS.get(
            decoded["file_id"].get("manufacturer"), "inconnu")
        laps = []
        for i, lap in enumerate(decoded["laps"]):
            laps.append({
                "idx": i, "duration_s": lap.get("total_elapsed_time"),
                "distance_m": lap.get("total_distance"),
                "avg_hr": lap.get("avg_heart_rate"), "max_hr": lap.get("max_heart_rate"),
                "avg_power_w": lap.get("avg_power"), "avg_speed_ms": lap.get("avg_speed"),
                "avg_cadence": lap.get("avg_cadence"),
                "elevation_gain_m": lap.get("total_ascent"),
            })
        return {
            "format": "fit", "sport": sport, "sub_sport": sub,
            "start_time": start,
            "duration_s": session.get("total_elapsed_time") or len(streams.get("time", [])),
            "moving_time_s": session.get("total_timer_time"),
            "streams": streams, "laps": laps, "session": session,
            "device": manufacturer,
            "device_name": decoded["file_id"].get("product_name"),
            "calories": session.get("total_calories"),
            "elevation_gain_m": session.get("total_ascent"),
            "elevation_loss_m": session.get("total_descent"),
            "distance_m": session.get("total_distance"),
            "reported_np": session.get("normalized_power"),
            "reported_tss": session.get("training_stress_score"),
        }
    if kind == "tcx":
        parsed = XML.parse_tcx(data)
    elif kind == "gpx":
        parsed = XML.parse_gpx(data)
    else:
        raise ValueError("Fichier XML non reconnu (ni TCX ni GPX).")
    parsed.setdefault("laps", [])
    parsed["device"] = "import fichier"
    return parsed


# ----------------------------------------------------------------- analyse
def _mean(values) -> float | None:
    clean = [v for v in values if v is not None]
    return round(statistics.fmean(clean), 2) if clean else None


def _max(values) -> float | None:
    clean = [v for v in values if v is not None]
    return round(max(clean), 2) if clean else None


def _elevation(altitude, threshold: float = 1.0) -> tuple[float, float]:
    """Dénivelé cumulé avec seuil anti-bruit barométrique."""
    clean = [v for v in altitude if v is not None]
    if len(clean) < 2:
        return (0.0, 0.0)
    smoothed = PW.rolling_mean(clean, 10)
    gain = loss = 0.0
    ref = smoothed[0]
    for v in smoothed[1:]:
        delta = v - ref
        if delta > threshold:
            gain += delta
            ref = v
        elif delta < -threshold:
            loss += -delta
            ref = v
    return (round(gain, 1), round(loss, 1))


def analyze(parsed: dict, ctx: dict) -> dict:
    """Calcule toutes les métriques dérivées d'une séance."""
    streams = parsed.get("streams") or {}
    sport = parsed.get("sport") or "other"
    duration = float(parsed.get("duration_s") or len(streams.get("time", [])) or 0)
    hr = streams.get("heart_rate") or []
    power = streams.get("power") or []
    speed = streams.get("speed") or []
    altitude = streams.get("altitude") or []
    distance = streams.get("distance") or []
    cadence = streams.get("cadence") or []

    out: dict[str, Any] = {"sport": sport, "duration_s": duration}

    # --- distance, dénivelé -------------------------------------------
    dist = parsed.get("distance_m")
    if not dist and distance:
        clean = [d for d in distance if d is not None]
        dist = round(max(clean), 1) if clean else None
    out["distance_m"] = dist
    if parsed.get("elevation_gain_m") is not None:
        out["elevation_gain_m"] = parsed["elevation_gain_m"]
        out["elevation_loss_m"] = parsed.get("elevation_loss_m")
    elif altitude:
        out["elevation_gain_m"], out["elevation_loss_m"] = _elevation(altitude)
    if altitude:
        clean = [a for a in altitude if a is not None]
        if clean:
            out["elevation_min_m"] = round(min(clean), 1)
            out["elevation_max_m"] = round(max(clean), 1)

    # --- temps en mouvement -------------------------------------------
    if parsed.get("moving_time_s"):
        out["moving_time_s"] = parsed["moving_time_s"]
    elif speed:
        out["moving_time_s"] = float(sum(1 for v in speed if v and v > 0.5))

    # --- fréquence cardiaque ------------------------------------------
    out["avg_hr"] = _mean(hr)
    out["max_hr"] = _max(hr)
    if hr and len(hr) > 120:
        tail = [v for v in hr[-90:] if v is not None]
        peak = [v for v in hr[-180:-90] if v is not None]
        if tail and peak:
            out["hrr60"] = round(max(peak) - min(tail), 1)

    # --- puissance -----------------------------------------------------
    if power and any(v for v in power):
        out["avg_power_w"] = _mean(power)
        out["max_power_w"] = _max(power)
        out["np_w"] = parsed.get("reported_np") or PW.normalized_power(power)
        out["xpower_w"] = PW.xpower(power)
        out["work_kj"] = PW.work_kj(power)
        out["variability_index"] = PW.variability_index(out["np_w"], out["avg_power_w"])
        if ctx.get("ftp_w"):
            out["intensity_factor"] = L.intensity_factor(out["np_w"], ctx["ftp_w"])
            out["tss"] = L.tss(duration, out["np_w"], ctx["ftp_w"])
        out["efficiency_factor"] = PW.efficiency_factor(out["np_w"], out["avg_hr"])
        out["decoupling_pct"] = PW.aerobic_decoupling(power, hr)

    # --- vitesse et allure ---------------------------------------------
    if speed and any(v for v in speed):
        moving = [v for v in speed if v and v > 0.5]
        out["avg_speed_ms"] = round(statistics.fmean(moving), 3) if moving else None
        out["max_speed_ms"] = _max(speed)
        if sport in ("running", "trail_running", "walking", "hiking"):
            gap = RUN.gap_speed_series(speed, altitude, distance)
            ngp = RUN.normalized_graded_speed(gap)
            out["ngp_s_km"] = RUN.speed_to_pace(ngp)
            gap_moving = [v for v in gap if v > 0.5]
            if gap_moving:
                out["gap_pace_s_km"] = RUN.speed_to_pace(statistics.fmean(gap_moving))
            if ctx.get("threshold_speed_ms") and ngp:
                out["rtss"] = L.rtss(duration, ngp, ctx["threshold_speed_ms"])
            if not out.get("efficiency_factor"):
                out["efficiency_factor"] = PW.efficiency_factor(
                    out["avg_speed_ms"], out["avg_hr"])
            if not out.get("decoupling_pct"):
                out["decoupling_pct"] = PW.aerobic_decoupling(gap, hr)
        elif sport == "swimming" and ctx.get("threshold_speed_ms"):
            out["stss"] = L.stss(duration, out["avg_speed_ms"], ctx["threshold_speed_ms"])

    # --- cadence et mécanique ------------------------------------------
    if cadence and any(v for v in cadence):
        out["avg_cadence"] = _mean(cadence)
        out["max_cadence"] = _max(cadence)
        if sport in ("running", "trail_running") and out.get("avg_speed_ms"):
            out["avg_stride_len_m"] = RUN.stride_length(
                out["avg_speed_ms"], out["avg_cadence"] * 2
                if out["avg_cadence"] < 130 else out["avg_cadence"])
    for src, dst, scale in (("stance_time", "avg_gct_ms", 1),
                            ("vertical_oscillation", "avg_vert_osc_cm", 0.1)):
        if streams.get(src):
            value = _mean(streams[src])
            if value:
                out[dst] = round(value * scale, 2)
    if out.get("avg_vert_osc_cm") and out.get("avg_stride_len_m"):
        out["avg_vert_ratio"] = RUN.vertical_ratio(
            out["avg_vert_osc_cm"], out["avg_stride_len_m"])
    if streams.get("temperature"):
        out["avg_temp_c"] = _mean(streams["temperature"])

    # --- TRIMP et hrTSS -------------------------------------------------
    hr_max, hr_rest = ctx.get("hr_max"), ctx.get("hr_rest")
    if hr and hr_max and hr_rest:
        out["trimp_banister"] = L.trimp_banister_series(hr, hr_rest, hr_max, ctx["sex"])
        if ctx.get("lthr"):
            out["hrtss"] = L.hrtss(duration, hr, out.get("avg_hr"), hr_rest,
                                   hr_max, ctx["lthr"], ctx["sex"])

    # --- temps en zones --------------------------------------------------
    zone_times: dict[str, list[float]] = {}
    zones = ctx.get("zones", {})
    if hr and zones.get("hr"):
        zone_times["hr"] = Z.time_in_zones(hr, zones["hr"])
        edwards = Z.time_in_zones(hr, Z.hr_zones("hrmax", hr_max=hr_max)) if hr_max else None
        if edwards:
            out["trimp_edwards"] = L.trimp_edwards(edwards)
        if zones.get("hr3"):
            three = Z.time_in_zones(hr, zones["hr3"])
            out["trimp_lucia"] = L.trimp_lucia(three)
            out["polarization_index"] = Z.polarization_index(*three)
            out["session_type"] = Z.classify_session(Z.zone_distribution(three))
    if power and zones.get("power"):
        zone_times["power"] = Z.time_in_zones(power, zones["power"])
    if speed and zones.get("pace") and sport in ("running", "trail_running"):
        zone_times["pace"] = Z.time_in_zones(
            [v for v in speed], zones["pace"])
    out["zone_times"] = zone_times

    # --- calories --------------------------------------------------------
    calories = parsed.get("calories")
    if not calories:
        if out.get("work_kj"):
            calories = PH.energy_from_power(out["work_kj"])
        elif sport in ("running", "trail_running") and out.get("distance_m") and ctx.get("weight_kg"):
            calories = PH.energy_running(out["distance_m"], ctx["weight_kg"],
                                         out.get("elevation_gain_m") or 0)
        elif out.get("avg_hr") and ctx.get("weight_kg") and ctx.get("age"):
            calories = PH.energy_from_hr(duration, out["avg_hr"], ctx["weight_kg"],
                                         ctx["age"], ctx["sex"])
    out["calories"] = calories

    # --- charge retenue ----------------------------------------------------
    out["load"], out["load_source"] = L.best_load(
        tss_v=out.get("tss"), rtss_v=out.get("rtss"), stss_v=out.get("stss"),
        hrtss_v=out.get("hrtss"), sport=sport)

    # --- courbe record ------------------------------------------------------
    out["mmp"] = {}
    if power and any(v for v in power):
        out["mmp"]["power"] = PW.mean_maximal(power, PW.MMP_DURATIONS)
    if speed and any(v for v in speed) and sport in ("running", "trail_running", "cycling"):
        out["mmp"]["speed"] = PW.mean_maximal(speed, PW.MMP_DURATIONS)
    if hr:
        out["mmp"]["hr"] = PW.mean_maximal(hr, [60, 300, 600, 1200, 1800, 3600])

    # --- W'bal ----------------------------------------------------------------
    if power and ctx.get("cp_w") and ctx.get("w_prime_j"):
        balance = PW.w_bal(power, ctx["cp_w"], ctx["w_prime_j"])
        if balance:
            out["w_bal_min_j"] = round(min(balance), 0)
            out["w_bal_depleted_pct"] = round(
                100 * (1 - min(balance) / ctx["w_prime_j"]), 1)

    if streams.get("lat"):
        first_lat = next((v for v in streams["lat"] if v is not None), None)
        first_lon = next((v for v in streams.get("lon", []) if v is not None), None)
        out["start_lat"], out["start_lon"] = first_lat, first_lon
        out["has_gps"] = 1 if first_lat is not None else 0
    return out


# ------------------------------------------------------------ persistance
SPORT_LABELS = {
    "running": "Course à pied", "trail_running": "Trail", "cycling": "Vélo",
    "swimming": "Natation", "walking": "Marche", "hiking": "Randonnée",
    "rowing": "Aviron", "training": "Renforcement", "other": "Autre",
    "cross_country_skiing": "Ski de fond", "e_biking": "VAE",
    "fitness_equipment": "Cardio salle", "strength_training": "Musculation",
}


def guess_name(sport: str, start: datetime, metrics: dict) -> str:
    hour = start.hour
    moment = ("Séance matinale" if hour < 11 else
              "Séance de midi" if hour < 14 else
              "Séance d'après-midi" if hour < 18 else "Séance du soir")
    sport_label = SPORT_LABELS.get(sport, sport.capitalize())
    dist = metrics.get("distance_m")
    if dist and dist > 500:
        return f"{sport_label} — {dist / 1000:.1f} km ({moment.lower()})"
    return f"{sport_label} — {moment.lower()}"


def store_activity(athlete_id: int, parsed: dict, metrics: dict, *,
                   provider: str = "manual", external_id: str | None = None,
                   source_file: str | None = None, name: str | None = None,
                   notes: str | None = None, rpe: int | None = None,
                   store_streams: bool = True) -> int:
    """Écrit l'activité, ses flux, ses tours et ses agrégats."""
    start: datetime = parsed["start_time"]
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    local_date = start.date().isoformat()

    row = {
        "athlete_id": athlete_id,
        "provider": provider,
        "external_id": external_id or f"{provider}-{int(start.timestamp())}",
        "source_file": source_file,
        "sport": metrics.get("sport") or "other",
        "sub_sport": parsed.get("sub_sport"),
        "name": name or guess_name(metrics.get("sport", "other"), start, metrics),
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "local_date": local_date,
        "duration_s": metrics.get("duration_s") or 0,
        "device_name": parsed.get("device_name") or parsed.get("device"),
        "notes": notes,
        "rpe": rpe,
        "has_streams": 1 if (store_streams and parsed.get("streams")) else 0,
    }
    for key in ("moving_time_s", "distance_m", "elevation_gain_m", "elevation_loss_m",
                "elevation_min_m", "elevation_max_m", "avg_hr", "max_hr", "hrr60",
                "avg_power_w", "max_power_w", "np_w", "xpower_w", "intensity_factor",
                "variability_index", "work_kj", "avg_speed_ms", "max_speed_ms",
                "gap_pace_s_km", "ngp_s_km", "avg_cadence", "max_cadence",
                "avg_stride_len_m", "avg_gct_ms", "avg_vert_osc_cm", "avg_vert_ratio",
                "avg_temp_c", "calories", "tss", "hrtss", "rtss", "stss", "load",
                "load_source", "trimp_banister", "trimp_edwards", "trimp_lucia",
                "decoupling_pct", "efficiency_factor", "polarization_index",
                "start_lat", "start_lon", "has_gps"):
        if metrics.get(key) is not None:
            row[key] = metrics[key]
    if rpe:
        row["session_rpe"] = L.session_rpe(row["duration_s"], rpe)
        if row.get("load") is None:
            row["load"] = L.rpe_to_tss_equivalent(row["duration_s"], rpe)
            row["load_source"] = "rpe"

    existing = db.query_one(
        "SELECT id FROM activities WHERE athlete_id = ? AND provider = ? AND external_id = ?",
        (athlete_id, row["provider"], row["external_id"]))
    if existing:
        activity_id = existing["id"]
        db.update("activities", activity_id, {**row, "updated_at": db.now_iso()})
        db.execute("DELETE FROM activity_zone_time WHERE activity_id = ?", (activity_id,))
        db.execute("DELETE FROM activity_laps WHERE activity_id = ?", (activity_id,))
        db.execute("DELETE FROM best_efforts WHERE activity_id = ?", (activity_id,))
    else:
        activity_id = db.insert("activities", row)

    if store_streams and parsed.get("streams"):
        db.save_streams(activity_id, parsed["streams"])

    for kind, seconds in (metrics.get("zone_times") or {}).items():
        for i, sec in enumerate(seconds, start=1):
            if sec > 0:
                db.execute(
                    "INSERT OR REPLACE INTO activity_zone_time"
                    " (activity_id, kind, zone_idx, seconds) VALUES (?,?,?,?)",
                    (activity_id, kind, i, round(sec, 1)))

    for lap in parsed.get("laps") or []:
        payload = {k: v for k, v in lap.items() if v is not None}
        payload["activity_id"] = activity_id
        payload.setdefault("idx", len(parsed["laps"]))
        try:
            db.insert("activity_laps", payload)
        except Exception:
            pass

    rows = []
    weight = None
    physio = profiles.physiology_at(athlete_id, local_date)
    weight = physio.get("weight_kg")
    for kind, curve in (metrics.get("mmp") or {}).items():
        for duration, (value, offset) in curve.items():
            if duration > (metrics.get("duration_s") or 0):
                continue
            rows.append((athlete_id, activity_id, local_date, row["sport"], kind,
                         duration, value,
                         round(value / weight, 3) if weight and kind == "power" else None,
                         offset))
    if rows:
        db.executemany(
            "INSERT INTO best_efforts (athlete_id, activity_id, local_date, sport,"
            " kind, duration_s, value, value_per_kg, start_offset_s)"
            " VALUES (?,?,?,?,?,?,?,?,?)", rows)
    return activity_id


def import_file(athlete_id: int, data: bytes, filename: str = "",
                provider: str = "manual", rpe: int | None = None,
                notes: str | None = None) -> dict:
    """Chaîne complète : lecture → analyse → stockage → recalcul."""
    parsed = parse_file(data, filename)
    start = parsed["start_time"]
    ctx = profiles.athlete_context(athlete_id, start.date().isoformat())
    metrics = analyze(parsed, ctx)
    activity_id = store_activity(athlete_id, parsed, metrics, provider=provider,
                                 source_file=filename, rpe=rpe, notes=notes)
    rebuild_daily(athlete_id)
    return {"activity_id": activity_id, "metrics": {
        k: v for k, v in metrics.items() if k not in ("mmp", "zone_times")}}


def reanalyze_activity(activity_id: int, store_streams: bool = True) -> dict:
    """Recalcule une séance depuis ses flux stockés (après changement de FTP)."""
    activity = db.query_one("SELECT * FROM activities WHERE id = ?", (activity_id,))
    if not activity:
        raise ValueError("Activité introuvable.")
    streams = db.load_streams(activity_id)
    if not streams:
        return {"activity_id": activity_id, "skipped": "aucun flux stocké"}
    parsed = {
        "streams": streams, "sport": activity["sport"],
        "sub_sport": activity["sub_sport"],
        "start_time": datetime.fromisoformat(activity["start_time"].replace("Z", "+00:00")),
        "duration_s": activity["duration_s"],
        "moving_time_s": activity["moving_time_s"],
        "distance_m": activity["distance_m"], "laps": [],
        "device": activity["device_name"],
    }
    ctx = profiles.athlete_context(activity["athlete_id"], activity["local_date"])
    metrics = analyze(parsed, ctx)
    store_activity(activity["athlete_id"], parsed, metrics,
                   provider=activity["provider"], external_id=activity["external_id"],
                   name=activity["name"], rpe=activity["rpe"],
                   store_streams=False)
    return {"activity_id": activity_id, "load": metrics.get("load")}


# --------------------------------------------------- agrégats quotidiens
def rebuild_daily(athlete_id: int, since: str | None = None) -> dict:
    """Reconstruit ``daily_load`` (PMC, ACWR, monotonie) et les alertes."""
    rows = db.query(
        "SELECT local_date AS date, COALESCE(SUM(load),0) AS load,"
        " COALESCE(SUM(trimp_banister),0) AS trimp, SUM(duration_s) AS duration_s,"
        " COALESCE(SUM(distance_m),0) AS distance_m,"
        " COALESCE(SUM(elevation_gain_m),0) AS elevation_m, COUNT(*) AS sessions"
        " FROM activities WHERE athlete_id = ? GROUP BY local_date ORDER BY local_date",
        (athlete_id,))
    if not rows:
        return {"days": 0}
    daily = {r["date"]: r["load"] for r in rows}
    by_date = {r["date"]: r for r in rows}
    start = datetime.fromisoformat(rows[0]["date"]).date()
    end = max(datetime.fromisoformat(rows[-1]["date"]).date(),
              datetime.now(timezone.utc).date())
    series = PMC.compute_pmc(daily, start, end)

    payload = []
    for point in series:
        agg = by_date.get(point["date"], {})
        payload.append((
            athlete_id, point["date"], point["load"], agg.get("trimp") or 0,
            agg.get("duration_s") or 0, agg.get("distance_m") or 0,
            agg.get("elevation_m") or 0, agg.get("sessions") or 0,
            point["ctl"], point["atl"], point["tsb"], point["ctl_ramp_7d"],
            point["acwr_rolling"], point["acwr_ewma"], point["monotony"],
            point["strain"],
        ))
    db.execute("DELETE FROM daily_load WHERE athlete_id = ?", (athlete_id,))
    db.executemany(
        "INSERT INTO daily_load (athlete_id, date, load, trimp, duration_s,"
        " distance_m, elevation_m, sessions, ctl, atl, tsb, ctl_ramp_7d,"
        " acwr_rolling, acwr_ewma, monotony, strain)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", payload)

    refresh_alerts(athlete_id, series)
    return {"days": len(series), "ctl": series[-1]["ctl"], "tsb": series[-1]["tsb"]}


def refresh_alerts(athlete_id: int, series: list[dict] | None = None) -> int:
    """Réévalue les alertes du jour pour un athlète."""
    athlete = db.query_one("SELECT * FROM athletes WHERE id = ?", (athlete_id,))
    if not athlete:
        return 0
    if series is None:
        series = db.query(
            "SELECT date, load, ctl, atl, tsb, ctl_ramp_7d, acwr_rolling,"
            " acwr_ewma, monotony, strain FROM daily_load"
            " WHERE athlete_id = ? ORDER BY date", (athlete_id,))
    wellness = db.query(
        "SELECT * FROM wellness WHERE athlete_id = ? ORDER BY date", (athlete_id,))
    injuries = db.query(
        "SELECT * FROM injuries WHERE athlete_id = ? AND status != 'résolue'",
        (athlete_id,))
    alerts = RISK.evaluate(athlete, series, wellness, injuries)
    today = series[-1]["date"] if series else datetime.now(timezone.utc).date().isoformat()
    db.execute("DELETE FROM alerts WHERE athlete_id = ? AND date = ? AND acknowledged = 0",
               (athlete_id, today))
    for alert in alerts:
        try:
            db.insert("alerts", alert, replace=True)
        except Exception:
            pass
    return len(alerts)
