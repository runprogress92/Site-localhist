"""Tests de la chaîne d'ingestion : FIT, TCX, GPX et pipeline d'analyse."""
import math
import random
import sys
import unittest
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.ingest import fit, fit_writer, pipeline, xmlformats


def build_sample_fit(n=900, sport=2, with_gps=True):
    """Construit en mémoire un fichier FIT complet et réaliste."""
    rng = random.Random(42)
    hr = [int(140 + 15 * math.sin(i / 200) + rng.gauss(0, 1.5)) for i in range(n)]
    power = [int(230 + 60 * math.sin(i / 150) + rng.gauss(0, 8)) for i in range(n)]
    cadence = [int(88 + rng.gauss(0, 2)) for _ in range(n)]
    speed = [round(8.0 + 0.9 * math.sin(i / 180), 3) for i in range(n)]
    distance, acc = [], 0.0
    for v in speed:
        acc += v
        distance.append(round(acc, 2))
    altitude = [round(150 + 35 * math.sin(i / 300), 1) for i in range(n)]
    streams = {"heart_rate": hr, "power": power, "cadence": cadence,
               "speed": speed, "distance": distance, "altitude": altitude,
               "temperature": [17] * n}
    if with_gps:
        streams["lat"] = [45.7640 + i * 1e-5 for i in range(n)]
        streams["lon"] = [4.8357 + i * 8e-6 for i in range(n)]

    writer = fit_writer.FitWriter()
    start = datetime(2026, 5, 12, 8, 0, tzinfo=timezone.utc)
    writer.write_file_id(start, manufacturer=1, product=4315)
    writer.write_records(start, streams)
    writer.write_lap(start, n // 2, distance[n // 2 - 1], avg_hr=145, max_hr=168,
                     avg_power=245, avg_speed=8.0, avg_cadence=88, ascent=40)
    writer.write_session(start, n, distance[-1], sport=sport,
                         avg_hr=int(sum(hr) / n), max_hr=max(hr),
                         avg_power=int(sum(power) / n), max_power=max(power),
                         np=int(sum(power) / n) + 12, avg_speed=sum(speed) / n,
                         max_speed=max(speed), avg_cadence=88, calories=520,
                         ascent=180, descent=175,
                         start_lat=streams.get("lat", [None])[0],
                         start_lon=streams.get("lon", [None])[0])
    return writer.build(), streams


class TestFitCodec(unittest.TestCase):
    def setUp(self):
        self.blob, self.streams = build_sample_fit()
        self.decoded = fit.decode(BytesIO(self.blob))

    def test_header_is_valid(self):
        self.assertEqual(self.blob[8:12], b".FIT")
        self.assertEqual(self.decoded["header"]["header_size"], 12)

    def test_crc_matches(self):
        """Le CRC de fin doit couvrir en-tête et données."""
        import struct
        body = self.blob[:-2]
        stored = struct.unpack("<H", self.blob[-2:])[0]
        self.assertEqual(fit.fit_crc(body), stored)

    def test_all_records_decoded(self):
        self.assertEqual(len(self.decoded["records"]), 900)
        self.assertEqual(len(self.decoded["sessions"]), 1)
        self.assertEqual(len(self.decoded["laps"]), 1)

    def test_values_roundtrip_exactly(self):
        record = self.decoded["records"][300]
        self.assertEqual(record["heart_rate"], self.streams["heart_rate"][300])
        self.assertEqual(record["power"], self.streams["power"][300])
        self.assertAlmostEqual(record["speed"], self.streams["speed"][300], places=3)
        self.assertAlmostEqual(record["altitude"], self.streams["altitude"][300], delta=0.2)

    def test_gps_semicircle_roundtrip(self):
        record = self.decoded["records"][100]
        self.assertAlmostEqual(fit.semicircles_to_degrees(record["position_lat"]),
                               self.streams["lat"][100], places=5)

    def test_sport_and_manufacturer_resolved(self):
        session = self.decoded["sessions"][0]
        self.assertEqual(fit.SPORT_NAMES[session["sport"]], "cycling")
        self.assertEqual(fit.MANUFACTURERS[self.decoded["file_id"]["manufacturer"]],
                         "Garmin")

    def test_to_streams_aligns_at_1hz(self):
        streams = fit.to_streams(self.decoded["records"])
        self.assertEqual(len(streams["heart_rate"]), 900)
        self.assertEqual(streams["heart_rate"][300], self.streams["heart_rate"][300])

    def test_truncated_file_raises(self):
        with self.assertRaises(fit.FitError):
            fit.decode(BytesIO(self.blob[:6]))

    def test_wrong_signature_raises(self):
        bad = bytearray(self.blob)
        bad[8:12] = b"XXXX"
        with self.assertRaises(fit.FitError):
            fit.decode(BytesIO(bytes(bad)))


