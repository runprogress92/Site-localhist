"""Score de disponibilité (readiness) — agrégation multi-signaux.

Il n'existe pas de standard consensuel : on construit ici un score 0–100
transparent et auditable, moyenne pondérée de sous-scores normalisés, dont
chaque contribution est renvoyée pour que l'entraîneur puisse voir *ce qui*
fait monter ou descendre le score plutôt qu'un chiffre opaque.

Composantes et pondérations par défaut
--------------------------------------
    VFC (écart à la ligne de base)          30 %
    FC de repos (écart à la ligne de base)  15 %
    Sommeil (durée + qualité)               20 %
    Ressenti subjectif (Hooper-Mackinnon)   20 %
    Bilan de charge (TSB / ACWR)            15 %

Les composantes absentes sont ignorées et les poids renormalisés : le score
reste calculable avec une simple mesure de VFC ou un simple questionnaire.
"""
from __future__ import annotations

DEFAULT_WEIGHTS = {
    "hrv": 0.30, "rhr": 0.15, "sleep": 0.20,
    "subjective": 0.20, "load": 0.15,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def hrv_subscore(ln_today: float | None, baseline: float | None,
                 sd: float | None) -> float | None:
    """50 = ligne de base ; ±1 écart-type ≈ ±25 points."""
    if ln_today is None or baseline is None or not sd:
        return None
    z = (ln_today - baseline) / sd
    return _clamp(50 + 25 * z)


def rhr_subscore(rhr: float | None, baseline: float | None) -> float | None:
    """−1 bpm sous la base = +7 points ; +1 bpm au-dessus = −7 points."""
    if rhr is None or baseline is None:
        return None
    return _clamp(50 - 7.0 * (rhr - baseline))


def sleep_subscore(total_min: float | None, quality_1_7: float | None,
                   need_min: float = 480) -> float | None:
    """Combine dette de sommeil (⅔) et qualité déclarée (⅓)."""
    parts, weights = [], []
    if total_min is not None:
        ratio = total_min / need_min
        parts.append(_clamp(100 * min(1.15, ratio) / 1.05))
        weights.append(2.0)
    if quality_1_7 is not None:
        # échelle Hooper : 1 = très bon, 7 = très mauvais
        parts.append(_clamp(100 * (7 - quality_1_7) / 6))
        weights.append(1.0)
    if not parts:
        return None
    return sum(p * w for p, w in zip(parts, weights)) / sum(weights)


def hooper_index(fatigue, soreness, mood, stress, sleep_quality) -> float | None:
    """Indice de Hooper-Mackinnon : somme de 4 items 1–7 (5 à 28 ; bas = bon).
    Le sommeil est compté ici pour rester fidèle à l'index original à 4 items
    (sommeil, fatigue, douleurs, stress) ; l'humeur est ajoutée en bonus."""
    items = [v for v in (fatigue, soreness, stress, sleep_quality) if v is not None]
    if len(items) < 3:
        return None
    scaled = sum(items) * 4 / len(items)     # ramené à 4 items
    return round(scaled, 1)


def subjective_subscore(fatigue=None, soreness=None, mood=None,
                        stress=None, motivation=None) -> float | None:
    """Moyenne des items déclaratifs, retournée sur 100 (haut = bon)."""
    items = [v for v in (fatigue, soreness, mood, stress, motivation) if v is not None]
    if not items:
        return None
    mean = sum(items) / len(items)
    return _clamp(100 * (7 - mean) / 6)


def load_subscore(tsb: float | None, acwr: float | None) -> float | None:
    """Pénalise la fatigue résiduelle (TSB très négatif) et les ratios extrêmes."""
    parts = []
    if tsb is not None:
        # TSB −40 → 10 ; TSB 0 → 65 ; TSB +25 → 90
        parts.append(_clamp(65 + tsb * 1.15))
    if acwr is not None:
        if acwr <= 1.30:
            parts.append(_clamp(100 - max(0.0, 0.80 - acwr) * 100))
        else:
            parts.append(_clamp(100 - (acwr - 1.30) * 130))
    if not parts:
        return None
    return sum(parts) / len(parts)


def readiness(*, ln_rmssd=None, hrv_baseline=None, hrv_sd=None,
              rhr=None, rhr_baseline=None,
              sleep_min=None, sleep_quality=None,
              fatigue=None, soreness=None, mood=None, stress=None, motivation=None,
              tsb=None, acwr=None, weights: dict | None = None) -> dict:
    """Score global 0–100 + détail des contributions."""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)
    subs = {
        "hrv": hrv_subscore(ln_rmssd, hrv_baseline, hrv_sd),
        "rhr": rhr_subscore(rhr, rhr_baseline),
        "sleep": sleep_subscore(sleep_min, sleep_quality),
        "subjective": subjective_subscore(fatigue, soreness, mood, stress, motivation),
        "load": load_subscore(tsb, acwr),
    }
    available = {k: v for k, v in subs.items() if v is not None}
    if not available:
        return {"score": None, "flag": "inconnu", "components": subs,
                "coverage": 0.0, "advice": "Aucune donnée disponible ce jour."}

    total_w = sum(w[k] for k in available)
    score = sum(v * w[k] for k, v in available.items()) / total_w
    coverage = round(total_w / sum(w.values()), 2)

    if score >= 70:
        flag, advice = "vert", ("Organisme disponible : séance planifiée "
                                "réalisable telle quelle, y compris en intensité.")
    elif score >= 50:
        flag, advice = "ambre", ("Disponibilité moyenne : conserver la séance mais "
                                 "réduire le volume ou l'intensité de 10 à 20 %, "
                                 "et réévaluer à l'échauffement.")
    else:
        flag, advice = "rouge", ("Disponibilité faible : remplacer par de la "
                                 "récupération active ou du repos. Une séance "
                                 "intense aujourd'hui coûtera plus qu'elle "
                                 "n'apportera.")
    return {
        "score": round(score, 1),
        "flag": flag,
        "advice": advice,
        "coverage": coverage,
        "components": {k: (round(v, 1) if v is not None else None) for k, v in subs.items()},
        "weights": {k: w[k] for k in w},
        "drivers": sorted(
            [{"key": k, "value": round(v, 1), "impact": round((v - 50) * w[k], 2)}
             for k, v in available.items()],
            key=lambda d: d["impact"],
        ),
    }
