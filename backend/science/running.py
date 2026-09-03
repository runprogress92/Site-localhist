"""Analyse spécifique à la course à pied.

* **GAP** (Grade Adjusted Pace) — allure corrigée de la pente à partir du
  coût énergétique de la course mesuré par Minetti et al. (2002),
  *J Appl Physiol* 93:1039-1046 : polynôme du 5ᵉ degré du coût métabolique
  (J·kg⁻¹·m⁻¹) en fonction de la pente, valide pour −45 % ≤ i ≤ +45 %.
* **NGP** (Normalized Graded Pace) — équivalent de la NP appliqué à la
  vitesse ajustée : moyenne glissante 30 s puis moyenne d'ordre 4.
* **Vitesse critique** — modèle linéaire distance = CS·t + D'.
* **VDOT / formules de Daniels** — VO2max « de terrain » déduit d'une
  performance, et allures d'entraînement associées.
* **Riegel** (1981) — extrapolation de performance entre distances,
  t₂ = t₁·(d₂/d₁)^1,06.
"""
from __future__ import annotations

import math
from typing import Sequence

from .power import rolling_mean

# Coefficients de Minetti (coût en J/kg/m) — Cr(i)
_MINETTI = (155.4, -30.4, -43.3, 46.3, 19.5, 3.6)
_CR_FLAT = 3.6           # coût sur le plat, J/kg/m


def grade_cost(grade: float) -> float:
    """Coût énergétique de la course pour une pente donnée (J/kg/m).

    ``grade`` est une fraction (0,05 = +5 %). Bornée à ±45 %, domaine de
    validité du polynôme ; au-delà, la course laisse place à la marche.
    """
    i = max(-0.45, min(0.45, grade))
    a, b, c, d, e, f = _MINETTI
    return a * i ** 5 + b * i ** 4 + c * i ** 3 + d * i ** 2 + e * i + f


def grade_factor(grade: float) -> float:
    """Facteur multiplicatif à appliquer à la vitesse pour l'équivalent plat."""
    return grade_cost(grade) / _CR_FLAT


def gap_speed_series(speed: Sequence[float | None], altitude: Sequence[float | None],
                     distance: Sequence[float | None] | None = None,
                     sample_rate: float = 1.0,
                     smooth_window: int = 15) -> list[float]:
    """Série de vitesses ajustées à la pente (m/s équivalent plat).

    L'altitude est lissée sur ``smooth_window`` secondes avant dérivation :
    le bruit barométrique produirait sinon des pentes aberrantes.
    """
    n = len(speed)
    if n == 0:
        return []
    alt = [a if a is not None else 0.0 for a in (altitude or [0.0] * n)]
    if len(alt) < n:
        alt = alt + [alt[-1] if alt else 0.0] * (n - len(alt))
    w = max(1, int(round(smooth_window * sample_rate)))
    alt_s = rolling_mean(alt, w)
    dt = 1.0 / sample_rate
    out: list[float] = []
    for i in range(n):
        v = speed[i] or 0.0
        if v <= 0.3:                       # arrêt / marche : pas d'ajustement
            out.append(0.0)
            continue
        j = max(0, i - w)
        d_alt = alt_s[i] - alt_s[j]
        if distance is not None and distance[i] is not None and distance[j] is not None:
            d_hor = distance[i] - distance[j]
        else:
            d_hor = v * (i - j) * dt
        grade = d_alt / d_hor if d_hor > 1 else 0.0
        out.append(v * grade_factor(grade))
    return out


def normalized_graded_speed(gap_series: Sequence[float], sample_rate: float = 1.0) -> float | None:
    """NGP exprimée en m/s (même algèbre que la puissance normalisée)."""
    data = [v for v in gap_series if v is not None]
    if len(data) < 30 * sample_rate:
        return None
    window = max(1, int(round(30 * sample_rate)))
    smoothed = rolling_mean(data, window)[window - 1:]
    if not smoothed:
        return None
    moving = [v for v in smoothed if v > 0.3]
    if not moving:
        return None
    fourth = sum(v ** 4 for v in moving) / len(moving)
    return round(fourth ** 0.25, 3)


# ------------------------------------------------------------- conversions
def speed_to_pace(speed_ms: float | None) -> float | None:
    """m/s → secondes par kilomètre."""
    if not speed_ms or speed_ms <= 0:
        return None
    return round(1000.0 / speed_ms, 1)


def pace_to_speed(pace_s_km: float | None) -> float | None:
    if not pace_s_km or pace_s_km <= 0:
        return None
    return round(1000.0 / pace_s_km, 4)


def format_pace(pace_s_km: float | None) -> str:
    if not pace_s_km or pace_s_km <= 0 or pace_s_km > 3600:
        return "—"
    m, s = divmod(int(round(pace_s_km)), 60)
    return f"{m}:{s:02d}/km"


