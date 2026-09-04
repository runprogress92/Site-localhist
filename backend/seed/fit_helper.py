"""Écriture d'un fichier FIT complet depuis des séries synthétiques."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..ingest.fit_writer import FitWriter

SPORT_CODES = {"running": (1, 0), "trail_running": (1, 3), "cycling": (2, 7),
               "swimming": (5, 17), "rowing": (15, 0), "walking": (11, 0)}


def write_fit(path: Path, start: datetime, sport: str, streams: dict) -> int:
    """Encode les séries en FIT, avec tours toutes les 15 minutes."""
    code, sub = SPORT_CODES.get(sport, (0, 0))
    writer = FitWriter()
    writer.write_file_id(start, manufacturer=1, product=4315)
    writer.write_records(start, streams)

    n = len(streams["time"])
    lap_length = 900
    for offset in range(0, n, lap_length):
        end = min(offset + lap_length, n)
        window = slice(offset, end)
        hr = [v for v in streams["heart_rate"][window] if v is not None]
        power = [v for v in (streams.get("power") or [])[window] if v is not None]
        speed = [v for v in streams["speed"][window] if v is not None]
        cadence = [v for v in (streams.get("cadence") or [])[window] if v is not None]
        writer.write_lap(
            start, end - offset,
            streams["distance"][end - 1] - streams["distance"][offset],
            avg_hr=round(sum(hr) / len(hr)) if hr else None,
            max_hr=round(max(hr)) if hr else None,
            avg_power=round(sum(power) / len(power)) if power else None,
            avg_speed=sum(speed) / len(speed) if speed else None,
            avg_cadence=round(sum(cadence) / len(cadence)) if cadence else None,
            ascent=None)

    hr = [v for v in streams["heart_rate"] if v is not None]
    power = [v for v in (streams.get("power") or []) if v is not None]
    speed = [v for v in streams["speed"] if v is not None]
    altitude = streams.get("altitude") or []
    ascent = 0.0
    for a, b in zip(altitude, altitude[1:]):
        if b > a:
            ascent += b - a
    writer.write_session(
        start, n, streams["distance"][-1], sport=code, sub_sport=sub,
        avg_hr=round(sum(hr) / len(hr)) if hr else None,
        max_hr=round(max(hr)) if hr else None,
        avg_power=round(sum(power) / len(power)) if power else None,
        max_power=round(max(power)) if power else None,
        np=round(sum(power) / len(power) * 1.04) if power else None,
        avg_speed=sum(speed) / len(speed) if speed else None,
        max_speed=max(speed) if speed else None,
        avg_cadence=round(sum(streams["cadence"]) / n) if streams.get("cadence") else None,
        calories=round(n * 0.19),
        ascent=round(ascent / 4), descent=round(ascent / 4),
        start_lat=(streams.get("lat") or [None])[0],
        start_lon=(streams.get("lon") or [None])[0])
    return writer.save(path)
