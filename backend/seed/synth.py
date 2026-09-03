"""Synthèse de séries temporelles d'entraînement réalistes.

L'objectif n'est pas de « faire joli » mais de produire des signaux qui se
comportent comme de vraies données de montre, afin que les métriques
calculées par le pipeline (NP, découplage, temps en zones, courbe record)
aient des valeurs plausibles :

* la **fréquence cardiaque** suit l'intensité avec une réponse du premier
  ordre (constante de temps ≈ 30 s), pas instantanément ;
* elle **dérive** vers le haut au fil de l'effort (dérive cardiaque), d'autant
  plus que l'intensité et la durée sont élevées ;
* la **puissance** et la **vitesse** portent un bruit corrélé (marche
  aléatoire filtrée), pas un bruit blanc ;
* le **relief** module la vitesse en course et la puissance en vélo ;
* la **trace GPS** est cohérente avec la distance parcourue.
"""
from __future__ import annotations

import math
import random
from typing import Sequence

# Intensités relatives par zone d'entraînement (fraction du seuil)
INTENSITY_FRACTION = {
    "récupération": 0.62, "endurance": 0.74, "tempo": 0.88,
    "seuil": 0.99, "VO2max": 1.12, "neuromusculaire": 1.45,
    "compétition": 1.02, "longue": 0.78,
}

# Structure des séances : (nom du bloc, part de la durée, intensité relative)
# Les niveaux sont exprimés en fraction de l'intensité au seuil (FTP en vélo,
# vitesse seuil en course). Calibrés pour que les séances produites tombent
# dans les fourchettes d'IF attendues : ~0,55 en récupération, 0,65-0,75 en
# endurance, 0,85-0,95 au seuil, > 1,00 en VO2max.
SESSION_SHAPES = {
    "endurance": [("échauffement", 0.10, 0.56), ("corps", 0.80, 0.67),
                  ("retour au calme", 0.10, 0.52)],
    "longue": [("échauffement", 0.08, 0.56), ("corps", 0.72, 0.69),
               ("finale", 0.12, 0.82), ("retour au calme", 0.08, 0.54)],
    "récupération": [("corps", 1.0, 0.50)],
    "tempo": [("échauffement", 0.18, 0.62), ("bloc tempo", 0.55, 0.86),
              ("retour au calme", 0.27, 0.55)],
    "seuil": [("échauffement", 0.20, 0.64), ("seuil 1", 0.22, 1.00),
              ("récupération", 0.06, 0.58), ("seuil 2", 0.22, 0.99),
              ("retour au calme", 0.30, 0.54)],
    "VO2max": [("échauffement", 0.25, 0.66), ("intervalles", 0.40, 1.15),
               ("retour au calme", 0.35, 0.53)],
    "neuromusculaire": [("échauffement", 0.30, 0.62), ("sprints", 0.25, 1.55),
                        ("retour au calme", 0.45, 0.52)],
    "compétition": [("échauffement", 0.10, 0.68), ("course", 0.85, 1.03),
                    ("retour au calme", 0.05, 0.50)],
}

# Nombre de répétitions pour les blocs fractionnés
INTERVAL_PATTERNS = {
    "VO2max": (8, 180, 90),          # 8 × 3 min / 90 s de récupération
    "neuromusculaire": (10, 20, 160),
    "seuil": (2, 900, 300),
}


def _correlated_noise(n: int, sigma: float, memory: float,
                      rng: random.Random) -> list[float]:
    """Bruit auto-corrélé (processus AR(1)) : plus réaliste qu'un bruit blanc."""
    out = []
    value = 0.0
    for _ in range(n):
        value = memory * value + rng.gauss(0, sigma)
        out.append(value)
    return out


def _inject_surges(profile: list[float], shape_key: str,
                   rng: random.Random) -> list[float]:
    """Insère quelques pointes courtes dans les séances en aisance.

    Sur le terrain, une sortie « facile » n'est jamais parfaitement lisse :
    relance après un feu, panneau d'entrée d'agglomération, bosse attaquée.
    Sans ces pointes, la courbe record resterait vide en dessous d'une minute
    et sous-estimerait la puissance neuromusculaire de l'athlète.
    """
    if shape_key not in ("endurance", "longue", "récupération", "tempo"):
        return profile
    n = len(profile)
    if n < 900 or rng.random() > 0.45:
        return profile
    for _ in range(rng.randint(1, 4)):
        length = rng.randint(8, 45)
        start = rng.randint(int(n * 0.15), max(int(n * 0.15) + 1, n - length - 60))
        peak = rng.uniform(1.35, 2.30) if length < 20 else rng.uniform(1.15, 1.55)
        for i in range(length):
            fade = 1.0 - 0.35 * (i / length)
            profile[start + i] = max(profile[start + i], peak * fade)
    return profile


