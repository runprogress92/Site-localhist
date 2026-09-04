"""Performance Management Chart et indicateurs de charge longitudinaux.

Modèle à impulsions-réponses de Banister (1975), popularisé sous le nom de
PMC par TrainingPeaks :

    CTL(j) = CTL(j−1) + (charge(j) − CTL(j−1)) · (1 − e^(−1/τc)),  τc = 42 j
    ATL(j) = ATL(j−1) + (charge(j) − ATL(j−1)) · (1 − e^(−1/τa)),  τa = 7 j
    TSB(j) = CTL(j−1) − ATL(j−1)          ← décalage d'un jour (convention TP)

S'y ajoutent :
* **ACWR** — ratio charge aiguë / charge chronique, en moyennes glissantes
  (Gabbett 2016) et en moyennes exponentielles (Williams et al. 2017), cette
  seconde forme étant plus sensible aux pics récents.
* **Monotonie et contrainte** de Foster (1998) :
  monotonie = charge moyenne / écart-type sur 7 jours ; contrainte = charge
  hebdomadaire × monotonie.
* **Rampe de CTL** — variation de CTL sur 7 jours, indicateur de la vitesse
  de progression de la charge.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Sequence

CTL_TAU = 42.0
ATL_TAU = 7.0

# Zones de forme (TSB) — repères praticiens
FORM_STATES = [
    (25, "affûté", "Fraîcheur maximale : fenêtre de performance, mais la "
                   "condition commence à se perdre au-delà de ~3 semaines."),
    (5, "frais", "Bon compromis fraîcheur / condition."),
    (-10, "neutre", "Charge et récupération à l'équilibre."),
    (-30, "productif", "Zone de construction : fatigue assumée, adaptation en cours."),
    (-999, "surcharge", "Fatigue élevée : à ne tenir que quelques jours."),
]


def form_state(tsb: float | None) -> tuple[str, str]:
    if tsb is None:
        return ("inconnu", "Données insuffisantes.")
    for threshold, label, advice in FORM_STATES:
        if tsb >= threshold:
            return (label, advice)
    return ("surcharge", "Fatigue élevée.")


def ewma_series(values: Sequence[float], tau: float, seed: float = 0.0) -> list[float]:
    """Moyenne exponentielle de constante ``tau`` jours."""
    alpha = 1 - math.exp(-1.0 / tau)
    out: list[float] = []
    prev = seed
    for v in values:
        prev = prev + (v - prev) * alpha
        out.append(prev)
    return out


def rolling_mean_window(values: Sequence[float], window: int) -> list[float | None]:
    """Moyenne glissante sur ``window`` jours (None tant que la fenêtre est
    incomplète, pour ne pas afficher de valeur non fondée)."""
    out: list[float | None] = []
    acc = 0.0
    for i, v in enumerate(values):
        acc += v
        if i >= window:
            acc -= values[i - window]
        out.append(acc / window if i >= window - 1 else None)
    return out


def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def compute_pmc(daily: dict[str, float], start: date, end: date,
                seed_ctl: float = 0.0, seed_atl: float = 0.0) -> list[dict]:
    """Calcule la série PMC complète.

    ``daily`` : {'YYYY-MM-DD': charge}. Les jours absents valent 0 (repos),
    ce qui est essentiel : sauter les jours sans séance fausserait les
    constantes de temps.
    """
    days = daterange(start, end)
    keys = [d.isoformat() for d in days]
    loads = [float(daily.get(k, 0.0) or 0.0) for k in keys]

    ctl_prev, atl_prev = seed_ctl, seed_atl
    a_ctl = 1 - math.exp(-1.0 / CTL_TAU)
    a_atl = 1 - math.exp(-1.0 / ATL_TAU)

    ctl_list: list[float] = []
    atl_list: list[float] = []
    tsb_list: list[float] = []
    for load in loads:
        # TSB du jour = état d'hier : la séance du jour n'a pas encore fatigué
        tsb_list.append(ctl_prev - atl_prev)
        ctl_prev = ctl_prev + (load - ctl_prev) * a_ctl
        atl_prev = atl_prev + (load - atl_prev) * a_atl
        ctl_list.append(ctl_prev)
        atl_list.append(atl_prev)

    # ACWR — moyennes glissantes 7 j / 28 j
    acute_r = rolling_mean_window(loads, 7)
    chronic_r = rolling_mean_window(loads, 28)
    # ACWR — moyennes exponentielles (Williams 2017)
    acute_e = ewma_series(loads, 7.0, seed=seed_atl)
    chronic_e = ewma_series(loads, 28.0, seed=seed_ctl)

    out: list[dict] = []
    for i, k in enumerate(keys):
        seven = loads[max(0, i - 6):i + 1]
        mean7 = statistics.fmean(seven) if seven else 0.0
        sd7 = statistics.pstdev(seven) if len(seven) > 1 else 0.0
        monotony = round(mean7 / sd7, 2) if sd7 > 0.01 else None
        weekly = sum(seven)
        strain = round(weekly * monotony, 0) if monotony else None

        acwr_r = (round(acute_r[i] / chronic_r[i], 3)
                  if acute_r[i] is not None and chronic_r[i] and chronic_r[i] > 1 else None)
        acwr_e = (round(acute_e[i] / chronic_e[i], 3)
                  if chronic_e[i] and chronic_e[i] > 1 else None)
        ramp = round(ctl_list[i] - ctl_list[i - 7], 2) if i >= 7 else None

        out.append({
            "date": k,
            "load": round(loads[i], 1),
            "ctl": round(ctl_list[i], 2),
            "atl": round(atl_list[i], 2),
            "tsb": round(tsb_list[i], 2),
            "ctl_ramp_7d": ramp,
            "acwr_rolling": acwr_r,
            "acwr_ewma": acwr_e,
            "monotony": monotony,
            "strain": strain,
            "weekly_load": round(weekly, 1),
            "form": form_state(tsb_list[i])[0],
        })
    return out


def project_forward(ctl: float, atl: float, planned: Sequence[float]) -> list[dict]:
    """Projette CTL/ATL/TSB sur les charges planifiées à venir.

    Permet de vérifier qu'un affûtage amène bien le TSB dans la fenêtre
    visée le jour de l'objectif.
    """
    a_ctl = 1 - math.exp(-1.0 / CTL_TAU)
    a_atl = 1 - math.exp(-1.0 / ATL_TAU)
    out = []
    for load in planned:
        tsb = ctl - atl
        ctl = ctl + (load - ctl) * a_ctl
        atl = atl + (load - atl) * a_atl
        out.append({"load": round(load, 1), "ctl": round(ctl, 2),
                    "atl": round(atl, 2), "tsb": round(tsb, 2),
                    "form": form_state(tsb)[0]})
    return out


def taper_plan(ctl: float, atl: float, days: int = 14,
               target_tsb: float = 15.0, taper_days: int | None = None) -> list[float]:
    """Construit une trajectoire de charge qui amène le TSB à la cible le jour J.

    Un affûtage n'occupe que les deux ou trois dernières semaines : au-delà,
    la charge doit être *maintenue*, sinon la condition (CTL) se perd bien
    avant l'échéance. La trajectoire comporte donc deux segments :

    * un **maintien** à hauteur de CTL, qui laisse le niveau de forme stable ;
    * un **affûtage** de ``taper_days`` jours à charge réduite, dont le
      coefficient est recherché par dichotomie pour atteindre exactement le
      TSB visé le dernier jour.

    Bosquet et al. (2007) situent l'affûtage optimal entre 8 et 14 jours,
    avec une réduction de volume de 40 à 60 %.
    """
    if days <= 0:
        return []
    taper_days = min(days, taper_days if taper_days is not None else 14)
    hold_days = days - taper_days

    lo, hi = 0.0, 1.5
    best: list[float] = []
    for _ in range(50):
        mid = (lo + hi) / 2
        loads = [ctl] * hold_days + [ctl * mid] * taper_days
        final_tsb = project_forward(ctl, atl, loads)[-1]["tsb"]
        best = loads
        if final_tsb < target_tsb:
            hi = mid          # encore trop de charge → réduire
        else:
            lo = mid
    return [round(v, 1) for v in best]


# ------------------------------------------------------- seuils praticiens
ACWR_SWEET_SPOT = (0.80, 1.30)
ACWR_DANGER = 1.50
MONOTONY_WARN = 2.0
STRAIN_WARN = 6000
RAMP_WARN = 8.0        # points de CTL par semaine


def interpret_acwr(acwr: float | None) -> tuple[str, str]:
    if acwr is None:
        return ("inconnu", "Historique insuffisant (28 jours requis).")
    if acwr < 0.80:
        return ("sous-charge", "Charge aiguë faible devant la charge chronique : "
                               "désentraînement possible si cela se prolonge.")
    if acwr <= 1.30:
        return ("optimal", "Zone d'équilibre : progression sans surcharge marquée.")
    if acwr <= 1.50:
        return ("vigilance", "Progression rapide de la charge — surveiller le ressenti.")
    return ("risque élevé", "Ratio > 1,50 : risque de blessure de surcharge "
                            "significativement accru dans les 7 à 14 jours.")
