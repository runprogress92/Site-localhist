"""Lecture des formats XML d'échange : TCX et GPX.

* **TCX** (Training Center XML, Garmin) — exporté par Garmin Connect et par
  Polar Flow. Contient tours, points de trace, FC, cadence, puissance
  (extension TPX) et distance cumulée.
* **GPX** (GPS Exchange Format) — universel ; les données physiologiques
  passent par l'extension ``TrackPointExtension`` de Garmin (FC, cadence,
  température) et par ``PowerExtension`` pour la puissance.

Les deux parsers produisent la même structure normalisée que le décodeur
FIT, ce qui permet de partager entièrement le pipeline d'analyse.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

_NS_RE = re.compile(r"\{.*?\}")


def _tag(element) -> str:
    """Nom de balise débarrassé de son espace de noms."""
    return _NS_RE.sub("", element.tag)


def _find(parent, name: str):
    for child in parent:
        if _tag(child) == name:
            return child
    return None


def _findall(parent, name: str) -> list:
    return [c for c in parent if _tag(c) == name]


def _deep(parent, name: str):
    for child in parent.iter():
        if _tag(child) == name:
            return child
    return None


def _text(element, default=None):
    if element is None or element.text is None:
        return default
    return element.text.strip()


def _float(element, default=None):
    value = _text(element)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def parse_time(value: str | None) -> datetime | None:
    """ISO-8601 tolérant (Z, offsets, fractions de seconde)."""
    if not value:
        return None
    value = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


TCX_SPORT_MAP = {"Running": "running", "Biking": "cycling",
                 "Swimming": "swimming", "Other": "other"}


def _hr_value(parent, name: str):
    """<AverageHeartRateBpm><Value>151</Value></...> : la valeur est imbriquee."""
    node = _find(parent, name)
    if node is None:
        return None
    value = _find(node, "Value")
    return _float(value if value is not None else node)


def parse_tcx(source) -> dict:
    """Analyse un fichier TCX. ``source`` : chemin, fichier ou bytes."""
    root = _parse_root(source)
    activities = _deep(root, "Activities")
    if activities is None:
        raise ValueError("TCX sans bloc <Activities> : fichier non reconnu.")
    activity = _find(activities, "Activity")
    if activity is None:
        raise ValueError("TCX sans <Activity>.")

    sport = TCX_SPORT_MAP.get(activity.get("Sport", "Other"), "other")
    points: list[dict] = []
    laps: list[dict] = []

    for lap_el in _findall(activity, "Lap"):
        lap = {
            "start_time": parse_time(lap_el.get("StartTime")),
            "duration_s": _float(_find(lap_el, "TotalTimeSeconds")),
            "distance_m": _float(_find(lap_el, "DistanceMeters")),
            "max_speed_ms": _float(_find(lap_el, "MaximumSpeed")),
            "calories": _float(_find(lap_el, "Calories")),
            "avg_hr": _hr_value(lap_el, "AverageHeartRateBpm"),
            "max_hr": _hr_value(lap_el, "MaximumHeartRateBpm"),
            "cadence": _float(_find(lap_el, "Cadence")),
            "intensity": _text(_find(lap_el, "Intensity")),
        }
        avg_watts = _deep(lap_el, "AvgWatts")
        if avg_watts is not None:
            lap["avg_power_w"] = _float(avg_watts)
        laps.append(lap)

        for track in _findall(lap_el, "Track"):
            for tp in _findall(track, "Trackpoint"):
                point: dict[str, Any] = {"time": parse_time(_text(_find(tp, "Time")))}
                position = _find(tp, "Position")
                if position is not None:
                    point["lat"] = _float(_find(position, "LatitudeDegrees"))
                    point["lon"] = _float(_find(position, "LongitudeDegrees"))
                point["altitude"] = _float(_find(tp, "AltitudeMeters"))
                point["distance"] = _float(_find(tp, "DistanceMeters"))
                hr = _find(tp, "HeartRateBpm")
                if hr is not None:
                    point["heart_rate"] = _float(_find(hr, "Value"))
                cad = _find(tp, "Cadence")
                if cad is not None:
                    point["cadence"] = _float(cad)
                ext = _find(tp, "Extensions")
                if ext is not None:
                    for node in ext.iter():
                        name = _tag(node)
                        if name == "Watts":
                            point["power"] = _float(node)
                        elif name == "Speed":
                            point["speed"] = _float(node)
                        elif name == "RunCadence":
                            point["cadence"] = _float(node)
                points.append(point)

    return _finalize(points, laps, sport, source_format="tcx")


def parse_gpx(source) -> dict:
    """Analyse un fichier GPX, extensions Garmin comprises."""
    root = _parse_root(source)
    points: list[dict] = []
    sport = "other"

    name_el = _deep(root, "name")
    track_name = _text(name_el)
    type_el = _deep(root, "type")
    type_text = (_text(type_el) or "").lower()
    if "run" in type_text or "cours" in type_text:
        sport = "running"
    elif "cycl" in type_text or "bike" in type_text or "ride" in type_text or "vélo" in type_text:
        sport = "cycling"
    elif "swim" in type_text or "nat" in type_text:
        sport = "swimming"

    for trk in root.iter():
        if _tag(trk) != "trkpt":
            continue
        point: dict[str, Any] = {
            "lat": float(trk.get("lat")) if trk.get("lat") else None,
            "lon": float(trk.get("lon")) if trk.get("lon") else None,
        }
        for child in trk.iter():
            name = _tag(child)
            if name == "ele":
                point["altitude"] = _float(child)
            elif name == "time":
                point["time"] = parse_time(_text(child))
            elif name in ("hr", "heartrate", "HeartRate"):
                point["heart_rate"] = _float(child)
            elif name in ("cad", "cadence", "Cadence"):
                point["cadence"] = _float(child)
            elif name in ("atemp", "temp", "Temperature"):
                point["temperature"] = _float(child)
            elif name in ("power", "PowerInWatts", "watts"):
                point["power"] = _float(child)
            elif name == "speed":
                point["speed"] = _float(child)
        points.append(point)

    if not points:
        raise ValueError("GPX sans point de trace <trkpt>.")
    result = _finalize(points, [], sport, source_format="gpx")
    if track_name:
        result["name"] = track_name
    return result


def _parse_root(source):
    if isinstance(source, (bytes, bytearray)):
        return ET.fromstring(source)
    if hasattr(source, "read"):
        return ET.parse(source).getroot()
    return ET.parse(str(source)).getroot()


# ----------------------------------------------------------- normalisation
def haversine(lat1, lon1, lat2, lon2) -> float:
    """Distance orthodromique en mètres (rayon terrestre moyen 6 371 km)."""
    import math
    if None in (lat1, lon1, lat2, lon2):
        return 0.0
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _finalize(points: list[dict], laps: list[dict], sport: str,
              source_format: str) -> dict:
    """Rééchantillonne à 1 Hz et reconstitue distance et vitesse si absentes."""
    points = [p for p in points if p.get("time")]
    if not points:
        raise ValueError("Aucun point horodaté exploitable.")
    points.sort(key=lambda p: p["time"])
    start = points[0]["time"]
    end = points[-1]["time"]
    span = int((end - start).total_seconds()) + 1
    if span <= 0 or span > 86400 * 2:
        span = len(points)

    keys = ["heart_rate", "power", "cadence", "speed", "altitude",
            "distance", "lat", "lon", "temperature"]
    series: dict[str, list] = {k: [None] * span for k in keys}

    for p in points:
        i = int((p["time"] - start).total_seconds())
        if not (0 <= i < span):
            continue
        for k in keys:
            if p.get(k) is not None:
                series[k][i] = p[k]

    # distance cumulée depuis le GPS si le fichier ne la fournit pas
    if not any(v is not None for v in series["distance"]) and \
            any(v is not None for v in series["lat"]):
        acc = 0.0
        prev = None
        for i in range(span):
            if series["lat"][i] is not None and series["lon"][i] is not None:
                if prev is not None:
                    acc += haversine(prev[0], prev[1], series["lat"][i], series["lon"][i])
                prev = (series["lat"][i], series["lon"][i])
                series["distance"][i] = round(acc, 2)

    # interpolation des trous courts
    for values in series.values():
        last = None
        for i, v in enumerate(values):
            if v is None:
                continue
            if last is not None and 1 < i - last <= 30:
                a, gap = values[last], i - last
                for j in range(1, gap):
                    values[last + j] = a + (v - a) * j / gap
            last = i

    # vitesse dérivée de la distance si elle manque
    if not any(v is not None for v in series["speed"]):
        for i in range(1, span):
            d0, d1 = series["distance"][i - 1], series["distance"][i]
            if d0 is not None and d1 is not None:
                series["speed"][i] = max(0.0, round(d1 - d0, 3))
        if span > 1:
            series["speed"][0] = series["speed"][1]

    series["time"] = list(range(span))
    streams = {k: v for k, v in series.items() if any(x is not None for x in v)}

    return {
        "format": source_format,
        "sport": sport,
        "start_time": start,
        "duration_s": float(span),
        "streams": streams,
        "laps": laps,
        "n_points": len(points),
    }