SAMPLE_TCX = b"""<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
 xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
<Activities><Activity Sport="Running"><Id>2026-04-02T06:15:00Z</Id>
<Lap StartTime="2026-04-02T06:15:00Z">
<TotalTimeSeconds>60</TotalTimeSeconds><DistanceMeters>210</DistanceMeters>
<Calories>18</Calories>
<AverageHeartRateBpm><Value>151</Value></AverageHeartRateBpm>
<MaximumHeartRateBpm><Value>163</Value></MaximumHeartRateBpm>
<Intensity>Active</Intensity><Track>
<Trackpoint><Time>2026-04-02T06:15:00Z</Time>
<Position><LatitudeDegrees>48.8566</LatitudeDegrees><LongitudeDegrees>2.3522</LongitudeDegrees></Position>
<AltitudeMeters>35</AltitudeMeters><DistanceMeters>0</DistanceMeters>
<HeartRateBpm><Value>120</Value></HeartRateBpm>
<Extensions><ns3:TPX><ns3:Speed>3.4</ns3:Speed><ns3:RunCadence>84</ns3:RunCadence></ns3:TPX></Extensions>
</Trackpoint>
<Trackpoint><Time>2026-04-02T06:16:00Z</Time>
<Position><LatitudeDegrees>48.8590</LatitudeDegrees><LongitudeDegrees>2.3560</LongitudeDegrees></Position>
<AltitudeMeters>38</AltitudeMeters><DistanceMeters>210</DistanceMeters>
<HeartRateBpm><Value>160</Value></HeartRateBpm>
<Extensions><ns3:TPX><ns3:Speed>3.6</ns3:Speed><ns3:Watts>280</ns3:Watts></ns3:TPX></Extensions>
</Trackpoint></Track></Lap></Activity></Activities></TrainingCenterDatabase>"""

SAMPLE_GPX = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"
 xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">
