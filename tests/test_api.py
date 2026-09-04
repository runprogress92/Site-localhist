"""Tests de bout en bout de l'API HTTP.

Un serveur réel est démarré sur une base temporaire, un petit jeu de données
est généré, puis les routes sont appelées par HTTP — ce qui exerce le
routeur, la sérialisation, la compression et la couche de persistance
ensemble, et pas seulement les fonctions prises isolément.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEMP_DIR = tempfile.mkdtemp(prefix="athlytics-tests-")
os.environ["ATHLYTICS_DB"] = str(Path(TEMP_DIR) / "test.db")

from backend import db  # noqa: E402
from backend import api as api_routes  # noqa: E402,F401  (enregistre les routes)
from backend.server import serve  # noqa: E402


class ApiTestCase(unittest.TestCase):
    server = None
    thread = None
    base = None

    @classmethod
    def setUpClass(cls):
        db.set_db_path(Path(TEMP_DIR) / "test.db")
        db.init_db()
        from backend.seed.generate import generate
        generate(athletes=2, days=70, stream_days=14, reset=True, verbose=False)
        cls.server = serve("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    # ------------------------------------------------------------ utilitaires
    def call(self, path, method="GET", body=None, expect=200):
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        if data:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                self.assertEqual(response.status, expect, f"{method} {path}")
                raw = response.read()
                if response.headers.get("Content-Type", "").startswith("application/json"):
                    return json.loads(raw)
                return raw
        except urllib.error.HTTPError as exc:
            payload = exc.read()
            if exc.code != expect:
                self.fail(f"{method} {path} → HTTP {exc.code} "
                          f"(attendu {expect}) : {payload[:300]!r}")
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return payload

    def first_athlete(self):
        return self.call("/api/athletes")["athletes"][0]

    # ------------------------------------------------------------------ tests
    def test_health(self):
        data = self.call("/api/health")
        self.assertEqual(data["status"], "ok")
        self.assertIn("database", data)

    def test_athlete_roster_has_state(self):
        data = self.call("/api/athletes")
        self.assertEqual(data["count"], 2)
        athlete = data["athletes"][0]
        for key in ("ctl", "atl", "tsb", "form", "week", "alerts"):
            self.assertIn(key, athlete)

    def test_athlete_detail_includes_zones(self):
        athlete = self.first_athlete()
        detail = self.call(f"/api/athletes/{athlete['id']}")
        self.assertIn("zones", detail)
        self.assertGreater(len(detail["zones"]["hr"]), 0)
        self.assertIn("physiology", detail)
        self.assertIn("totals", detail)

    def test_summary_payload_is_complete(self):
        athlete = self.first_athlete()
        summary = self.call(f"/api/athletes/{athlete['id']}/summary?days=60")
        for key in ("pmc", "wellness", "activities", "zone_summary", "hrv",
                    "sports", "alerts", "zones"):
            self.assertIn(key, summary)
        self.assertGreater(len(summary["pmc"]), 30)

    def test_pmc_projection(self):
        athlete = self.first_athlete()
        data = self.call(f"/api/athletes/{athlete['id']}/pmc?days=60&project=14")
        self.assertEqual(len(data["projection"]), 14)
        self.assertIn("form", data["current"])
        self.assertIn("acwr_state", data["current"])

    def test_activities_pagination_and_filters(self):
        athlete = self.first_athlete()
        page1 = self.call(f"/api/activities?athlete_id={athlete['id']}&limit=5")
        self.assertEqual(len(page1["activities"]), 5)
        page2 = self.call(f"/api/activities?athlete_id={athlete['id']}&limit=5&offset=5")
        ids1 = {a["id"] for a in page1["activities"]}
        ids2 = {a["id"] for a in page2["activities"]}
        self.assertFalse(ids1 & ids2, "les pages ne doivent pas se recouvrir")

    def test_activity_detail_and_streams(self):
        rows = db.query(
            "SELECT id FROM activities WHERE has_streams = 1 LIMIT 1")
        self.assertTrue(rows, "le jeu de test doit contenir des flux")
        activity_id = rows[0]["id"]
        detail = self.call(f"/api/activities/{activity_id}")
        self.assertIn("zone_times", detail)
        self.assertIn("context", detail)
        streams = self.call(f"/api/activities/{activity_id}/streams?points=500")
        self.assertIn("heart_rate", streams["streams"])
        self.assertLessEqual(len(streams["streams"]["heart_rate"]), 520)

    def test_wellness_roundtrip_computes_readiness(self):
        athlete = self.first_athlete()
        result = self.call(f"/api/athletes/{athlete['id']}/wellness", "POST", {
            "date": "2026-01-15", "hrv_rmssd": 62, "resting_hr": 46,
            "sleep_total_min": 470, "fatigue": 3, "soreness": 2,
            "mood": 2, "stress_subj": 3, "sleep_quality": 2, "motivation": 2,
        }, expect=201)
        self.assertIsNotNone(result["readiness"]["score"])
        self.assertIn(result["readiness"]["flag"], ("vert", "ambre", "rouge"))
        stored = self.call(f"/api/athletes/{athlete['id']}/wellness?days=400")
        entry = next(w for w in stored["wellness"] if w["date"] == "2026-01-15")
        self.assertEqual(entry["hrv_rmssd"], 62)
        self.assertIsNotNone(entry["hrv_ln_rmssd"])

    def test_physiology_update_is_dated_not_retroactive(self):
        """Une nouvelle FTP ne doit pas modifier les zones d'une date antérieure."""
        athlete = self.first_athlete()
        before = self.call(f"/api/athletes/{athlete['id']}/zones?date=2025-01-01")
        self.call(f"/api/athletes/{athlete['id']}/physiology", "POST", {
            "effective_date": "2030-01-01", "ftp_w": 999, "hr_lt2": 175,
        }, expect=201)
        after = self.call(f"/api/athletes/{athlete['id']}/zones?date=2025-01-01")
        self.assertEqual(before["basis"]["ftp_w"], after["basis"]["ftp_w"])
        future = self.call(f"/api/athletes/{athlete['id']}/zones?date=2030-06-01")
        self.assertEqual(future["basis"]["ftp_w"], 999)

    def test_upload_fit_file(self):
        """Import multipart d'un fichier FIT réellement encodé."""
        from tests.test_ingest import build_sample_fit
        blob, _ = build_sample_fit(n=1200)
        athlete = self.first_athlete()
        boundary = "----athlyticsTestBoundary"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="essai.fit"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + blob + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(
            f"{self.base}/api/activities/upload?athlete_id={athlete['id']}",
            data=body, method="POST")
        request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(request, timeout=60) as response:
            result = json.loads(response.read())
        self.assertEqual(result["imported"], 1, result.get("errors"))
        metrics = result["results"][0]["metrics"]
        self.assertAlmostEqual(metrics["duration_s"], 1200, delta=2)
        self.assertIsNotNone(metrics["load"])

    def test_export_csv_has_header(self):
        rows = db.query("SELECT id FROM activities WHERE has_streams = 1 LIMIT 1")
        raw = self.call(f"/api/activities/{rows[0]['id']}/export.csv")
        first_line = raw.split(b"\n")[0].decode()
        self.assertIn("time", first_line)
        self.assertIn("heart_rate", first_line)

    def test_export_fit_roundtrips(self):
        """Le FIT exporté doit être relisible par notre propre décodeur."""
        from io import BytesIO
        from backend.ingest import fit
        rows = db.query("SELECT id FROM activities WHERE has_streams = 1 LIMIT 1")
        blob = self.call(f"/api/activities/{rows[0]['id']}/export.fit")
        decoded = fit.decode(BytesIO(blob))
        self.assertGreater(len(decoded["records"]), 100)
        self.assertEqual(len(decoded["sessions"]), 1)

    def test_planning_generate_and_compliance(self):
        athlete = self.first_athlete()
        result = self.call(f"/api/athletes/{athlete['id']}/planned/generate", "POST",
                           {"weekly_load": 420, "replace": True}, expect=201)
        self.assertGreater(len(result["created"]), 3)
        total = sum(w["target_load"] for w in result["created"])
        self.assertAlmostEqual(total, 420, delta=25)
        compliance = self.call(f"/api/athletes/{athlete['id']}/compliance?weeks=8")
        self.assertIn("weeks", compliance)

    def test_taper_reaches_requested_form(self):
        athlete = self.first_athlete()
        from datetime import date, timedelta
        target = (date.today() + timedelta(days=21)).isoformat()
        data = self.call(f"/api/athletes/{athlete['id']}/taper?date={target}&tsb=18")
        self.assertAlmostEqual(data["final"]["tsb"], 18, delta=1.5)
        self.assertEqual(data["hold_days"] + data["taper_days"], data["days"])

    def test_taper_unavailable_is_not_an_error(self):
        """Sans objectif ni historique, la réponse doit rester un 200 explicite :
        c'est l'état normal d'un athlète qu'on vient de créer."""
        created = self.call("/api/athletes", "POST", {
            "first_name": "Sans", "last_name": "Historique"}, expect=201)
        data = self.call(f"/api/athletes/{created['id']}/taper")
        self.assertFalse(data["available"])
        self.assertIn("objectif", data["reason"].lower())
        self.call(f"/api/athletes/{created['id']}?hard=true", "DELETE")

    def test_fueling_plan(self):
        athlete = self.first_athlete()
        data = self.call(f"/api/athletes/{athlete['id']}/fueling"
                         "?duration_s=14400&temp_c=30&humidity_pct=70")
        self.assertGreaterEqual(data["carbs"]["g_per_hour"], 80)
        self.assertIn(data["heat"]["risk"], ("modéré", "élevé", "extrême — séance intense déconseillée"))
        self.assertGreater(data["heat"]["pace_penalty_pct"], 0)

    def test_zone_distribution_and_polarization(self):
        athlete = self.first_athlete()
        data = self.call(f"/api/athletes/{athlete['id']}/zone-distribution?days=60")
        self.assertIn("three_zone", data)
        self.assertAlmostEqual(
            data["three_zone"]["low"] + data["three_zone"]["threshold"]
            + data["three_zone"]["high"], 100, delta=0.5)
        self.assertIsInstance(data["verdict"], str)

    def test_team_overview_and_matrix(self):
        overview = self.call("/api/team/overview")
        self.assertEqual(len(overview["athletes"]), 2)
        self.assertIn("flags", overview["totals"])
        matrix = self.call("/api/team/matrix?days=21")
        self.assertEqual(len(matrix["dates"]), 21)
        self.assertEqual(len(matrix["matrix"][0]["cells"]), 21)

    def test_compare_endpoint(self):
        ids = ",".join(str(a["id"]) for a in self.call("/api/athletes")["athletes"])
        data = self.call(f"/api/compare?athletes={ids}&metric=ctl&days=40")
        self.assertEqual(len(data["series"]), 2)
        self.assertIn("stats", data["series"][0])

    def test_providers_never_leak_tokens(self):
        payload = json.dumps(self.call("/api/devices/providers"))
        self.assertNotIn("access_token", payload)
        self.assertNotIn("refresh_token", payload)
        self.assertNotIn("token_secret", payload)

    def test_provider_authorize_requires_configuration(self):
        athlete = self.first_athlete()
        error = self.call(
            f"/api/devices/garmin/authorize?athlete_id={athlete['id']}&json=true",
            expect=400)
        self.assertIn("client_id", error["error"])

    def test_search(self):
        athlete = self.first_athlete()
        data = self.call(f"/api/search?q={athlete['last_name'][:4]}")
        self.assertTrue(any(r["type"] == "athlete" for r in data["results"]))

    # ------------------------------------------------------- cas d'erreur
    def test_unknown_route_returns_404(self):
        error = self.call("/api/inexistant", expect=404)
        self.assertIn("error", error)

    def test_unknown_athlete_returns_404(self):
        self.call("/api/athletes/99999", expect=404)

    def test_wrong_method_returns_405(self):
        self.call("/api/athletes", "DELETE", expect=405)

    def test_invalid_json_returns_400(self):
        request = urllib.request.Request(
            f"{self.base}/api/athletes", data=b"{ceci n'est pas du json",
            method="POST")
        request.add_header("Content-Type", "application/json")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(ctx.exception.code, 400)

    def test_missing_required_field_returns_400(self):
        error = self.call("/api/athletes", "POST", {"first_name": "Sans"}, expect=400)
        self.assertIn("nom", error["error"].lower())

    def test_static_index_is_served(self):
        with urllib.request.urlopen(f"{self.base}/", timeout=10) as response:
            body = response.read()
        self.assertIn(b"<title>", body)
        self.assertIn(b"Athlytics", body)

    def test_path_traversal_is_blocked(self):
        request = urllib.request.Request(f"{self.base}/../backend/db.py")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
            self.assertNotIn(b"sqlite3", body)
        except urllib.error.HTTPError as exc:
            self.assertIn(exc.code, (403, 404))

    def test_athlete_crud_cycle(self):
        created = self.call("/api/athletes", "POST", {
            "first_name": "Test", "last_name": "Éphémère", "sex": "F",
            "birth_date": "1999-05-05", "primary_sport": "running",
        }, expect=201)
        athlete_id = created["id"]
        self.assertIsNotNone(created["athlete"]["id"])
        # un profil physiologique par défaut doit avoir été créé
        detail = self.call(f"/api/athletes/{athlete_id}")
        self.assertIsNotNone(detail["physiology"].get("hr_max"))
        self.call(f"/api/athletes/{athlete_id}", "PATCH", {"level": "national"})
        self.assertEqual(self.call(f"/api/athletes/{athlete_id}")["level"], "national")
        self.call(f"/api/athletes/{athlete_id}?hard=true", "DELETE")
        self.call(f"/api/athletes/{athlete_id}", expect=404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
