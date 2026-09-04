"""Résolution du profil d'un athlète à une date donnée.

Le profil physiologique est historisé : chaque test met à jour une ligne
datée. Analyser une séance de mars avec la FTP de novembre fausserait la
charge — on résout donc toujours le profil applicable *à la date de la
séance*, jamais le plus récent.
"""
from __future__ import annotations

from datetime import date, datetime

from . import db
from .science import zones as Z


def age_at(birth_date: str | None, on: str | None = None) -> float | None:
    if not birth_date:
        return None
    try:
        born = datetime.fromisoformat(birth_date).date()
    except ValueError:
        return None
    ref = date.fromisoformat(on) if on else date.today()
    return round((ref - born).days / 365.25, 1)


def physiology_at(athlete_id: int, on: str | None = None) -> dict:
    """Dernière ligne de profil dont la date d'effet précède ``on``."""
    on = on or date.today().isoformat()
    row = db.query_one(
        "SELECT * FROM physiology WHERE athlete_id = ? AND effective_date <= ?"
        " ORDER BY effective_date DESC LIMIT 1", (athlete_id, on))
    if row is None:   # avant le premier test : on prend le plus ancien connu
        row = db.query_one(
            "SELECT * FROM physiology WHERE athlete_id = ?"
            " ORDER BY effective_date ASC LIMIT 1", (athlete_id,))
    return row or {}


def athlete_context(athlete_id: int, on: str | None = None) -> dict:
    """Athlète + profil physiologique + zones, prêts pour l'analyse."""
    athlete = db.query_one("SELECT * FROM athletes WHERE id = ?", (athlete_id,))
    if not athlete:
        raise ValueError(f"Athlète {athlete_id} introuvable.")
    physio = physiology_at(athlete_id, on)
    ctx = {
        "athlete": athlete,
        "physiology": physio,
        "sex": athlete.get("sex") or "X",
        "age": age_at(athlete.get("birth_date"), on),
        "weight_kg": physio.get("weight_kg") or athlete.get("weight_kg"),
        "hr_max": physio.get("hr_max"),
        "hr_rest": physio.get("hr_rest"),
        "lthr": physio.get("hr_lt2") or physio.get("hr_max") and round(physio["hr_max"] * 0.9),
        "lt1": physio.get("hr_lt1"),
        "ftp_w": physio.get("ftp_w"),
        "cp_w": physio.get("cp_w"),
        "w_prime_j": physio.get("w_prime_j"),
        "threshold_pace_s_km": physio.get("threshold_pace_s_km"),
        "critical_speed_ms": physio.get("critical_speed_ms"),
        "vo2max": physio.get("vo2max"),
        "vdot": physio.get("vdot"),
    }
    if ctx["threshold_pace_s_km"] and not ctx["critical_speed_ms"]:
        ctx["critical_speed_ms"] = round(1000.0 / ctx["threshold_pace_s_km"], 4)
    ctx["threshold_speed_ms"] = ctx["critical_speed_ms"]
    ctx["zones"] = {
        "hr": Z.hr_zones("friel_lthr", lthr=ctx["lthr"], hr_max=ctx["hr_max"],
                         hr_rest=ctx["hr_rest"]),
        "hr3": Z.hr_zones("seiler3", lthr=ctx["lthr"], hr_max=ctx["hr_max"]),
        "power": Z.power_zones(ctx["ftp_w"] or 0),
        "pace": Z.pace_zones(ctx["threshold_speed_ms"] or 0),
    }
    return ctx


def default_physiology(sex: str = "M", age: float = 32) -> dict:
    """Valeurs de repli pour un athlète sans profil renseigné."""
    from .science.physiology import estimate_hr_max
    hr_max = (estimate_hr_max(age, sex) or {}).get("hr_max", 190)
    return {
        "hr_max": hr_max,
        "hr_rest": 55,
        "hr_lt2": round(hr_max * 0.89),
        "hr_lt1": round(hr_max * 0.78),
        "ftp_w": 200,
        "threshold_pace_s_km": 300,
    }
