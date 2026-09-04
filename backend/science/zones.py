"""Modèles de zones d'intensité.

Références :
  * Coggan A. & Allen H. — *Training and Racing with a Power Meter* (zones
    puissance en % de FTP, 7 zones).
  * Friel J. — *The Cyclist's / Triathlete's Training Bible* (zones FC en
    % de la FC au seuil lactique, LTHR).
  * Karvonen M. (1957) — méthode de la réserve de fréquence cardiaque.
  * Seiler S. (2010) — modèle 3 zones utilisé pour l'analyse polarisée.
  * Daniels J. — *Daniels' Running Formula* (zones d'allure).

Chaque modèle renvoie une liste de zones ordonnées, bornes incluses en bas
et exclues en haut. La dernière zone a `high = None` (infini).
"""
from __future__ import annotations

from typing import Sequence

# Palette partagée avec le front (frontend/css/tokens.css : --z1..--z7)
ZONE_COLORS = [
    "#5b8fd6",  # Z1 gris-bleu — récupération
    "#3fb98c",  # Z2 vert — endurance fondamentale
    "#c9c04a",  # Z3 jaune — tempo
    "#e08d3c",  # Z4 orange — seuil
    "#d8543f",  # Z5 rouge — VO2max
    "#b1418b",  # Z6 magenta — capacité anaérobie
    "#7b56c9",  # Z7 violet — neuromusculaire
]


class Zone(dict):
    """Zone = dict sérialisable (idx, name, low, high, color, purpose)."""

    def contains(self, value: float) -> bool:
        if value is None:
            return False
        if self["low"] is not None and value < self["low"]:
            return False
        if self["high"] is not None and value >= self["high"]:
            return False
        return True


def _build(kind: str, basis: float, spec: Sequence[tuple], invert: bool = False) -> list[Zone]:
    """Construit les zones depuis une spec (nom, court, %bas, %haut, but)."""
    zones: list[Zone] = []
    for i, (name, short, lo_pct, hi_pct, purpose) in enumerate(spec, start=1):
        lo = None if lo_pct is None else round(basis * lo_pct, 2)
        hi = None if hi_pct is None else round(basis * hi_pct, 2)
        if invert:  # allures : un % plus élevé = une vitesse plus lente
            lo, hi = hi, lo
        zones.append(Zone(
            idx=i, name=name, short_name=short, low=lo, high=hi,
            low_pct=None if lo_pct is None else round(lo_pct * 100, 1),
            high_pct=None if hi_pct is None else round(hi_pct * 100, 1),
            color=ZONE_COLORS[min(i - 1, len(ZONE_COLORS) - 1)],
            purpose=purpose, kind=kind,
        ))
    return zones


# ---------------------------------------------------------------- puissance
COGGAN_SPEC = [
    ("Récupération active", "Z1", None, 0.55, "Circulation, régénération"),
    ("Endurance",           "Z2", 0.55, 0.76, "Oxydation lipidique, capillarisation"),
    ("Tempo",               "Z3", 0.76, 0.91, "Endurance musculaire, glycogène"),
    ("Seuil",               "Z4", 0.91, 1.06, "Puissance au seuil fonctionnel"),
    ("VO2max",              "Z5", 1.06, 1.21, "Consommation maximale d'oxygène"),
    ("Capacité anaérobie",  "Z6", 1.21, 1.50, "Glycolyse, tolérance lactique"),
    ("Neuromusculaire",     "Z7", 1.50, None, "Force-vitesse, recrutement"),
]


def power_zones(ftp: float, model: str = "coggan") -> list[Zone]:
    """Zones de puissance en watts à partir de la FTP (ou CP)."""
    if not ftp or ftp <= 0:
        return []
    return _build("power", ftp, COGGAN_SPEC)


# ------------------------------------------------------------ fréquence card.
FRIEL_LTHR_SPEC = [
    ("Récupération", "Z1", None, 0.85, "Récupération active"),
    ("Endurance",    "Z2", 0.85, 0.90, "Base aérobie"),
    ("Tempo",        "Z3", 0.90, 0.95, "Endurance musculaire"),
    ("Sous-seuil",   "Z4", 0.95, 1.00, "Seuil lactique bas"),
    ("Sur-seuil",    "Z5a", 1.00, 1.03, "Seuil lactique haut"),
    ("VO2max",       "Z5b", 1.03, 1.06, "Puissance aérobie maximale"),
    ("Anaérobie",    "Z5c", 1.06, None, "Capacité anaérobie"),
]

HRMAX_SPEC = [
    ("Récupération", "Z1", None, 0.60, "Récupération active"),
    ("Endurance",    "Z2", 0.60, 0.70, "Base aérobie, Fatmax"),
    ("Tempo",        "Z3", 0.70, 0.80, "Endurance active"),
    ("Seuil",        "Z4", 0.80, 0.90, "Seuil anaérobie"),
    ("VO2max",       "Z5", 0.90, None, "Puissance aérobie maximale"),
]

SEILER3_SPEC = [
    ("Zone 1 — sous-LT1", "Z1", None, 0.82, "Volume aérobie, base polarisée"),
    ("Zone 2 — LT1↔LT2",  "Z2", 0.82, 0.92, "Zone « grise » / seuil"),
    ("Zone 3 — sur-LT2",  "Z3", 0.92, None, "Haute intensité"),
]


