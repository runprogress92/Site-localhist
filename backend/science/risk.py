"""Moteur d'alertes : détection de situations à risque.

Chaque règle est explicite, seuillée sur la littérature, et produit une
alerte horodatée. L'objectif est d'attirer l'œil de l'entraîneur, pas de
décider à sa place : chaque alerte porte son seuil et sa valeur observée.
"""
from __future__ import annotations

from typing import Sequence

from .pmc import ACWR_DANGER, MONOTONY_WARN, RAMP_WARN, STRAIN_WARN

# code, sévérité, titre, gabarit de message
RULES_DOC = {
    "acwr_high":     "Ratio charge aiguë:chronique au-dessus de 1,50",
    "acwr_low":      "Charge aiguë effondrée devant la charge chronique",
    "monotony_high": "Monotonie de l'entraînement supérieure à 2,0",
    "strain_high":   "Contrainte hebdomadaire (strain) très élevée",
    "ramp_high":     "Progression de CTL trop rapide",
    "tsb_low":       "Fatigue résiduelle prolongée (TSB très négatif)",
    "hrv_suppressed": "VFC durablement sous la plage normale",
    "rhr_elevated":  "FC de repos élevée plusieurs jours de suite",
    "sleep_debt":    "Dette de sommeil cumulée",
    "readiness_low": "Disponibilité faible répétée",
    "no_data":       "Absence de données récentes",
    "injury_open":   "Blessure en cours",
    "monotonous_week": "Semaine sans jour de repos",
}


def _fr(value: float, digits: int = 2) -> str:
    """Nombre écrit à la française : la virgule sépare les décimales.

    Les messages d'alerte sont lus tels quels par l'entraîneur ; un « 6.2 h »
    au milieu d'une phrase française dénote.
    """
    return f"{value:.{digits}f}".replace(".", ",")


def _alert(athlete_id, date, code, severity, title, message,
           metric=None, value=None, threshold=None) -> dict:
    return {
        "athlete_id": athlete_id, "date": date, "code": code,
        "severity": severity, "title": title, "message": message,
        "metric": metric,
        "value": round(value, 2) if isinstance(value, (int, float)) else value,
        "threshold": threshold,
    }


