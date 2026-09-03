"""Quantification de la charge d'entraînement.

Modèles implémentés
-------------------
* **TRIMP de Banister** (1991) — pondération exponentielle de la réserve de FC,
  coefficients distincts hommes / femmes.
* **TRIMP d'Edwards** (1993) — somme pondérée du temps en 5 zones de FC.
* **TRIMP de Lucía** (2003) — 3 zones délimitées par LT1 et LT2.
* **TSS** (Coggan) — Training Stress Score à partir de la puissance normalisée.
* **hrTSS** — TSS estimé depuis la FC, normalisé pour qu'une heure au seuil
  lactique vaille exactement 100 points chez chaque athlète.
* **rTSS / sTSS** — équivalents course à pied et natation, basés sur l'allure
  normalisée rapportée à l'allure seuil.
* **sRPE de Foster** (2001) — RPE (CR-10) × durée en minutes.

Toutes les fonctions sont tolérantes aux données manquantes et renvoient
``None`` plutôt que de lever, afin de pouvoir être chaînées sur des séances
partiellement instrumentées.
"""
from __future__ import annotations

import math
from typing import Sequence

# ------------------------------------------------------------------- TRIMP
BANISTER_B = {"M": 1.92, "F": 1.67, "X": 1.80}
BANISTER_A = {"M": 0.64, "F": 0.86, "X": 0.75}


def hr_reserve_ratio(hr: float, hr_rest: float, hr_max: float) -> float | None:
    """Fraction de réserve de FC, bornée à [0, 1]."""
    if None in (hr, hr_rest, hr_max) or hr_max <= hr_rest:
        return None
    return max(0.0, min(1.0, (hr - hr_rest) / (hr_max - hr_rest)))


def trimp_banister(duration_s: float, avg_hr: float, hr_rest: float,
                   hr_max: float, sex: str = "X") -> float | None:
    """TRIMP de Banister à partir de la FC moyenne.

        TRIMP = t(min) · Δ · a · e^(b·Δ)     avec Δ = réserve de FC

    Sensible à la FC moyenne : préférer :func:`trimp_banister_series` dès
    qu'un flux de FC est disponible (l'exponentielle n'est pas linéaire).
    """
    x = hr_reserve_ratio(avg_hr, hr_rest, hr_max)
    if x is None or not duration_s:
        return None
    a = BANISTER_A.get(sex, 0.75)
    b = BANISTER_B.get(sex, 1.80)
    return round((duration_s / 60.0) * x * a * math.exp(b * x), 2)


def trimp_banister_series(hr_series: Sequence[float | None], hr_rest: float,
                          hr_max: float, sex: str = "X",
                          sample_rate: float = 1.0) -> float | None:
    """TRIMP de Banister intégré échantillon par échantillon (plus exact)."""
    if not hr_series or hr_max is None or hr_rest is None or hr_max <= hr_rest:
        return None
    a = BANISTER_A.get(sex, 0.75)
    b = BANISTER_B.get(sex, 1.80)
    dt_min = (1.0 / sample_rate) / 60.0 if sample_rate else 1 / 60.0
    total = 0.0
    span = hr_max - hr_rest
    for hr in hr_series:
        if hr is None:
            continue
        x = (hr - hr_rest) / span
        if x <= 0:
            continue
        x = min(1.0, x)
        total += dt_min * x * a * math.exp(b * x)
    return round(total, 2)


EDWARDS_WEIGHTS = (1, 2, 3, 4, 5)


def trimp_edwards(zone_seconds: Sequence[float]) -> float | None:
    """TRIMP d'Edwards : Σ (minutes en zone i × i), zones à 50-60-70-80-90 % FCmax."""
    if not zone_seconds:
        return None
    total = 0.0
    for i, sec in enumerate(zone_seconds[:5]):
        total += (sec / 60.0) * EDWARDS_WEIGHTS[i]
    return round(total, 2)


def trimp_lucia(zone_seconds_3: Sequence[float]) -> float | None:
    """TRIMP de Lucía : minutes en Z1×1 + Z2×2 + Z3×3 (zones LT1/LT2)."""
    if not zone_seconds_3 or len(zone_seconds_3) < 3:
        return None
    z1, z2, z3 = zone_seconds_3[:3]
    return round((z1 / 60) * 1 + (z2 / 60) * 2 + (z3 / 60) * 3, 2)


