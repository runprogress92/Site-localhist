"""Génère des fichiers d'activité réalistes dans ``samples/``.

Ces fichiers servent à éprouver la chaîne d'import sans posséder de montre :
ils sont produits par les mêmes encodeurs que ceux du projet et lus par les
mêmes décodeurs, dans les trois formats acceptés.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import synth
from .fit_helper import write_fit

ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLES = ROOT / "samples"


def _xml_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def write_tcx(path: Path, start: datetime, sport: str, streams: dict) -> None:
    """Écrit un TCX conforme au schéma de Garmin, extensions comprises."""
    tcx_sport = {"running": "Running", "cycling": "Biking",
                 "swimming": "Other"}.get(sport, "Other")
    n = len(streams["time"])
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<TrainingCenterDatabase '
        'xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" '
        'xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">',
        f'<Activities><Activity Sport="{tcx_sport}">',
        f'<Id>{start.strftime("%Y-%m-%dT%H:%M:%SZ")}</Id>',
        f'<Lap StartTime="{start.strftime("%Y-%m-%dT%H:%M:%SZ")}">',
        f'<TotalTimeSeconds>{n}</TotalTimeSeconds>',
        f'<DistanceMeters>{streams["distance"][-1]:.1f}</DistanceMeters>',
        f'<MaximumSpeed>{max(streams["speed"]):.3f}</MaximumSpeed>',
        '<Calories>0</Calories>',
        f'<AverageHeartRateBpm><Value>'
        f'{round(sum(streams["heart_rate"]) / n)}</Value></AverageHeartRateBpm>',
        f'<MaximumHeartRateBpm><Value>'
        f'{round(max(streams["heart_rate"]))}</Value></MaximumHeartRateBpm>',
        '<Intensity>Active</Intensity><TriggerMethod>Manual</TriggerMethod>',
        '<Track>',
    ]
    for i in range(n):
        stamp = (start + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append("<Trackpoint>")
        lines.append(f"<Time>{stamp}</Time>")
        if streams.get("lat"):
            lines.append(
                f'<Position><LatitudeDegrees>{streams["lat"][i]:.7f}</LatitudeDegrees>'
                f'<LongitudeDegrees>{streams["lon"][i]:.7f}</LongitudeDegrees></Position>')
        if streams.get("altitude"):
            lines.append(f'<AltitudeMeters>{streams["altitude"][i]:.1f}</AltitudeMeters>')
        lines.append(f'<DistanceMeters>{streams["distance"][i]:.2f}</DistanceMeters>')
        lines.append(f'<HeartRateBpm><Value>'
                     f'{round(streams["heart_rate"][i])}</Value></HeartRateBpm>')
        if streams.get("cadence") and sport == "cycling":
            lines.append(f'<Cadence>{round(streams["cadence"][i])}</Cadence>')
        extensions = [f'<ns3:Speed>{streams["speed"][i]:.3f}</ns3:Speed>']
        if streams.get("power"):
            extensions.append(f'<ns3:Watts>{round(streams["power"][i])}</ns3:Watts>')
        if streams.get("cadence") and sport != "cycling":
            extensions.append(
                f'<ns3:RunCadence>{round(streams["cadence"][i] / 2)}</ns3:RunCadence>')
        lines.append("<Extensions><ns3:TPX>" + "".join(extensions) + "</ns3:TPX></Extensions>")
        lines.append("</Trackpoint>")
    lines += ["</Track></Lap>",
              "<Creator xsi:type=\"Device_t\" "
              "xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\">"
              "<Name>Athlytics</Name></Creator>",
              "</Activity></Activities></TrainingCenterDatabase>"]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_gpx(path: Path, start: datetime, name: str, sport: str,
              streams: dict) -> None:
    n = len(streams["time"])
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Athlytics" '
        'xmlns="http://www.topografix.com/GPX/1/1" '
        'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">',
        f"<metadata><time>{start.strftime('%Y-%m-%dT%H:%M:%SZ')}</time></metadata>",
        f"<trk><name>{_xml_escape(name)}</name><type>{sport}</type><trkseg>",
    ]
    for i in range(n):
        stamp = (start + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(f'<trkpt lat="{streams["lat"][i]:.7f}" '
                     f'lon="{streams["lon"][i]:.7f}">')
        lines.append(f'<ele>{streams["altitude"][i]:.1f}</ele>')
        lines.append(f"<time>{stamp}</time>")
        parts = [f'<gpxtpx:hr>{round(streams["heart_rate"][i])}</gpxtpx:hr>']
        if streams.get("cadence"):
            parts.append(f'<gpxtpx:cad>{round(streams["cadence"][i] / 2)}</gpxtpx:cad>')
        if streams.get("temperature"):
            parts.append(f'<gpxtpx:atemp>'
                         f'{round(streams["temperature"][i])}</gpxtpx:atemp>')
        lines.append("<extensions><gpxtpx:TrackPointExtension>"
                     + "".join(parts) + "</gpxtpx:TrackPointExtension></extensions>")
        lines.append("</trkpt>")
    lines += ["</trkseg></trk></gpx>"]
    path.write_text("\n".join(lines), encoding="utf-8")


SAMPLE_SPECS = [
    {"file": "garmin-velo-seuil.fit", "format": "fit", "sport": "cycling",
     "shape": "seuil", "duration": 4500, "elevation": 420,
     "ctx": {"hr_max": 189, "hr_rest": 42, "lthr": 171, "ftp_w": 285,
             "threshold_speed_ms": 4.6},
     "name": "Vélo — blocs au seuil"},
    {"file": "garmin-course-vo2max.fit", "format": "fit", "sport": "running",
     "shape": "VO2max", "duration": 3600, "elevation": 90,
     "ctx": {"hr_max": 196, "hr_rest": 44, "lthr": 176,
             "threshold_speed_ms": 4.55},
     "name": "Course — intervalles VO2max"},
    {"file": "polar-course-endurance.tcx", "format": "tcx", "sport": "running",
     "shape": "endurance", "duration": 3900, "elevation": 140,
     "ctx": {"hr_max": 192, "hr_rest": 46, "lthr": 172,
             "threshold_speed_ms": 4.2},
     "name": "Course — endurance fondamentale"},
    {"file": "coros-trail-longue.gpx", "format": "gpx", "sport": "trail_running",
     "shape": "longue", "duration": 7200, "elevation": 950,
     "ctx": {"hr_max": 191, "hr_rest": 41, "lthr": 172,
             "threshold_speed_ms": 3.7},
     "name": "Trail — sortie longue en montagne"},
    {"file": "velo-sortie-longue.fit", "format": "fit", "sport": "cycling",
     "shape": "longue", "duration": 12600, "elevation": 1250,
     "ctx": {"hr_max": 185, "hr_rest": 48, "lthr": 165, "ftp_w": 245,
             "threshold_speed_ms": 4.2},
     "name": "Vélo — sortie longue"},
]


def generate(verbose: bool = True) -> list[Path]:
    SAMPLES.mkdir(exist_ok=True)
    rng = random.Random(2026)
    written = []
    start = datetime.now(timezone.utc).replace(
        hour=8, minute=0, second=0, microsecond=0) - timedelta(days=6)

    for i, spec in enumerate(SAMPLE_SPECS):
        ctx = {"sex": "M", **spec["ctx"]}
        streams = synth.build_streams(
            sport=spec["sport"], shape=spec["shape"], duration_s=spec["duration"],
            ctx=ctx, elevation_gain_m=spec["elevation"], rng=rng,
            start_lat=45.20 + rng.uniform(-0.4, 0.4),
            start_lon=6.35 + rng.uniform(-0.4, 0.4))
        moment = start + timedelta(days=i)
        path = SAMPLES / spec["file"]
        if spec["format"] == "fit":
            write_fit(path, moment, spec["sport"], streams)
        elif spec["format"] == "tcx":
            write_tcx(path, moment, spec["sport"], streams)
        else:
            write_gpx(path, moment, spec["name"], spec["sport"], streams)
        written.append(path)
        if verbose:
            size = path.stat().st_size
            print(f"  {path.name:32s} {spec['format']:4s} "
                  f"{spec['duration'] // 60:4d} min  {size / 1024:7.1f} ko")
    return written


if __name__ == "__main__":
    print("\n  Génération des fichiers d'exemple\n")
    generate()
    print(f"\n  Écrits dans {SAMPLES}\n")
