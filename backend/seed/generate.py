"""Génération du jeu de données de démonstration.

Construit un historique cohérent sur plusieurs saisons : périodisation en
mésocycles (trois semaines de charge, une de décharge), affûtage avant les
objectifs A, coupure après compétition, progression des seuils, bien-être
corrélé à la fatigue, blessures, tests de laboratoire et notes d'entraîneur.

Les métriques ne sont jamais inventées : les séances récentes sont générées
sous forme de flux à 1 Hz puis passées dans le *même* pipeline d'analyse que
les fichiers importés. Les séances plus anciennes reçoivent un résumé calculé
analytiquement, pour que la génération reste rapide.
"""
from __future__ import annotations

import json
import math
import random
import statistics
import sys
import time
from datetime import date, datetime, timedelta, timezone

from .. import db, profiles
from ..ingest import pipeline
from ..science import hrv as HRV
from ..science import load as L
from ..science import power as PW
from ..science import readiness as RD
from ..science import running as RUN
from ..science import zones as Z
from . import synth
from .athletes_data import ARCHETYPES, INJURY_TEMPLATES, NOTE_TEMPLATES, TEAMS

# Trame hebdomadaire par nombre de séances : (jour, gabarit, part de volume)
# Trame hebdomadaire par nombre de séances : (jour, gabarit, part de volume).
# Le lundi reste vide pour les volumes modérés : un jour de repos complet est
# le levier de récupération le mieux documenté. Les parts sont volontairement
# contrastées — une semaine dont toutes les journées se ressemblent produit
# une monotonie de Foster élevée, associée aux épisodes de méforme.
WEEK_PATTERNS = {
    6: [(1, "VO2max", 0.13), (2, "endurance", 0.11), (3, "seuil", 0.17),
        (4, "récupération", 0.05), (5, "longue", 0.40), (6, "endurance", 0.14)],
    7: [(1, "VO2max", 0.12), (2, "endurance", 0.10), (3, "seuil", 0.16),
        (4, "récupération", 0.05), (5, "longue", 0.38), (6, "endurance", 0.13),
        (6, "neuromusculaire", 0.06)],
    8: [(0, "récupération", 0.04), (1, "VO2max", 0.13), (1, "endurance", 0.05),
        (2, "endurance", 0.09), (3, "seuil", 0.16), (4, "récupération", 0.04),
        (5, "longue", 0.35), (6, "endurance", 0.14)],
    9: [(0, "récupération", 0.04), (1, "VO2max", 0.12), (1, "endurance", 0.04),
        (2, "endurance", 0.09), (3, "seuil", 0.15), (3, "neuromusculaire", 0.04),
        (4, "récupération", 0.04), (5, "longue", 0.34), (6, "endurance", 0.14)],
    10: [(0, "récupération", 0.03), (0, "endurance", 0.04), (1, "VO2max", 0.12),
         (1, "endurance", 0.04), (2, "endurance", 0.08), (2, "tempo", 0.06),
         (3, "seuil", 0.14), (4, "récupération", 0.03), (5, "longue", 0.32),
         (6, "endurance", 0.14)],
}

SESSION_NAMES = {
    "récupération": ["Footing de récupération", "Décrassage", "Sortie souple"],
    "endurance": ["Endurance fondamentale", "Sortie en aisance", "Volume aérobie"],
    "tempo": ["Bloc tempo", "Allure spécifique", "Travail au rythme"],
    "seuil": ["Séance au seuil", "Blocs au seuil lactique", "Travail de seuil"],
    "VO2max": ["Intervalles VO2max", "Fractionné court", "Séance de puissance aérobie"],
    "longue": ["Sortie longue", "Volume long", "Séance longue spécifique"],
    "neuromusculaire": ["Sprints et lignes droites", "Travail de vitesse"],
    "compétition": ["Compétition", "Course"],
}


def _phase_for(day: date, events: list[tuple]) -> tuple[str, float]:
    """Phase d'entraînement et coefficient de volume à une date donnée."""
    upcoming = [(d, name) for name, d, prio in events if d >= day and prio == "A"]
    past = [(d, name) for name, d, prio in events if d < day and prio == "A"]
    if past:
        last = max(d for d, _ in past)
        since = (day - last).days
        if since <= 5:
            return ("transition", 0.35)
    if not upcoming:
        return ("préparation générale", 0.92)
    nearest = min(d for d, _ in upcoming)
    days_out = (nearest - day).days
    if days_out <= 12:
        return ("affûtage", 0.42 + 0.03 * days_out)
    if days_out <= 45:
        return ("préparation spécifique", 1.02)
    if days_out <= 90:
        return ("développement", 0.98)
    return ("préparation générale", 0.88)