<trk><name>Col du Galibier</name><type>cycling</type><trkseg>
<trkpt lat="45.0640" lon="6.4070"><ele>1800</ele><time>2026-07-14T09:00:00Z</time>
<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>142</gpxtpx:hr>
<gpxtpx:cad>78</gpxtpx:cad><gpxtpx:atemp>14</gpxtpx:atemp>
</gpxtpx:TrackPointExtension></extensions></trkpt>
<trkpt lat="45.0700" lon="6.4100"><ele>1830</ele><time>2026-07-14T09:00:30Z</time>
<extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>150</gpxtpx:hr>
</gpxtpx:TrackPointExtension></extensions></trkpt>
</trkseg></trk></gpx>"""


class TestXmlFormats(unittest.TestCase):
    def test_tcx_parses_sport_and_streams(self):
        parsed = xmlformats.parse_tcx(SAMPLE_TCX)
        self.assertEqual(parsed["sport"], "running")
        self.assertEqual(parsed["duration_s"], 61.0)
        self.assertIn("heart_rate", parsed["streams"])
        self.assertEqual(parsed["streams"]["heart_rate"][0], 120)
        self.assertEqual(parsed["streams"]["heart_rate"][60], 160)

    def test_tcx_interpolates_between_points(self):
        parsed = xmlformats.parse_tcx(SAMPLE_TCX)
        mid = parsed["streams"]["heart_rate"][30]
        self.assertAlmostEqual(mid, 140, delta=1)

    def test_tcx_lap_nested_heart_rate(self):
        parsed = xmlformats.parse_tcx(SAMPLE_TCX)
        self.assertEqual(parsed["laps"][0]["avg_hr"], 151.0)
        self.assertEqual(parsed["laps"][0]["max_hr"], 163.0)

    def test_gpx_parses_extensions(self):
        parsed = xmlformats.parse_gpx(SAMPLE_GPX)
        self.assertEqual(parsed["name"], "Col du Galibier")
        self.assertEqual(parsed["sport"], "cycling")
        self.assertEqual(parsed["streams"]["heart_rate"][0], 142)
        self.assertEqual(parsed["streams"]["cadence"][0], 78)

    def test_gpx_reconstructs_distance_from_gps(self):
        parsed = xmlformats.parse_gpx(SAMPLE_GPX)
        distance = parsed["streams"]["distance"][-1]
        self.assertGreater(distance, 600)
        self.assertLess(distance, 800)

    def test_haversine_known_distance(self):
        # Paris — Lyon : environ 392 km
        km = xmlformats.haversine(48.8566, 2.3522, 45.7640, 4.8357) / 1000
        self.assertAlmostEqual(km, 392, delta=3)

    def test_gpx_without_points_raises(self):
        with self.assertRaises(ValueError):
            xmlformats.parse_gpx(b'<?xml version="1.0"?><gpx><trk></trk></gpx>')


class TestPipeline(unittest.TestCase):
    def test_format_detection(self):
        blob, _ = build_sample_fit(n=60)
        self.assertEqual(pipeline.sniff_format(blob), "fit")
        self.assertEqual(pipeline.sniff_format(SAMPLE_TCX), "tcx")
        self.assertEqual(pipeline.sniff_format(SAMPLE_GPX), "gpx")
        with self.assertRaises(ValueError):
            pipeline.sniff_format(b"ceci n'est pas une activite")

    def test_parse_file_normalises_all_formats(self):
        blob, _ = build_sample_fit(n=120)
        for data, name in ((blob, "a.fit"), (SAMPLE_TCX, "a.tcx"), (SAMPLE_GPX, "a.gpx")):
            parsed = pipeline.parse_file(data, name)
            self.assertIn("streams", parsed)
            self.assertIn("start_time", parsed)
            self.assertIn("sport", parsed)
            self.assertIsNotNone(parsed["start_time"].tzinfo)

    def test_analyze_computes_expected_metrics(self):
        blob, streams = build_sample_fit(n=3600)
        parsed = pipeline.parse_file(blob, "test.fit")
        ctx = {
            "sex": "M", "age": 32, "weight_kg": 70, "hr_max": 190, "hr_rest": 45,
            "lthr": 170, "ftp_w": 250, "cp_w": 260, "w_prime_j": 20000,
            "threshold_speed_ms": 4.5, "zones": {
                "hr": [], "hr3": [], "power": [], "pace": []},
        }
        metrics = pipeline.analyze(parsed, ctx)
        self.assertAlmostEqual(metrics["avg_power_w"], 230, delta=15)
        self.assertGreaterEqual(metrics["np_w"], metrics["avg_power_w"] - 1)
        self.assertIsNotNone(metrics["tss"])
        self.assertIsNotNone(metrics["trimp_banister"])
        self.assertEqual(metrics["load_source"], "tss")
        self.assertIn("power", metrics["mmp"])
        self.assertGreater(metrics["work_kj"], 700)
        self.assertEqual(metrics["has_gps"], 1)

    def test_analyze_without_power_falls_back_to_hr(self):
        parsed = pipeline.parse_file(SAMPLE_TCX, "a.tcx")
        ctx = {"sex": "F", "age": 28, "weight_kg": 55, "hr_max": 195, "hr_rest": 45,
               "lthr": 175, "ftp_w": None, "threshold_speed_ms": 4.0,
               "zones": {"hr": [], "hr3": [], "power": [], "pace": []}}
        metrics = pipeline.analyze(parsed, ctx)
        self.assertIsNone(metrics.get("tss"))
        self.assertIsNotNone(metrics.get("hrtss"))

    def test_elevation_gain_ignores_noise(self):
        """Un profil plat bruité ne doit pas produire de dénivelé fantôme."""
        import random
        rng = random.Random(1)
        flat = [100 + rng.gauss(0, 0.3) for _ in range(3600)]
        gain, loss = pipeline._elevation(flat)
        self.assertLess(gain, 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
