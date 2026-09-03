"""Variabilité de la fréquence cardiaque (VFC / HRV).

Indices temporels calculés depuis les intervalles RR :
* **RMSSD** — racine de la moyenne des carrés des différences successives ;
  reflète l'activité parasympathique (vagale), indice de référence pour le
  suivi quotidien sur mesure courte (1 à 5 min).
* **SDNN** — écart-type des intervalles NN (variabilité globale).
* **pNN50** — proportion de différences successives > 50 ms.
* **ln(RMSSD)** — transformation logarithmique, utilisée pour le suivi car
  elle normalise la distribution (fortement asymétrique) du RMSSD.

Méthodologie de suivi (Plews, Laursen, Buchheit) :
* travailler sur la **moyenne glissante 7 jours** de ln(RMSSD), pas sur la
  valeur du jour, trop bruitée ;
* comparer à une **plage normale** = moyenne 60 j ± 0,5 × écart-type
  (« smallest worthwhile change ») ;
* surveiller le **coefficient de variation** de ln(RMSSD) sur 7 jours : sa
  hausse précède souvent la baisse de la moyenne et signale un stress
  d'accumulation.
"""
from __future__ import annotations

import math
import statistics
from typing import Sequence


def rmssd(rr_ms: Sequence[float]) -> float | None:
    """RMSSD en millisecondes à partir des intervalles RR."""
    rr = [v for v in rr_ms if v and 300 < v < 2000]
    if len(rr) < 10:
        return None
    diffs = [rr[i + 1] - rr[i] for i in range(len(rr) - 1)]
    return round(math.sqrt(sum(d * d for d in diffs) / len(diffs)), 1)


def sdnn(rr_ms: Sequence[float]) -> float | None:
    rr = [v for v in rr_ms if v and 300 < v < 2000]
    if len(rr) < 10:
        return None
    return round(statistics.pstdev(rr), 1)


def pnn50(rr_ms: Sequence[float]) -> float | None:
    rr = [v for v in rr_ms if v and 300 < v < 2000]
    if len(rr) < 10:
        return None
    diffs = [abs(rr[i + 1] - rr[i]) for i in range(len(rr) - 1)]
    return round(100.0 * sum(1 for d in diffs if d > 50) / len(diffs), 1)


def ln_rmssd(rmssd_ms: float | None) -> float | None:
    if not rmssd_ms or rmssd_ms <= 0:
        return None
    return round(math.log(rmssd_ms), 3)


def artifact_correction(rr_ms: Sequence[float], threshold: float = 0.25) -> list[float]:
    """Filtre les battements ectopiques : tout RR s'écartant de plus de
    ``threshold`` (25 %) de la médiane locale est remplacé par elle."""
    rr = list(rr_ms)
    if len(rr) < 5:
        return rr
    out = []
    for i, v in enumerate(rr):
        window = rr[max(0, i - 2):i + 3]
        med = statistics.median(window)
        out.append(med if med > 0 and abs(v - med) / med > threshold else v)
    return out


def rolling_baseline(series: Sequence[float | None], window: int = 7) -> list[float | None]:
    """Moyenne glissante ignorant les trous (mesure manquée un jour donné)."""
    out: list[float | None] = []
    for i in range(len(series)):
        chunk = [v for v in series[max(0, i - window + 1):i + 1] if v is not None]
        out.append(round(statistics.fmean(chunk), 3) if len(chunk) >= max(3, window // 2) else None)
    return out


def normal_range(series: Sequence[float | None], window: int = 60,
                 k: float = 0.5) -> tuple[float | None, float | None, float | None]:
    """Plage normale : (borne basse, moyenne, borne haute) sur ``window`` jours."""
    chunk = [v for v in series[-window:] if v is not None]
    if len(chunk) < 10:
        return (None, None, None)
    mean = statistics.fmean(chunk)
    sd = statistics.pstdev(chunk)
    return (round(mean - k * sd, 3), round(mean, 3), round(mean + k * sd, 3))


def coefficient_of_variation(series: Sequence[float | None], window: int = 7) -> float | None:
    """CV de ln(RMSSD) en %, sur la fenêtre la plus récente."""
    chunk = [v for v in series[-window:] if v is not None]
    if len(chunk) < 4:
        return None
    mean = statistics.fmean(chunk)
    if mean == 0:
        return None
    return round(100.0 * statistics.pstdev(chunk) / abs(mean), 2)


def hrv_status(baseline_7d: float | None, low: float | None, high: float | None,
               cv: float | None = None, cv_baseline: float | None = None) -> dict:
    """Interprète la position de la moyenne 7 j dans la plage normale."""
    if baseline_7d is None or low is None or high is None:
        return {"status": "inconnu", "label": "Données insuffisantes",
                "advice": "Au moins 10 mesures sur 60 jours sont nécessaires "
                          "pour établir une plage de référence.", "level": 0}
    cv_rising = (cv is not None and cv_baseline is not None and cv > cv_baseline * 1.3)
    if baseline_7d < low:
        return {"status": "supprimée", "label": "VFC sous la plage normale",
                "advice": "Signature d'une fatigue accumulée, d'un stress non "
                          "entraînement ou d'un état infectieux débutant. "
                          "Réduire l'intensité 24 à 72 h.", "level": 3}
    if baseline_7d > high:
        return {"status": "élevée", "label": "VFC au-dessus de la plage normale",
                "advice": "Souvent une bonne nouvelle (fraîcheur retrouvée). "
                          "Une hausse conjuguée à une charge très élevée peut "
                          "aussi traduire une fatigue parasympathique — croiser "
                          "avec la FC de repos et le ressenti.", "level": 1}
    if cv_rising:
        return {"status": "instable", "label": "VFC normale mais instable",
                "advice": "La dispersion jour à jour augmente : signal précoce "
                          "d'un stress d'accumulation. Surveiller de près.", "level": 2}
    return {"status": "normale", "label": "VFC dans la plage normale",
            "advice": "Équilibre neurovégétatif préservé : la charge est absorbée.",
            "level": 0}


def rhr_deviation(current: float | None, baseline: float | None) -> dict | None:
    """Écart de FC de repos à la ligne de base (+5 bpm = signal d'alerte)."""
    if current is None or baseline is None:
        return None
    delta = current - baseline
    if delta >= 7:
        level, label = 3, "FC de repos nettement élevée"
    elif delta >= 4:
        level, label = 2, "FC de repos élevée"
    elif delta <= -4:
        level, label = 0, "FC de repos basse (bonne récupération)"
    else:
        level, label = 0, "FC de repos normale"
    return {"delta_bpm": round(delta, 1), "level": level, "label": label}