def _mesocycle_factor(week_index: int) -> float:
    """3 semaines de charge croissante puis 1 de décharge."""
    position = week_index % 4
    return [0.92, 1.00, 1.08, 0.63][position]


def _pick_sport(sports: dict, shape: str, rng: random.Random) -> str:
    """Choisit le sport de la séance en respectant la répartition du profil."""
    if shape in ("longue", "seuil", "VO2max"):
        # les séances clés se font dans le sport principal
        return max(sports, key=sports.get)
    keys = list(sports)
    weights = [sports[k] for k in keys]
    return rng.choices(keys, weights=weights)[0]


def _analytic_metrics(sport: str, shape: str, duration_s: int, ctx: dict,
                      elevation_gain_m: float, rng: random.Random) -> dict:
    """Résumé calculé sans générer de flux (séances anciennes).

    On reprend exactement les mêmes gabarits d'intensité que le synthétiseur,
    de sorte que les charges soient sur la même échelle que les séances
    détaillées : moyenne d'ordre 4 du profil d'intensité pour la NP.
    """
    profile = synth.intensity_profile(shape, duration_s, rng)
    mean_level = statistics.fmean(profile)
    np_level = (statistics.fmean(v ** 4 for v in profile)) ** 0.25
    hr_max = ctx.get("hr_max") or 190
    hr_rest = ctx.get("hr_rest") or 50
    lthr = ctx.get("lthr") or round(hr_max * 0.89)
    avg_hr = round(hr_rest + (lthr - hr_rest) * (mean_level ** 0.62) * 1.02, 1)
    max_hr = round(min(hr_max, hr_rest + (lthr - hr_rest) * (max(profile) ** 0.62)), 1)

    out: dict = {
        "sport": sport, "duration_s": duration_s,
        "moving_time_s": duration_s * rng.uniform(0.95, 0.995),
        "avg_hr": avg_hr, "max_hr": max_hr,
        "elevation_gain_m": round(elevation_gain_m),
        "elevation_loss_m": round(elevation_gain_m * rng.uniform(0.94, 1.06)),
        "avg_temp_c": round(rng.uniform(6, 25)),
    }
    out["trimp_banister"] = L.trimp_banister(duration_s, avg_hr, hr_rest, hr_max,
                                             ctx.get("sex", "M"))
    out["hrtss"] = L.hrtss(duration_s, None, avg_hr, hr_rest, hr_max, lthr,
                           ctx.get("sex", "M"))
    if sport in ("cycling", "rowing") and ctx.get("ftp_w"):
        ftp = ctx["ftp_w"]
        out["avg_power_w"] = round(ftp * mean_level, 1)
        out["np_w"] = round(ftp * np_level, 1)
        out["max_power_w"] = round(ftp * max(profile) * rng.uniform(1.3, 1.9), 1)
        out["intensity_factor"] = L.intensity_factor(out["np_w"], ftp)
        out["tss"] = L.tss(duration_s, out["np_w"], ftp)
        out["work_kj"] = round(out["avg_power_w"] * duration_s / 1000, 1)
        out["variability_index"] = round(np_level / mean_level, 3)
        out["efficiency_factor"] = PW.efficiency_factor(out["np_w"], avg_hr)
        if sport == "cycling":
            out["avg_speed_ms"] = round(8.0 * mean_level ** 0.34, 3)
            out["distance_m"] = round(out["avg_speed_ms"] * duration_s * 0.97)
        out["avg_cadence"] = round(rng.uniform(84, 93), 1)
    elif sport == "swimming" and ctx.get("critical_speed_ms"):
        speed = ctx["critical_speed_ms"] * mean_level
        out["avg_speed_ms"] = round(speed, 3)
        out["distance_m"] = round(speed * duration_s * 0.96)
        out["stss"] = L.stss(duration_s, speed, ctx["critical_speed_ms"])
        out["avg_cadence"] = round(rng.uniform(31, 37), 1)
    elif sport in ("running", "trail_running") and ctx.get("threshold_speed_ms"):
        threshold = ctx["threshold_speed_ms"]
        if sport == "trail_running":
            threshold *= 0.80                      # terrain technique
        speed = threshold * mean_level
        ngp = threshold * np_level
        out["avg_speed_ms"] = round(speed, 3)
        out["max_speed_ms"] = round(threshold * max(profile), 3)
        out["distance_m"] = round(speed * duration_s * 0.985)
        out["ngp_s_km"] = RUN.speed_to_pace(ngp)
        out["gap_pace_s_km"] = RUN.speed_to_pace(speed * 1.03)
        out["rtss"] = L.rtss(duration_s, ngp, ctx["threshold_speed_ms"])
        out["efficiency_factor"] = PW.efficiency_factor(speed, avg_hr)
        out["avg_cadence"] = round(rng.uniform(166, 180), 1)
        out["avg_stride_len_m"] = RUN.stride_length(speed, out["avg_cadence"] * 2)
    else:
        out["avg_cadence"] = None

    out["decoupling_pct"] = round(rng.gauss(3.2, 2.4), 2) if duration_s > 3600 else None
    out["load"], out["load_source"] = L.best_load(
        tss_v=out.get("tss"), rtss_v=out.get("rtss"), stss_v=out.get("stss"),
        hrtss_v=out.get("hrtss"), sport=sport)
    out["calories"] = round((out.get("work_kj") or duration_s * 0.19) *
                            (1.0 if out.get("work_kj") else 1.0))
    # temps en zones approximé depuis le profil d'intensité
    zones = ctx.get("zones", {}).get("hr") or []
    if zones:
        hr_series = [hr_rest + (lthr - hr_rest) * (level ** 0.62) for level in profile]
        out["zone_times"] = {"hr": Z.time_in_zones(hr_series, zones)}
        three = ctx.get("zones", {}).get("hr3") or []
        if three:
            buckets = Z.time_in_zones(hr_series, three)
            out["polarization_index"] = Z.polarization_index(*buckets)
    return out