def hr_zones(model: str = "friel_lthr", *, lthr: float | None = None,
             hr_max: float | None = None, hr_rest: float | None = None) -> list[Zone]:
    """Zones de FC en bpm.

    model :
      * ``friel_lthr``  — % de la FC au seuil (recommandé si LTHR connue)
      * ``hrmax``       — % de la FC maximale
      * ``karvonen``    — % de la réserve de FC : FC = FCrepos + %·(FCmax−FCrepos)
      * ``seiler3``     — 3 zones basées sur LT1/LT2 (analyse polarisée)
    """
    if model == "friel_lthr" and lthr:
        return _build("hr", lthr, FRIEL_LTHR_SPEC)
    if model == "seiler3":
        base = lthr or (hr_max * 0.9 if hr_max else None)
        if not base:
            return []
        return _build("hr", base, SEILER3_SPEC)
    if model == "karvonen" and hr_max and hr_rest:
        hrr = hr_max - hr_rest
        zones = _build("hr", hrr, HRMAX_SPEC)
        for z in zones:              # décalage par la FC de repos
            if z["low"] is not None:
                z["low"] = round(z["low"] + hr_rest, 1)
            if z["high"] is not None:
                z["high"] = round(z["high"] + hr_rest, 1)
        return zones
    if hr_max:
        return _build("hr", hr_max, HRMAX_SPEC)
    return []


# ----------------------------------------------------------------- allures
# Bornes exprimées en % de la vitesse au seuil (pas de l'allure) :
# on travaille en m/s puis on convertit.
PACE_SPEC = [
    ("Récupération",  "Z1", None, 0.78, "Footing très léger"),
    ("Endurance",     "Z2", 0.78, 0.88, "Endurance fondamentale"),
    ("Marathon",      "Z3", 0.88, 0.95, "Allure marathon / tempo"),
    ("Seuil",         "Z4", 0.95, 1.02, "Allure semi / seuil"),
    ("VO2max",        "Z5", 1.02, 1.12, "Allure 3 000–5 000 m"),
    ("Anaérobie",     "Z6", 1.12, 1.30, "Allure 800–1 500 m"),
    ("Sprint",        "Z7", 1.30, None, "Vitesse maximale"),
]


def pace_zones(threshold_speed_ms: float) -> list[Zone]:
    """Zones d'allure exprimées en vitesse (m/s), croissantes."""
    if not threshold_speed_ms or threshold_speed_ms <= 0:
        return []
    return _build("pace", threshold_speed_ms, PACE_SPEC)


# ------------------------------------------------------------- répartition
def time_in_zones(values: Sequence[float | None], zones: Sequence[dict],
                  sample_rate: float = 1.0) -> list[float]:
    """Temps passé (s) dans chaque zone pour une série d'échantillons.

    Lorsque les zones sont contiguës — ce que garantissent tous les modèles
    de ce module — la zone d'un échantillon s'obtient par recherche
    dichotomique sur les bornes hautes, en une opération au lieu d'un
    parcours de toutes les zones. Sur une séance de trois heures à 1 Hz,
    cela divise le coût par cinq. Le parcours général reste utilisé pour des
    zones quelconques (chevauchantes ou avec des trous).
    """
    import bisect
    from collections import Counter

    seconds = [0.0] * len(zones)
    if not zones:
        return seconds
    dt = 1.0 / sample_rate if sample_rate else 1.0
    lows = [z["low"] for z in zones]
    highs = [z["high"] for z in zones]

    contiguous = (lows[0] is None and highs[-1] is None
                  and all(highs[i] is not None and highs[i] == lows[i + 1]
                          for i in range(len(zones) - 1)))
    if contiguous:
        bounds = highs[:-1]
        counts = Counter(bisect.bisect_right(bounds, v)
                         for v in values if v is not None)
        for index, count in counts.items():
            seconds[index] += count * dt
        return seconds

    for v in values:
        if v is None:
            continue
        for i in range(len(zones)):
            lo, hi = lows[i], highs[i]
            if (lo is None or v >= lo) and (hi is None or v < hi):
                seconds[i] += dt
                break
    return seconds


def zone_distribution(seconds: Sequence[float]) -> list[float]:
    total = sum(seconds)
    if total <= 0:
        return [0.0] * len(seconds)
    return [round(100 * s / total, 2) for s in seconds]


def polarization_index(z1_s: float, z2_s: float, z3_s: float) -> float | None:
    """Indice de polarisation (Treff et al., 2019).

        PI = log10( (Z1 × Z3 × 100) / Z2² )   sur les *pourcentages* de temps.

    PI > 2.00 ⇒ distribution réellement polarisée.
    """
    total = z1_s + z2_s + z3_s
    if total <= 0 or z2_s <= 0 or z3_s <= 0 or z1_s <= 0:
        return None
    import math
    p1, p2, p3 = (100 * z1_s / total, 100 * z2_s / total, 100 * z3_s / total)
    return round(math.log10((p1 * p3 * 100) / (p2 ** 2)), 3)


def classify_session(dist3: Sequence[float]) -> str:
    """Classe une séance à partir de sa répartition en 3 zones (%)."""
    z1, z2, z3 = dist3
    if z3 >= 15:
        return "haute intensité"
    if z2 >= 25:
        return "seuil / tempo"
    if z1 >= 80:
        return "endurance"
    return "mixte"