# --------------------------------------------------------------------- TSS
def tss(duration_s: float, np_w: float, ftp_w: float) -> float | None:
    """Training Stress Score (Coggan).

        TSS = (t · NP · IF) / (FTP · 3600) · 100 = t(h) · IF² · 100

    Par construction, une heure exactement à la FTP vaut 100 points.
    """
    if not (duration_s and np_w and ftp_w) or ftp_w <= 0:
        return None
    intensity = np_w / ftp_w
    return round((duration_s * np_w * intensity) / (ftp_w * 3600.0) * 100.0, 1)


def intensity_factor(np_w: float, ftp_w: float) -> float | None:
    if not (np_w and ftp_w) or ftp_w <= 0:
        return None
    return round(np_w / ftp_w, 3)


def hrtss(duration_s: float, hr_series: Sequence[float | None] | None,
          avg_hr: float | None, hr_rest: float, hr_max: float, lthr: float,
          sex: str = "X", sample_rate: float = 1.0) -> float | None:
    """TSS estimé à partir de la fréquence cardiaque.

    On calcule le TRIMP de la séance puis on le rapporte au TRIMP d'une heure
    passée exactement à la FC du seuil lactique. L'échelle est donc identique
    à celle du TSS : 1 h au seuil = 100, quel que soit le profil de l'athlète.
    """
    if not (hr_rest and hr_max and lthr) or hr_max <= hr_rest:
        return None
    reference = trimp_banister(3600, lthr, hr_rest, hr_max, sex)
    if not reference:
        return None
    if hr_series:
        session = trimp_banister_series(hr_series, hr_rest, hr_max, sex, sample_rate)
    else:
        session = trimp_banister(duration_s, avg_hr, hr_rest, hr_max, sex)
    if session is None:
        return None
    return round(100.0 * session / reference, 1)


def rtss(duration_s: float, ngp_speed_ms: float, threshold_speed_ms: float) -> float | None:
    """running TSS : allure normalisée rapportée à la vitesse seuil.

    Identique au TSS mais l'« intensité » est un rapport de vitesses ;
    1 h à l'allure seuil = 100 points.
    """
    if not (duration_s and ngp_speed_ms and threshold_speed_ms) or threshold_speed_ms <= 0:
        return None
    intensity = ngp_speed_ms / threshold_speed_ms
    return round((duration_s / 3600.0) * intensity ** 2 * 100.0, 1)


def stss(duration_s: float, avg_speed_ms: float, threshold_speed_ms: float) -> float | None:
    """swim TSS. L'exposant 3 rend compte de la traînée hydrodynamique."""
    if not (duration_s and avg_speed_ms and threshold_speed_ms) or threshold_speed_ms <= 0:
        return None
    intensity = avg_speed_ms / threshold_speed_ms
    return round((duration_s / 3600.0) * intensity ** 3 * 100.0, 1)


def session_rpe(duration_s: float, rpe: float) -> float | None:
    """Charge sRPE de Foster : RPE (CR-10) × durée en minutes (unités arbitraires)."""
    if not duration_s or rpe is None:
        return None
    return round((duration_s / 60.0) * rpe, 1)


def rpe_to_tss_equivalent(duration_s: float, rpe: float) -> float | None:
    """Conversion approchée sRPE → échelle TSS (÷ 6,5), pour homogénéiser
    la charge des séances non instrumentées (musculation, sports collectifs)."""
    load = session_rpe(duration_s, rpe)
    return None if load is None else round(load / 6.5, 1)


# ------------------------------------------------------- charge consolidée
LOAD_PRIORITY = ("tss", "rtss", "stss", "hrtss", "rpe")


def best_load(*, tss_v=None, rtss_v=None, stss_v=None, hrtss_v=None,
              rpe_v=None, sport: str = "") -> tuple[float | None, str | None]:
    """Choisit la meilleure estimation de charge disponible.

    Ordre de préférence : mesure la plus directe d'abord (puissance), puis
    allure, puis fréquence cardiaque, puis ressenti. Pour la course à pied on
    privilégie le rTSS sur le TSS de puissance, les capteurs de puissance de
    running restant peu comparables entre marques.
    """
    order = list(LOAD_PRIORITY)
    if sport in ("running", "trail_running"):
        order = ["rtss", "tss", "hrtss", "rpe"]
    elif sport == "swimming":
        order = ["stss", "hrtss", "rpe"]
    values = {"tss": tss_v, "rtss": rtss_v, "stss": stss_v,
              "hrtss": hrtss_v, "rpe": rpe_v}
    for key in order:
        v = values.get(key)
        if v is not None and v > 0:
            return round(float(v), 1), key
    return None, None