def intensity_profile(shape_key: str, duration_s: int,
                      rng: random.Random) -> list[float]:
    """Construit la courbe d'intensité relative seconde par seconde."""
    shape = SESSION_SHAPES.get(shape_key, SESSION_SHAPES["endurance"])
    profile: list[float] = []
    for name, share, level in shape:
        block = max(1, int(duration_s * share))
        if shape_key in INTERVAL_PATTERNS and name in ("intervalles", "sprints",
                                                       "seuil 1", "seuil 2"):
            reps, work, rest = INTERVAL_PATTERNS[shape_key]
            cycle = work + rest
            for i in range(block):
                in_work = (i % cycle) < work
                fade = 1.0 - 0.04 * (i // cycle)      # légère baisse sur les dernières
                profile.append(level * fade if in_work else 0.60)
        else:
            for i in range(block):
                ramp = 1.0
                if name == "échauffement":
                    ramp = 0.85 + 0.15 * (i / max(1, block))
                elif name in ("retour au calme", "récupération"):
                    ramp = 1.0 - 0.12 * (i / max(1, block))
                elif name == "finale":
                    ramp = 1.0 + 0.06 * (i / max(1, block))
                profile.append(level * ramp)
    while len(profile) < duration_s:
        profile.append(profile[-1] if profile else 0.7)
    return _inject_surges(profile[:duration_s], shape_key, rng)


def altitude_profile(duration_s: int, elevation_gain_m: float, base_m: float,
                     rng: random.Random) -> list[float]:
    """Relief : somme de deux sinusoïdes de périodes différentes, plus du bruit."""
    if elevation_gain_m <= 0:
        return [base_m] * duration_s
    n_hills = max(1, int(elevation_gain_m / 90))
    amplitude = elevation_gain_m / (2 * n_hills)
    phase = rng.random() * math.tau
    out = []
    for i in range(duration_s):
        t = i / duration_s
        value = (base_m
                 + amplitude * math.sin(math.tau * n_hills * t + phase)
                 + amplitude * 0.35 * math.sin(math.tau * n_hills * 3.3 * t))
        out.append(round(value, 1))
    smooth = _correlated_noise(duration_s, 0.15, 0.98, rng)
    return [round(a + s, 1) for a, s in zip(out, smooth)]


def heart_rate_series(intensity: Sequence[float], hr_rest: float, hr_max: float,
                      lthr: float, rng: random.Random,
                      fatigue: float = 0.0) -> list[float]:
    """FC issue de l'intensité, avec réponse retardée et dérive cardiaque.

    ``fatigue`` (0 à 1) élève légèrement la FC pour une même intensité, ce
    qui reproduit l'effet d'une charge accumulée ou d'une chaleur élevée.
    """
    n = len(intensity)
    tau = 32.0                       # constante de temps de la réponse cardiaque
    alpha = 1 - math.exp(-1.0 / tau)
    reserve = hr_max - hr_rest
    noise = _correlated_noise(n, 0.45, 0.96, rng)
    hr = hr_rest + reserve * 0.25
    out = []
    lthr_reserve = max(1.0, lthr - hr_rest)
    for i, level in enumerate(intensity):
        # La FC ne suit pas linéairement l'intensité : elle se rapporte à la
        # RÉSERVE de FC, avec une pente qui s'aplatit en bas d'échelle
        # (exposant 0,62). Ainsi 62 % du seuil donne ~73 % de la réserve —
        # ce que l'on mesure réellement sur un footing en aisance.
        fraction = level ** 0.62
        target = hr_rest + lthr_reserve * fraction
        target = min(hr_max - 1, max(hr_rest + 12, target))
        target *= (1 + 0.02 * fatigue)
        drift = 1 + (0.035 * (i / max(1, n)) * min(1.4, level))   # dérive cardiaque
        hr += alpha * (target * drift - hr)
        out.append(round(min(hr_max, max(hr_rest, hr + noise[i])), 1))
    return out


def power_series(intensity: Sequence[float], ftp: float, altitude: Sequence[float],
                 rng: random.Random, indoor: bool = False) -> list[float]:
    """Puissance : intensité × FTP, modulée par la pente et un bruit corrélé."""
    n = len(intensity)
    sigma = 0.012 if indoor else 0.055
    noise = _correlated_noise(n, ftp * sigma, 0.90, rng)
    out = []
    for i, level in enumerate(intensity):
        grade_boost = 0.0
        if not indoor and i >= 10:
            slope = (altitude[i] - altitude[i - 10]) / 10.0
            grade_boost = max(-0.28, min(0.30, slope * 0.9))
        value = ftp * level * (1 + grade_boost) + noise[i]
        out.append(round(max(0.0, value), 1))
    return out


def speed_series(intensity: Sequence[float], threshold_speed: float,
                 altitude: Sequence[float], rng: random.Random) -> list[float]:
    """Vitesse en course : la pente ralentit à coût énergétique constant."""
    from ..science.running import grade_factor
    n = len(intensity)
    noise = _correlated_noise(n, threshold_speed * 0.020, 0.93, rng)
    out = []
    for i, level in enumerate(intensity):
        grade = 0.0
        if i >= 12:
            rise = altitude[i] - altitude[i - 12]
            run = max(1.0, threshold_speed * level * 12)
            grade = max(-0.30, min(0.30, rise / run))
        flat_speed = threshold_speed * level
        actual = flat_speed / max(0.45, grade_factor(grade))
        out.append(round(max(0.5, actual + noise[i]), 3))
    return out


def cadence_series(intensity: Sequence[float], base: float, spread: float,
                   rng: random.Random) -> list[float]:
    noise = _correlated_noise(len(intensity), spread * 0.3, 0.92, rng)
    return [round(max(30.0, base + spread * (level - 0.8) * 2 + noise[i]), 1)
            for i, level in enumerate(intensity)]


def gps_track(speed: Sequence[float], start_lat: float, start_lon: float,
              rng: random.Random) -> tuple[list[float], list[float]]:
    """Trace GPS en boucle : cap qui tourne lentement, distance cohérente."""
    lat, lon = start_lat, start_lon
    heading = rng.random() * math.tau
    turn_rate = rng.uniform(-0.004, 0.004)
    lats, lons = [], []
    for i, v in enumerate(speed):
        heading += turn_rate + rng.gauss(0, 0.006)
        if i and i % 600 == 0:
            turn_rate = rng.uniform(-0.006, 0.006)
        # 1° de latitude ≈ 111 320 m ; la longitude se resserre avec cos(lat)
        lat += (v * math.cos(heading)) / 111320.0
        lon += (v * math.sin(heading)) / (111320.0 * math.cos(math.radians(lat)))
        lats.append(round(lat, 7))
        lons.append(round(lon, 7))
    return lats, lons


def distance_series(speed: Sequence[float]) -> list[float]:
    out, acc = [], 0.0
    for v in speed:
        acc += v
        out.append(round(acc, 2))
    return out


def build_streams(*, sport: str, shape: str, duration_s: int, ctx: dict,
                  elevation_gain_m: float, rng: random.Random,
                  fatigue: float = 0.0, indoor: bool = False,
                  start_lat: float = 45.76, start_lon: float = 4.83) -> dict:
    """Assemble toutes les séries d'une séance."""
    intensity = intensity_profile(shape, duration_s, rng)
    base_alt = rng.uniform(60, 320)
    altitude = altitude_profile(duration_s, 0 if indoor else elevation_gain_m,
                                base_alt, rng)
    streams: dict[str, list] = {"time": list(range(duration_s))}

    hr_max = ctx.get("hr_max") or 190
    hr_rest = ctx.get("hr_rest") or 50
    lthr = ctx.get("lthr") or round(hr_max * 0.89)
    streams["heart_rate"] = heart_rate_series(intensity, hr_rest, hr_max, lthr,
                                              rng, fatigue)

    if sport in ("cycling", "rowing"):
        ftp = ctx.get("ftp_w") or 220
        streams["power"] = power_series(intensity, ftp, altitude, rng, indoor)
        speed = [round(max(1.5, 8.0 * (p / max(1.0, ftp)) ** 0.34
                           + rng.gauss(0, 0.35)), 3)
                 for p in streams["power"]] if sport == "cycling" else None
        if speed:
            streams["speed"] = speed
        streams["cadence"] = cadence_series(intensity, 88, 8, rng)
    elif sport == "swimming":
        threshold = ctx.get("critical_speed_ms") or 1.25
        streams["speed"] = [round(max(0.5, threshold * level + rng.gauss(0, 0.02)), 3)
                            for level in intensity]
        streams["cadence"] = cadence_series(intensity, 34, 3, rng)
        altitude = [base_alt] * duration_s
    elif sport == "strength_training":
        streams.pop("time", None)
        streams["time"] = list(range(duration_s))
        streams["cadence"] = [0.0] * duration_s
    else:                                   # course à pied et trail
        threshold = ctx.get("threshold_speed_ms") or 3.5
        streams["speed"] = speed_series(intensity, threshold, altitude, rng)
        streams["cadence"] = cadence_series(intensity, 172, 10, rng)
        streams["vertical_oscillation"] = [
            round(max(50, 92 - 10 * (level - 0.8) + rng.gauss(0, 2)), 1)
            for level in intensity]
        streams["stance_time"] = [
            round(max(150, 262 - 45 * (level - 0.8) + rng.gauss(0, 5)), 1)
            for level in intensity]

    if not indoor:
        streams["altitude"] = altitude
        if streams.get("speed") and sport != "swimming":
            streams["lat"], streams["lon"] = gps_track(streams["speed"],
                                                       start_lat, start_lon, rng)
    if streams.get("speed"):
        streams["distance"] = distance_series(streams["speed"])
    streams["temperature"] = [round(rng.uniform(8, 26) if i == 0 else
                                    streams["temperature"][-1] + rng.gauss(0, 0.02), 1)
                              for i in range(duration_s)] if False else \
        [round(rng.uniform(9, 24), 0)] * duration_s
    return streams