def _synthetic_best_efforts(metrics: dict, sport: str, ctx: dict,
                            rng: random.Random) -> dict:
    """Courbe record approchée pour les séances sans flux stocké.

    On applique un modèle hyperbolique P(t) = W'/t + CP à l'intensité de la
    séance : une séance facile ne produit pas de record, une séance intense
    approche la courbe de l'athlète.
    """
    out: dict[str, dict] = {}
    duration = metrics.get("duration_s") or 0
    sprint_effort = (rng.uniform(0.86, 1.00) if rng.random() < 0.17
                     else rng.uniform(0.38, 0.62))
    if sport in ("cycling", "rowing") and ctx.get("cp_w"):
        cp = ctx["cp_w"]
        w_prime = ctx.get("w_prime_j") or 18000
        p_max = (ctx.get("physiology") or {}).get("pmax_w") or cp * 3.6
        effort = min(1.0, (metrics.get("intensity_factor") or 0.6) / 0.95)
        curve = {}
        for d in PW.MMP_DURATIONS:
            if d > duration:
                continue
            # plafond borné par Pmax (modèle de Morton) : sans cela le modèle
            # à 2 paramètres prédirait plusieurs milliers de watts sur 5 s
            ceiling = PW.power_duration(d, cp, w_prime, p_max)
            reach = 0.55 + 0.45 * effort
            if d < 60:
                # Sur le court, tout dépend d'un sprint ponctuel : la plupart
                # des séances n'en contiennent pas, une sur six va très haut.
                reach = sprint_effort
            value = ceiling * reach * rng.uniform(0.96, 1.02)
            curve[d] = (round(min(value, ceiling), 1), 0)
        if curve:
            out["power"] = curve
    if sport in ("running", "trail_running") and ctx.get("critical_speed_ms"):
        cs = ctx["critical_speed_ms"]
        if sport == "trail_running":
            cs *= 0.80
        d_prime = ctx.get("d_prime_m") or 180
        v_max = cs * 1.85                      # vitesse de sprint plafond
        pace_level = (metrics.get("avg_speed_ms") or 0) / max(0.1, cs)
        effort = min(1.0, pace_level / 0.85)
        curve = {}
        for d in PW.MMP_DURATIONS:
            if d > duration:
                continue
            ceiling = PW.speed_duration(d, cs, d_prime, v_max)
            reach = 0.60 + 0.40 * effort
            if d < 60:
                reach = sprint_effort
            value = ceiling * reach * rng.uniform(0.97, 1.02)
            curve[d] = (round(min(value, ceiling), 3), 0)
        if curve:
            out["speed"] = curve
    return out