def evaluate(athlete: dict, pmc_rows: Sequence[dict], wellness_rows: Sequence[dict],
             injuries: Sequence[dict] = (), today: str | None = None) -> list[dict]:
    """Applique toutes les règles à l'état courant d'un athlète."""
    if not pmc_rows:
        return []
    aid = athlete["id"]
    last = pmc_rows[-1]
    day = today or last["date"]
    out: list[dict] = []

    # --- charge -------------------------------------------------------
    acwr = last.get("acwr_ewma") or last.get("acwr_rolling")
    if acwr is not None:
        if acwr > ACWR_DANGER:
            out.append(_alert(aid, day, "acwr_high", "critical",
                              "Ratio charge aiguë:chronique élevé",
                              f"ACWR à {_fr(acwr)} (seuil {_fr(ACWR_DANGER)}). "
                              "Au-delà de 1,50, l'incidence des blessures de "
                              "surcharge augmente nettement dans les 7 à 14 jours. "
                              "Stabiliser la charge une semaine avant toute nouvelle hausse.",
                              "acwr", acwr, ACWR_DANGER))
        elif acwr > 1.30:
            out.append(_alert(aid, day, "acwr_high", "warning",
                              "Charge en progression rapide",
                              f"ACWR à {_fr(acwr)} : au-dessus de la fenêtre "
                              "d'équilibre (0,80–1,30) sans être critique. "
                              "Surveiller le ressenti et la VFC.",
                              "acwr", acwr, 1.30))
        elif acwr < 0.80 and last["ctl"] > 25:
            out.append(_alert(aid, day, "acwr_low", "info",
                              "Charge aiguë en retrait",
                              f"ACWR à {_fr(acwr)} : la charge récente est très "
                              "inférieure à l'habitude. Normal en affûtage ou "
                              "après une compétition, à corriger sinon.",
                              "acwr", acwr, 0.80))

    if last.get("monotony") and last["monotony"] > MONOTONY_WARN:
        out.append(_alert(aid, day, "monotony_high", "warning",
                          "Entraînement trop monotone",
                          f"Monotonie de Foster à {_fr(last['monotony'])} "
                          f"(seuil {MONOTONY_WARN}). Des charges quotidiennes trop "
                          "uniformes limitent la surcompensation. Introduire un "
                          "vrai contraste dur / facile et un jour de repos.",
                          "monotony", last["monotony"], MONOTONY_WARN))

    if last.get("strain") and last["strain"] > STRAIN_WARN:
        out.append(_alert(aid, day, "strain_high", "warning",
                          "Contrainte hebdomadaire élevée",
                          f"Strain à {_fr(last['strain'], 0)} (charge hebdomadaire × "
                          "monotonie). Foster associe les pics de contrainte aux "
                          "épisodes de maladie et de méforme.",
                          "strain", last["strain"], STRAIN_WARN))

    if last.get("ctl_ramp_7d") and last["ctl_ramp_7d"] > RAMP_WARN:
        out.append(_alert(aid, day, "ramp_high", "warning",
                          "Progression de charge trop rapide",
                          f"CTL en hausse de {_fr(last['ctl_ramp_7d'], 1)} points sur "
                          f"7 jours (repère prudent : ≤ {_fr(RAMP_WARN, 0)}). "
                          "Une montée en charge soutenable se situe entre 3 et 7 "
                          "points de CTL par semaine.",
                          "ctl_ramp_7d", last["ctl_ramp_7d"], RAMP_WARN))

    recent_tsb = [r["tsb"] for r in pmc_rows[-10:] if r.get("tsb") is not None]
    if len(recent_tsb) >= 10 and all(t < -25 for t in recent_tsb):
        out.append(_alert(aid, day, "tsb_low", "warning",
                          "Fatigue résiduelle prolongée",
                          f"TSB sous −25 depuis 10 jours (actuel {_fr(last['tsb'], 0)}). "
                          "Soutenable sur un bloc de surcharge court, à condition "
                          "de programmer une décharge dans les jours qui viennent.",
                          "tsb", last["tsb"], -25))

    # --- semaine sans repos -------------------------------------------
    last7 = pmc_rows[-7:]
    if len(last7) == 7 and all(r["load"] > 20 for r in last7):
        out.append(_alert(aid, day, "monotonous_week", "info",
                          "Sept jours d'affilée sans repos",
                          "Aucun jour à charge nulle sur la semaine écoulée. "
                          "Un jour de repos complet hebdomadaire reste le levier "
                          "de récupération le mieux documenté.",
                          "sessions", 7, 7))

    # --- bien-être ----------------------------------------------------
    w_recent = [w for w in wellness_rows[-7:]]
    hrv_flags = [w for w in w_recent if w.get("hrv_ln_rmssd") is not None]
    if len(hrv_flags) >= 4:
        baseline = sum(w["hrv_ln_rmssd"] for w in wellness_rows[-60:]
                       if w.get("hrv_ln_rmssd") is not None)
        n = sum(1 for w in wellness_rows[-60:] if w.get("hrv_ln_rmssd") is not None)
        if n >= 15:
            baseline /= n
            recent_mean = sum(w["hrv_ln_rmssd"] for w in hrv_flags) / len(hrv_flags)
            if recent_mean < baseline - 0.12:
                out.append(_alert(aid, day, "hrv_suppressed", "critical",
                                  "VFC durablement basse",
                                  f"Moyenne 7 jours de ln(RMSSD) à {_fr(recent_mean)} "
                                  f"contre {_fr(baseline)} en référence 60 jours. "
                                  "Une dépression vagale prolongée précède "
                                  "fréquemment la méforme ou l'infection : alléger "
                                  "l'intensité 48 à 72 h.",
                                  "ln_rmssd", recent_mean, round(baseline - 0.12, 3)))

    rhr_recent = [w["resting_hr"] for w in w_recent if w.get("resting_hr")]
    rhr_base = [w["resting_hr"] for w in wellness_rows[-60:-7] if w.get("resting_hr")]
    if len(rhr_recent) >= 3 and len(rhr_base) >= 15:
        cur = sum(rhr_recent[-3:]) / len(rhr_recent[-3:])
        base = sum(rhr_base) / len(rhr_base)
        if cur - base >= 5:
            out.append(_alert(aid, day, "rhr_elevated", "warning",
                              "FC de repos élevée",
                              f"FC de repos à {_fr(cur, 0)} bpm sur 3 jours contre "
                              f"{_fr(base, 0)} bpm en référence (+{_fr(cur - base, 0)}). "
                              "Cause fréquente : dette de sommeil, infection "
                              "débutante, déshydratation ou charge non absorbée.",
                              "resting_hr", cur, round(base + 5, 1)))

    sleep = [w["sleep_total_min"] for w in w_recent if w.get("sleep_total_min")]
    if len(sleep) >= 5:
        debt = sum(480 - s for s in sleep if s < 480)
        if debt > 300:
            out.append(_alert(aid, day, "sleep_debt", "warning",
                              "Dette de sommeil cumulée",
                              f"{_fr(debt / 60, 1)} h de déficit sur la semaine "
                              "(besoin de référence 8 h). Le sommeil est le "
                              "premier facteur de récupération et de prévention "
                              "des blessures chez le sportif.",
                              "sleep_debt_min", debt, 300))

    readiness_low = [w for w in w_recent if (w.get("readiness") or 100) < 50]
    if len(readiness_low) >= 3:
        out.append(_alert(aid, day, "readiness_low", "warning",
                          "Disponibilité faible répétée",
                          f"{len(readiness_low)} jours sous 50/100 sur les 7 derniers. "
                          "Croiser avec la charge : si le PMC ne l'explique pas, "
                          "chercher du côté du sommeil, du stress ou de la nutrition.",
                          "readiness", len(readiness_low), 3))

    for inj in injuries:
        if inj.get("status") != "résolue":
            out.append(_alert(aid, day, "injury_open", "critical",
                              f"Blessure en cours — {inj.get('body_part', 'n/c')}",
                              f"{inj.get('type') or 'Lésion'} "
                              f"({inj.get('body_part')}, {inj.get('side') or 'n/a'}) "
                              f"depuis le {inj.get('date')}. Statut : {inj.get('status')}. "
                              "Adapter la charge et documenter le retour progressif.",
                              "severity", inj.get("severity"), None))
            break

    return out


def summarize(alerts: Sequence[dict]) -> dict:
    sev = {"critical": 0, "warning": 0, "info": 0}
    for a in alerts:
        sev[a["severity"]] = sev.get(a["severity"], 0) + 1
    if sev["critical"]:
        overall = "critical"
    elif sev["warning"]:
        overall = "warning"
    elif sev["info"]:
        overall = "info"
    else:
        overall = "ok"
    return {"counts": sev, "overall": overall, "total": len(alerts)}