# ------------------------------------------------------- vitesse critique
def critical_speed(efforts: Sequence[tuple[float, float]]) -> dict | None:
    """Modèle linéaire distance–temps : d = CS·t + D'.

    ``efforts`` : (durée_s, distance_m). Domaine retenu : 2 à 20 min.
    """
    pts = [(t, d) for t, d in efforts if 120 <= t <= 1200 and d and d > 0]
    if len(pts) < 2:
        return None
    n = len(pts)
    mt = sum(t for t, _ in pts) / n
    md = sum(d for _, d in pts) / n
    stt = sum((t - mt) ** 2 for t, _ in pts)
    if stt <= 0:
        return None
    std = sum((t - mt) * (d - md) for t, d in pts)
    cs = std / stt              # pente = vitesse critique (m/s)
    d_prime = md - cs * mt      # ordonnée = D' (mètres)
    ss_tot = sum((d - md) ** 2 for _, d in pts)
    ss_res = sum((d - (d_prime + cs * t)) ** 2 for t, d in pts)
    if cs <= 0:
        return None
    return {
        "cs_ms": round(cs, 3),
        "cs_pace_s_km": speed_to_pace(cs),
        "d_prime_m": round(d_prime, 1),
        "r2": round(1 - ss_res / ss_tot, 4) if ss_tot > 0 else None,
        "n_points": n,
    }


# -------------------------------------------------------------- VDOT Daniels
def vo2_at_speed(speed_m_min: float) -> float:
    """Coût en O2 d'une vitesse de course (Daniels & Gilbert), ml/kg/min."""
    return -4.60 + 0.182258 * speed_m_min + 0.000104 * speed_m_min ** 2


def pct_vo2max_at_time(minutes: float) -> float:
    """Fraction de VO2max soutenable pour une durée d'effort donnée."""
    return (0.8 + 0.1894393 * math.exp(-0.012778 * minutes)
            + 0.2989558 * math.exp(-0.1932605 * minutes))


def vdot(distance_m: float, time_s: float) -> float | None:
    """VDOT : VO2max « de terrain » déduit d'une performance en course."""
    if not distance_m or not time_s or time_s <= 0:
        return None
    minutes = time_s / 60.0
    speed = distance_m / minutes            # m/min
    v = vo2_at_speed(speed) / pct_vo2max_at_time(minutes)
    return round(v, 1) if 20 <= v <= 95 else None


def speed_for_vo2(target_vo2: float) -> float:
    """Inverse de :func:`vo2_at_speed` (résolution de l'équation du 2ᵈ degré)."""
    a, b, c = 0.000104, 0.182258, -4.60 - target_vo2
    disc = b * b - 4 * a * c
    if disc < 0:
        return 0.0
    return (-b + math.sqrt(disc)) / (2 * a)   # m/min


DANIELS_INTENSITIES = {
    "easy":      (0.59, 0.74, "Endurance fondamentale (E)"),
    "marathon":  (0.75, 0.84, "Allure marathon (M)"),
    "threshold": (0.83, 0.88, "Seuil (T) — ~1 h de course"),
    "interval":  (0.95, 1.00, "Intervalles VO2max (I)"),
    "repetition": (1.05, 1.20, "Répétitions / vitesse (R)"),
}


def daniels_paces(vdot_value: float) -> dict[str, dict]:
    """Allures d'entraînement de Daniels pour un VDOT donné."""
    out = {}
    for key, (lo, hi, label) in DANIELS_INTENSITIES.items():
        v_lo = speed_for_vo2(vdot_value * lo) / 60.0     # m/s
        v_hi = speed_for_vo2(vdot_value * hi) / 60.0
        out[key] = {
            "label": label,
            "speed_min_ms": round(v_lo, 3),
            "speed_max_ms": round(v_hi, 3),
            "pace_slow_s_km": speed_to_pace(v_lo),
            "pace_fast_s_km": speed_to_pace(v_hi),
        }
    return out


RACE_DISTANCES = {
    "1500 m": 1500, "3000 m": 3000, "5 km": 5000, "10 km": 10000,
    "15 km": 15000, "10 miles": 16093, "Semi-marathon": 21097.5,
    "Marathon": 42195,
}


def riegel_predict(known_distance_m: float, known_time_s: float,
                   target_distance_m: float, exponent: float = 1.06) -> float | None:
    """Prédiction de Riegel : t₂ = t₁ · (d₂/d₁)^k, k ≈ 1,06."""
    if not (known_distance_m and known_time_s and target_distance_m):
        return None
    return round(known_time_s * (target_distance_m / known_distance_m) ** exponent, 1)


def race_predictions(distance_m: float, time_s: float) -> list[dict]:
    """Tableau de prédictions sur les distances de référence."""
    out = []
    for label, d in RACE_DISTANCES.items():
        t = riegel_predict(distance_m, time_s, d)
        if t:
            out.append({
                "label": label, "distance_m": d, "time_s": t,
                "pace_s_km": round(t / (d / 1000.0), 1),
            })
    return out


def running_economy(vo2max: float, vvo2max_ms: float) -> float | None:
    """Économie de course : ml O2 par kg et par km à VMA."""
    if not vo2max or not vvo2max_ms or vvo2max_ms <= 0:
        return None
    return round(vo2max / (vvo2max_ms * 60 / 1000.0), 1)


# ------------------------------------------------------ mécanique de foulée
def stride_length(speed_ms: float | None, cadence_spm: float | None) -> float | None:
    """Longueur de foulée (m). ``cadence_spm`` en pas par minute (2 jambes)."""
    if not speed_ms or not cadence_spm or cadence_spm <= 0:
        return None
    return round(speed_ms * 60.0 / cadence_spm, 3)


def vertical_ratio(vertical_oscillation_cm: float | None,
                   stride_len_m: float | None) -> float | None:
    """Ratio vertical (%) : oscillation verticale / longueur de foulée.
    Plus il est bas, plus la foulée est économique (< 7 % : très bon)."""
    if not vertical_oscillation_cm or not stride_len_m or stride_len_m <= 0:
        return None
    return round(100.0 * (vertical_oscillation_cm / 100.0) / stride_len_m, 2)