def generate(athletes: int = 8, days: int = 400, stream_days: int = 120,
             reset: bool = True, seed: int = 20260903, verbose: bool = True) -> dict:
    """Point d'entrée : construit la base de démonstration."""
    started = time.time()
    rng = random.Random(seed)
    db.init_db()

    if reset:
        for table in ("best_efforts", "activity_zone_time", "activity_laps",
                      "activity_streams", "activities", "wellness", "daily_load",
                      "planned_workouts", "training_blocks", "events",
                      "lactate_points", "lab_tests", "injuries", "alerts",
                      "coach_notes", "sync_log", "provider_accounts", "devices",
                      "oauth_states", "physiology", "zones", "zone_models",
                      "athletes", "teams"):
            db.execute(f"DELETE FROM {table}")

    team_ids = [db.insert("teams", team) for team in TEAMS]
    today = date.today()
    start = today - timedelta(days=days)
    counts = {"athletes": 0, "activities": 0, "wellness": 0, "streams": 0,
              "events": 0, "planned": 0, "tests": 0, "injuries": 0}

    for index, archetype in enumerate(ARCHETYPES[:athletes]):
        athlete_id = _create_athlete(archetype, team_ids, start, rng)
        counts["athletes"] += 1
        if verbose:
            print(f"  · {archetype['first_name']} {archetype['last_name']}"
                  f" ({archetype['discipline']})", flush=True)

        events = _create_events(athlete_id, archetype, today, rng)
        counts["events"] += len(events)
        _create_physiology_history(athlete_id, archetype, start, today, rng)
        injuries = _create_injuries(athlete_id, archetype, start, today, rng, index)
        counts["injuries"] += len(injuries)

        created, streamed = _create_training(
            athlete_id, archetype, start, today, stream_days, events, injuries, rng)
        counts["activities"] += created
        counts["streams"] += streamed

        pipeline.rebuild_daily(athlete_id)
        counts["wellness"] += _create_wellness(athlete_id, archetype, start, today, rng)
        counts["planned"] += _create_planned(athlete_id, archetype, today, rng)
        counts["tests"] += _create_tests(athlete_id, archetype, start, today, rng)
        _create_blocks(athlete_id, events, start, today)
        _create_notes(athlete_id, start, today, rng)
        _create_devices(athlete_id, archetype, index, rng)
        pipeline.rebuild_daily(athlete_id)
        pipeline.refresh_alerts(athlete_id)

    counts["seconds"] = round(time.time() - started, 1)
    if verbose:
        print(f"\n  Terminé en {counts['seconds']} s — "
              f"{counts['activities']} séances, {counts['wellness']} relevés.")
    return counts


# ------------------------------------------------------------------ éléments
def _create_athlete(archetype: dict, team_ids: list, start: date,
                    rng: random.Random) -> int:
    team = team_ids[1] if archetype["primary_sport"] == "cycling" else team_ids[0]
    athlete_id = db.insert("athletes", {
        "first_name": archetype["first_name"], "last_name": archetype["last_name"],
        "sex": archetype["sex"], "birth_date": archetype["birth_date"],
        "height_cm": archetype["height_cm"], "weight_kg": archetype["weight_kg"],
        "primary_sport": archetype["primary_sport"],
        "discipline": archetype["discipline"], "level": archetype["level"],
        "team_id": team, "country": archetype["country"],
        "accent": archetype["accent"], "status": "active",
        "email": f"{archetype['first_name'].lower()}."
                 f"{archetype['last_name'].lower()}@exemple.fr",
        "joined_at": (start - timedelta(days=rng.randint(200, 900))).isoformat(),
    })
    return athlete_id


def _create_physiology_history(athlete_id: int, archetype: dict, start: date,
                               today: date, rng: random.Random) -> None:
    """Profil physiologique révisé tous les ~2 mois, en progression."""
    base = dict(archetype["physio"])
    progression = archetype["progression"]
    cursor = start - timedelta(days=30)
    step = 0
    total_steps = max(1, (today - cursor).days // 60)
    while cursor <= today:
        factor = 1 + progression * (step / total_steps)
        row = {"athlete_id": athlete_id, "effective_date": cursor.isoformat(),
               "source": "terrain" if step % 2 else "laboratoire",
               "weight_kg": round(archetype["weight_kg"] * rng.uniform(0.985, 1.012), 1),
               "max_hr_source": "test"}
        for key, value in base.items():
            if key in ("hr_max", "hr_rest", "hr_lt1", "hr_lt2"):
                row[key] = round(value + rng.gauss(0, 0.8))
            elif key == "threshold_pace_s_km":
                row[key] = round(value / factor, 1)
                row["critical_speed_ms"] = round(1000 / row[key], 4)
            elif key == "running_economy":
                row[key] = round(value / factor, 1)
            else:
                row[key] = round(value * factor, 2)
        if row.get("critical_speed_ms"):
            row["d_prime_m"] = round(rng.uniform(150, 240), 1)
        db.insert("physiology", row)
        cursor += timedelta(days=60)
        step += 1


def _create_events(athlete_id: int, archetype: dict, today: date,
                   rng: random.Random) -> list[tuple]:
    """Objectifs passés et à venir ; renvoie [(nom, date, priorité)]."""
    out = []
    for name, offset, priority, distance, target in archetype["events"]:
        for cycle in (-1, 0):                       # une saison passée, une à venir
            event_date = today + timedelta(days=offset + cycle * 365)
            result_time = result_rank = None
            if event_date < today:
                result_time = round(target * rng.uniform(0.985, 1.045))
                result_rank = rng.randint(1, 40)
            db.insert("events", {
                "athlete_id": athlete_id, "name": name,
                "date": event_date.isoformat(), "sport": archetype["primary_sport"],
                "priority": priority, "distance_m": distance,
                "target_time_s": target, "result_time_s": result_time,
                "result_rank": result_rank,
                "location": rng.choice(["France", "Paris", "Lyon", "Annecy",
                                        "Chamonix", "Berlin", "Aix-en-Provence"]),
                "result_notes": ("Course maîtrisée, allure régulière."
                                 if result_time and result_time <= target else
                                 "Fin de course difficile, gestion à revoir."
                                 if result_time else None),
            })
            out.append((name, event_date, priority))
    return out


def _create_training(athlete_id: int, archetype: dict, start: date, today: date,
                     stream_days: int, events: list, injuries: list,
                     rng: random.Random) -> tuple[int, int]:
    """Génère l'historique d'entraînement complet."""
    ctx_cache: dict[str, dict] = {}
    stream_cutoff = today - timedelta(days=stream_days)
    injured_days = set()
    for injury in injuries:
        injury_start = date.fromisoformat(injury["date"])
        for i in range(injury.get("days_lost") or 0):
            injured_days.add((injury_start + timedelta(days=i)).isoformat())

    sessions_per_week = archetype["sessions_per_week"]
    pattern = WEEK_PATTERNS.get(sessions_per_week, WEEK_PATTERNS[7])
    weekly_seconds = archetype["weekly_hours"] * 3600
    event_dates = {d.isoformat(): (name, prio) for name, d, prio in events}

    created = streamed = 0
    rows_to_store: list[tuple] = []
    week_index = 0
    cursor = start - timedelta(days=start.weekday())

    while cursor <= today:
        phase, phase_factor = _phase_for(cursor, events)
        meso = _mesocycle_factor(week_index)
        week_volume = weekly_seconds * phase_factor * meso * rng.uniform(0.94, 1.06)

        for weekday, shape, share in pattern:
            day = cursor + timedelta(days=weekday)
            if day > today or day < start:
                continue
            key = day.isoformat()
            if key in injured_days:
                continue
            if rng.random() < 0.06:                 # aléas de la vie
                continue
            # semaine de décharge : on retire aussi des séances, pas seulement
            # du volume — c'est ce qui restaure vraiment la fraîcheur
            if meso < 0.7 and shape in ("endurance", "récupération") \
                    and rng.random() < 0.45:
                continue

            month_key = key[:7]
            if month_key not in ctx_cache:
                ctx_cache[month_key] = profiles.athlete_context(athlete_id, key)
            ctx = ctx_cache[month_key]

            if key in event_dates:
                name, priority = event_dates[key]
                shape = "compétition"
                duration = _event_duration(archetype, name)
            else:
                duration = int(week_volume * share * rng.uniform(0.90, 1.10))
                duration = max(1500, min(6 * 3600, duration))
                name = rng.choice(SESSION_NAMES[shape])

            sport = (archetype["primary_sport"] if shape == "compétition"
                     else _pick_sport(archetype["sports"], shape, rng))
            elevation = _elevation_for(sport, duration, rng)
            indoor = sport in ("swimming", "strength_training") or rng.random() < 0.12
            start_dt = datetime.combine(
                day, datetime.min.time()).replace(tzinfo=timezone.utc) + \
                timedelta(hours=rng.choice([6, 7, 7, 8, 12, 17, 18, 18, 19]),
                          minutes=rng.randint(0, 55))

            fatigue = min(1.0, max(0.0, (week_index % 4) / 3.0))
            if day >= stream_cutoff:
                streams = synth.build_streams(
                    sport=sport, shape=shape, duration_s=duration, ctx=ctx,
                    elevation_gain_m=elevation, rng=rng, fatigue=fatigue,
                    indoor=indoor, start_lat=45.76 + rng.uniform(-1.5, 2.5),
                    start_lon=4.83 + rng.uniform(-2.0, 2.0))
                parsed = {"streams": streams, "sport": sport,
                          "start_time": start_dt, "duration_s": duration,
                          "laps": [], "device": _device_for(archetype),
                          "device_name": _device_for(archetype)}
                metrics = pipeline.analyze(parsed, ctx)
                pipeline.store_activity(
                    athlete_id, parsed, metrics, provider=_provider_for(archetype),
                    external_id=f"seed-{key}-{weekday}-{shape}", name=name,
                    rpe=_rpe_for(shape, rng))
                streamed += 1
            else:
                metrics = _analytic_metrics(sport, shape, duration, ctx,
                                            elevation, rng)
                metrics["mmp"] = _synthetic_best_efforts(metrics, sport, ctx, rng)
                parsed = {"streams": {}, "sport": sport, "start_time": start_dt,
                          "duration_s": duration, "laps": [],
                          "device": _device_for(archetype),
                          "device_name": _device_for(archetype)}
                pipeline.store_activity(
                    athlete_id, parsed, metrics, provider=_provider_for(archetype),
                    external_id=f"seed-{key}-{weekday}-{shape}", name=name,
                    rpe=_rpe_for(shape, rng), store_streams=False)
            created += 1

        cursor += timedelta(days=7)
        week_index += 1
    return created, streamed


def _event_duration(archetype: dict, name: str) -> int:
    for event_name, _offset, _prio, _distance, target in archetype["events"]:
        if event_name == name:
            return int(target * 1.12)
    return 3600


def _elevation_for(sport: str, duration_s: int, rng: random.Random) -> float:
    hours = duration_s / 3600
    if sport == "trail_running":
        return round(hours * rng.uniform(450, 900))
    if sport == "cycling":
        return round(hours * rng.uniform(120, 520))
    if sport in ("running",):
        return round(hours * rng.uniform(40, 220))
    return 0.0


def _rpe_for(shape: str, rng: random.Random) -> int:
    base = {"récupération": 2, "endurance": 4, "longue": 6, "tempo": 6,
            "seuil": 7, "VO2max": 8, "neuromusculaire": 7, "compétition": 9}
    return max(1, min(10, base.get(shape, 5) + rng.choice([-1, 0, 0, 0, 1])))


def _provider_for(archetype: dict) -> str:
    return {"running": "garmin", "trail_running": "coros", "cycling": "garmin",
            "swimming": "polar", "rowing": "polar"}.get(
                archetype["primary_sport"], "garmin")


def _device_for(archetype: dict) -> str:
    return {"garmin": "Garmin Forerunner 965", "coros": "COROS APEX 2 Pro",
            "polar": "Polar Vantage V3"}[_provider_for(archetype)]


def _create_wellness(athlete_id: int, archetype: dict, start: date, today: date,
                     rng: random.Random) -> int:
    """Bien-être quotidien, corrélé négativement à la fatigue aiguë."""
    loads = {r["date"]: r for r in db.query(
        "SELECT date, atl, ctl, tsb, acwr_ewma FROM daily_load WHERE athlete_id = ?",
        (athlete_id,))}
    base_rmssd = rng.uniform(52, 88)
    base_rhr = archetype["physio"]["hr_rest"] + rng.uniform(-1, 2)
    rows = []
    cursor = start
    ln_history: list[float] = []
    while cursor <= today:
        key = cursor.isoformat()
        if rng.random() < 0.06:                    # mesure oubliée
            cursor += timedelta(days=1)
            continue
        load_row = loads.get(key, {})
        atl = load_row.get("atl") or 0
        ctl = load_row.get("ctl") or 1
        strain = max(-1.0, min(2.0, (atl - ctl) / max(12.0, ctl * 0.35)))

        rmssd = base_rmssd * math.exp(-0.11 * strain) * rng.lognormvariate(0, 0.085)
        rmssd = max(12.0, min(180.0, rmssd))
        ln = HRV.ln_rmssd(rmssd)
        ln_history.append(ln)
        rhr = base_rhr + strain * 3.1 + rng.gauss(0, 1.3)
        sleep = rng.gauss(455, 48) - strain * 12
        deep = sleep * rng.uniform(0.14, 0.22)
        rem = sleep * rng.uniform(0.18, 0.25)
        light = sleep - deep - rem
        subjective_base = 2.4 + strain * 1.15

        def item(spread=0.7):
            return max(1, min(7, round(rng.gauss(subjective_base, spread))))

        row = {
            "athlete_id": athlete_id, "date": key, "source": _provider_for(archetype),
            "hrv_rmssd": round(rmssd, 1), "hrv_ln_rmssd": ln,
            "hrv_sdnn": round(rmssd * rng.uniform(0.85, 1.25), 1),
            "resting_hr": round(rhr, 1),
            "sleep_total_min": round(max(240, sleep), 1),
            "sleep_deep_min": round(max(0, deep), 1),
            "sleep_rem_min": round(max(0, rem), 1),
            "sleep_light_min": round(max(0, light), 1),
            "sleep_awake_min": round(rng.uniform(8, 42), 1),
            "sleep_score": round(max(30, min(100, 82 - strain * 12 + rng.gauss(0, 6)))),
            "spo2_avg": round(rng.uniform(94, 99), 1),
            "respiration_avg": round(rng.uniform(12, 16), 1),
            "steps": round(rng.uniform(7000, 17000)),
            "weight_kg": round(archetype["weight_kg"] + rng.gauss(0, 0.45), 1),
            "fatigue": item(), "soreness": item(), "mood": item(0.6),
            "stress_subj": item(0.8), "sleep_quality": item(0.7),
            "motivation": item(0.6),
        }
        row["hooper_index"] = RD.hooper_index(
            row["fatigue"], row["soreness"], row["mood"],
            row["stress_subj"], row["sleep_quality"])
        baseline = (statistics.fmean(ln_history[-60:-1])
                    if len(ln_history) > 10 else None)
        sd = (statistics.pstdev(ln_history[-60:-1])
              if len(ln_history) > 10 else None)
        score = RD.readiness(
            ln_rmssd=ln, hrv_baseline=baseline, hrv_sd=sd,
            rhr=row["resting_hr"],
            rhr_baseline=base_rhr if len(ln_history) > 10 else None,
            sleep_min=row["sleep_total_min"], sleep_quality=row["sleep_quality"],
            fatigue=row["fatigue"], soreness=row["soreness"], mood=row["mood"],
            stress=row["stress_subj"], motivation=row["motivation"],
            tsb=load_row.get("tsb"), acwr=load_row.get("acwr_ewma"))
        row["readiness"] = score["score"]
        row["readiness_flag"] = score["flag"]
        rows.append(row)
        cursor += timedelta(days=1)

    for row in rows:
        db.upsert("wellness", row, ["athlete_id", "date"])
    return len(rows)


def _create_planned(athlete_id: int, archetype: dict, today: date,
                    rng: random.Random) -> int:
    """Plan des trois prochaines semaines et rapprochement du passé récent."""
    from ..api.planning import INTENSITY_TEMPLATES
    current = db.query_one(
        "SELECT ctl FROM daily_load WHERE athlete_id = ? ORDER BY date DESC LIMIT 1",
        (athlete_id,))
    weekly = round((current["ctl"] if current else 45) * 7 * 1.03, 1)
    pattern = WEEK_PATTERNS.get(archetype["sessions_per_week"], WEEK_PATTERNS[7])
    created = 0
    monday = today - timedelta(days=today.weekday())
    for week in range(3):
        for weekday, shape, share in pattern:
            day = monday + timedelta(days=week * 7 + weekday)
            if day < today:
                continue
            intensity = {"récupération": "récupération", "endurance": "endurance",
                         "longue": "endurance", "tempo": "tempo", "seuil": "seuil",
                         "VO2max": "VO2max"}.get(shape, "endurance")
            load = round(weekly * share, 1)
            template = INTENSITY_TEMPLATES[intensity]
            db.insert("planned_workouts", {
                "athlete_id": athlete_id, "date": day.isoformat(),
                "sport": archetype["primary_sport"],
                "name": rng.choice(SESSION_NAMES[shape]),
                "intensity": intensity, "target_load": load,
                "target_duration_s": round(load / template["load_per_hour"] * 3600),
                "status": "planned"})
            created += 1
    return created


def _create_blocks(athlete_id: int, events: list, start: date, today: date) -> None:
    upcoming = sorted([(d, name) for name, d, prio in events
                       if d >= today - timedelta(days=120) and prio == "A"])
    phases = [("Préparation générale", "préparation générale",
               "Volume aérobie, force fondamentale"),
              ("Préparation spécifique", "spécifique",
               "Travail au seuil et allure de course"),
              ("Affûtage", "affûtage", "Réduction du volume, intensité maintenue")]
    for event_date, name in upcoming[:2]:
        cursor = event_date - timedelta(days=84)
        for i, (label, phase, focus) in enumerate(phases):
            length = [42, 28, 14][i]
            end = cursor + timedelta(days=length - 1)
            db.insert("training_blocks", {
                "athlete_id": athlete_id, "name": f"{label} — {name}",
                "phase": phase, "focus": focus,
                "start_date": cursor.isoformat(), "end_date": end.isoformat()})
            cursor = end + timedelta(days=1)


def _create_injuries(athlete_id: int, archetype: dict, start: date, today: date,
                     rng: random.Random, index: int) -> list[dict]:
    """Une blessure sur trois athlètes environ, avec arrêt effectif."""
    out = []
    if index % 3 != 0:
        return out
    template = dict(rng.choice(INJURY_TEMPLATES))
    injury_date = start + timedelta(days=rng.randint(60, max(61, (today - start).days - 60)))
    days_lost = rng.randint(8, 24)
    template.update({
        "athlete_id": athlete_id, "date": injury_date.isoformat(),
        "side": rng.choice(["gauche", "droite"]), "days_lost": days_lost,
        "status": "résolue",
        "return_date": (injury_date + timedelta(days=days_lost)).isoformat(),
        "notes": "Reprise progressive validée, aucune récidive constatée.",
    })
    db.insert("injuries", template)
    out.append(template)
    return out


def _create_tests(athlete_id: int, archetype: dict, start: date, today: date,
                  rng: random.Random) -> int:
    """Tests de laboratoire, dont une courbe lactate exploitable."""
    physio = archetype["physio"]
    count = 0
    test_date = start + timedelta(days=45)
    while test_date < today:
        if physio.get("ftp_w"):
            test_id = db.insert("lab_tests", {
                "athlete_id": athlete_id, "date": test_date.isoformat(),
                "type": "lactate", "lab": "Laboratoire de physiologie de l'effort",
                "protocol": "Paliers de 4 min, incréments de 30 W, prélèvement au doigt",
                "conclusion": "Seuils confirmés, zones ajustées en conséquence."})
            cp = physio.get("cp_w", 280)
            lactate = 0.9
            for stage in range(1, 9):
                power = round(cp * (0.55 + 0.09 * stage))
                relative = power / cp
                lactate = round(0.85 + 0.35 * math.exp(3.4 * max(0, relative - 0.72)), 2)
                db.insert("lactate_points", {
                    "test_id": test_id, "stage": stage, "intensity": power,
                    "power_w": power, "lactate": min(14.0, lactate),
                    "hr": round(physio["hr_rest"] +
                                (physio["hr_lt2"] - physio["hr_rest"]) * relative ** 0.62),
                    "rpe": min(20, 8 + stage)})
            count += 1
        else:
            db.insert("lab_tests", {
                "athlete_id": athlete_id, "date": test_date.isoformat(),
                "type": "vo2max",
                "lab": "Laboratoire de physiologie de l'effort",
                "protocol": "Rampe 1 km/h par minute jusqu'à épuisement",
                "results": json.dumps({
                    "vo2max": physio.get("vo2max"),
                    "vma_kmh": round((physio.get("vvo2max") or 4.8) * 3.6, 1),
                    "hr_max": physio["hr_max"], "rer_max": 1.14,
                    "lactate_peak": round(rng.uniform(9.5, 14.0), 1)},
                    ensure_ascii=False),
                "conclusion": "Valeurs conformes au niveau annoncé."})
            count += 1
        test_date += timedelta(days=rng.randint(140, 200))
    return count


def _create_notes(athlete_id: int, start: date, today: date,
                  rng: random.Random) -> None:
    for _ in range(rng.randint(4, 8)):
        day = start + timedelta(days=rng.randint(0, (today - start).days))
        category, text = rng.choice(NOTE_TEMPLATES)
        db.insert("coach_notes", {
            "athlete_id": athlete_id, "date": day.isoformat(),
            "author": "Entraîneur", "category": category, "text": text,
            "pinned": 1 if rng.random() < 0.15 else 0})


def _create_devices(athlete_id: int, archetype: dict, index: int,
                    rng: random.Random) -> None:
    provider = _provider_for(archetype)
    db.upsert("provider_accounts", {
        "athlete_id": athlete_id, "provider": provider,
        "provider_user_id": f"demo-{provider}-{athlete_id}",
        "status": "connected" if index % 4 != 3 else "expired",
        "last_sync_at": db.now_iso(),
        "scope": "démonstration — aucun jeton réel enregistré",
    }, ["athlete_id", "provider"])
    db.upsert("devices", {
        "athlete_id": athlete_id, "provider": provider,
        "external_id": f"dev-{athlete_id}", "name": _device_for(archetype),
        "model": _device_for(archetype),
        "manufacturer": provider.capitalize(), "kind": "montre",
        "firmware": f"{rng.randint(8, 22)}.{rng.randint(0, 9)}0",
        "battery_pct": rng.randint(35, 100), "last_seen_at": db.now_iso(),
    }, ["athlete_id", "provider", "external_id"])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Génère le jeu de démonstration.")
    parser.add_argument("--athletes", type=int, default=8)
    parser.add_argument("--days", type=int, default=400)
    parser.add_argument("--stream-days", type=int, default=120)
    parser.add_argument("--seed", type=int, default=20260903)
    args = parser.parse_args()
    print(generate(args.athletes, args.days, args.stream_days, seed=args.seed))
