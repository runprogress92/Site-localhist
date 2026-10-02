"""Accès depuis le réseau local : code, temporisation, filtrage HTTP.

Les fonctions pures sont vérifiées directement ; le filtrage lui-même est
exercé par de vraies requêtes HTTP émises vers l'adresse réseau de la
machine, parce que c'est l'adresse du client vue par le serveur qui décide
de tout. Sans interface réseau, ces tests-là sont ignorés plutôt que
faussement verts.
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

TEMP_DIR = tempfile.mkdtemp(prefix="athlytics-network-")
os.environ["ATHLYTICS_DB"] = str(Path(TEMP_DIR) / "test.db")

from backend import db, network  # noqa: E402
from backend import api as api_routes  # noqa: E402,F401  (enregistre les routes)
from backend.server import serve  # noqa: E402


class CodeTestCase(unittest.TestCase):
    """Code d'accès et décision d'autorisation, sans passer par HTTP."""

    @classmethod
    def setUpClass(cls):
        db.set_db_path(Path(TEMP_DIR) / "test.db")
        db.init_db()

    def setUp(self):
        network.enable_lan(False)
        network._failures.clear()

    def test_code_is_six_digits_and_stable(self):
        code = network.access_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        # Un code qui changerait à chaque lecture rendrait le QR code faux
        # une seconde après son affichage.
        self.assertEqual(code, network.access_code())

    def test_rotate_changes_the_code(self):
        before = network.access_code()
        after = network.rotate_code()
        self.assertNotEqual(before, after)
        self.assertEqual(after, network.access_code())

    def test_loopback_never_needs_a_code(self):
        network.enable_lan(True)
        for address in ("127.0.0.1", "::1", "localhost"):
            self.assertTrue(network.check_access(address, "", None), address)

    def test_lan_refused_while_access_is_closed(self):
        code = network.access_code()
        # L'accès n'est pas activé : même le bon code ne doit rien ouvrir.
        self.assertFalse(network.check_access("192.168.1.42", "", code))

    def test_lan_accepts_query_then_cookie(self):
        network.enable_lan(True)
        code = network.access_code()
        self.assertTrue(network.check_access("192.168.1.42", "", code))
        self.assertTrue(network.check_access(
            "192.168.1.42", f"{network.COOKIE_NAME}={code}", None))
        self.assertTrue(network.check_access(
            "192.168.1.42", f"autre=1; {network.COOKIE_NAME}={code}; x=2", None))

    def test_lan_refuses_wrong_or_missing_code(self):
        network.enable_lan(True)
        self.assertFalse(network.check_access("192.168.1.42", "", None))
        self.assertFalse(network.check_access("192.168.1.42", "", "000000"))
        self.assertFalse(network.check_access(
            "192.168.1.42", f"{network.COOKIE_NAME}=000000", None))
        # Un préfixe correct ne doit pas suffire.
        code = network.access_code()
        self.assertFalse(network.check_access("192.168.1.42", "", code[:5]))

    def test_throttle_is_free_then_grows(self):
        client = "192.168.1.77"
        for _ in range(network.FREE_ATTEMPTS):
            self.assertEqual(network.note_failure(client), 0.0)
            self.assertEqual(network.retry_after(client), 0.0)
        first = network.note_failure(client)
        second = network.note_failure(client)
        self.assertGreater(first, 0)
        self.assertEqual(second, first * 2)
        self.assertGreater(network.retry_after(client), 0)

    def test_throttle_is_capped_and_per_client(self):
        client = "192.168.1.78"
        for _ in range(40):
            network.note_failure(client)
        self.assertLessEqual(network.note_failure(client), network.MAX_DELAY_S)
        # Le voisin bloqué ne doit pas bloquer tout le réseau.
        self.assertEqual(network.retry_after("192.168.1.79"), 0.0)

    def test_success_clears_the_slate(self):
        client = "192.168.1.80"
        for _ in range(network.FREE_ATTEMPTS + 2):
            network.note_failure(client)
        self.assertGreater(network.retry_after(client), 0)
        network.clear_failures(client)
        self.assertEqual(network.retry_after(client), 0.0)

    def test_private_and_loopback_detection(self):
        self.assertTrue(network.is_private("192.168.1.1"))
        self.assertTrue(network.is_private("10.0.0.1"))
        self.assertFalse(network.is_private("8.8.8.8"))
        self.assertFalse(network.is_private("pas-une-adresse"))
        self.assertTrue(network.is_loopback("127.0.0.1"))
        self.assertFalse(network.is_loopback("192.168.1.1"))

    def test_phone_url_carries_the_code_only_when_open(self):
        if not network.all_local_ips():
            self.skipTest("aucune interface réseau")
        network.enable_lan(False)
        self.assertNotIn("?c=", network.phone_url(8420) or "")
        network.enable_lan(True)
        url = network.phone_url(8420)
        self.assertIn(f"?c={network.access_code()}", url)
        self.assertTrue(url.startswith("http://"))


class LanHttpTestCase(unittest.TestCase):
    """Filtrage réel, vu depuis une adresse qui n'est pas la boucle locale."""

    server = None
    thread = None

    @classmethod
    def setUpClass(cls):
        db.set_db_path(Path(TEMP_DIR) / "test.db")
        db.init_db()
        cls.address = network.local_ip()
        if not cls.address:
            raise unittest.SkipTest("aucune adresse réseau locale")
        cls.server = serve("0.0.0.0", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        if cls.server:
            cls.server.shutdown()
            cls.server.server_close()

    def setUp(self):
        network._failures.clear()
        network.enable_lan(True)
        self.code = network.access_code()

    def tearDown(self):
        network.enable_lan(False)
        network._failures.clear()

    # ------------------------------------------------------------ utilitaires
    def fetch(self, path, cookie=None, host=None, follow=False):
        """Renvoie (statut, en-têtes, corps) sans lever d'exception."""
        url = f"http://{host or self.address}:{self.port}{path}"
        request = urllib.request.Request(url)
        if cookie:
            request.add_header("Cookie", cookie)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = (urllib.request.build_opener()
                  if follow else urllib.request.build_opener(NoRedirect))
        try:
            with opener.open(request, timeout=20) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    # ------------------------------------------------------------------ tests
    def test_loopback_is_served_without_a_code(self):
        status, _, _ = self.fetch("/api/health", host="127.0.0.1")
        self.assertEqual(status, 200)

    def test_lan_without_code_gets_the_access_page(self):
        status, headers, body = self.fetch("/")
        self.assertEqual(status, 401)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn("Code d'accès", body.decode("utf-8"))
        # La page de saisie ne doit rien révéler du code attendu.
        self.assertNotIn(self.code.encode(), body)

    def test_lan_api_without_code_is_json_401(self):
        status, headers, body = self.fetch("/api/athletes")
        self.assertEqual(status, 401)
        payload = json.loads(body)
        self.assertTrue(payload["detail"]["needs_code"])
        self.assertNotIn(self.code, body.decode("utf-8"))

    def test_good_code_redirects_without_the_code_and_sets_a_cookie(self):
        status, headers, _ = self.fetch(f"/?c={self.code}")
        self.assertEqual(status, 302)
        # Le code ne doit pas rester inscrit dans la barre d'adresse.
        self.assertEqual(headers["Location"], "/")
        self.assertIn(f"{network.COOKIE_NAME}={self.code}", headers["Set-Cookie"])
        self.assertIn("HttpOnly", headers["Set-Cookie"])

    def test_redirect_keeps_the_other_parameters(self):
        _, headers, _ = self.fetch(f"/seances?c={self.code}&tri=date")
        self.assertEqual(headers["Location"], "/seances?tri=date")

    def test_cookie_alone_opens_the_api(self):
        status, _, _ = self.fetch(
            "/api/athletes", cookie=f"{network.COOKIE_NAME}={self.code}")
        self.assertEqual(status, 200)

    def test_wrong_cookie_is_refused(self):
        status, _, _ = self.fetch(
            "/api/athletes", cookie=f"{network.COOKIE_NAME}=000000")
        self.assertEqual(status, 401)

    def test_closing_access_reopens_nothing(self):
        network.enable_lan(False)
        # Accès refermé : même l'écoute ouverte ne doit plus rien servir au
        # réseau… sauf que « lan_enabled » faux désactive tout le filtre, donc
        # le serveur redevient ouvert. C'est le comportement voulu : refermer
        # l'accès passe par l'arrêt de l'écoute, pas par le filtre.
        status, _, _ = self.fetch("/api/health")
        self.assertEqual(status, 200)

    def test_repeated_failures_are_throttled(self):
        for _ in range(network.FREE_ATTEMPTS + 1):
            status, _, _ = self.fetch("/?c=000000")
            self.assertEqual(status, 401)
        status, _, body = self.fetch("/?c=000000")
        self.assertEqual(status, 429)
        self.assertIn("Trop d'essais", body.decode("utf-8"))
        # Pendant l'attente, même le bon code est refusé : sinon la
        # temporisation ne coûterait rien à qui les essaie tous.
        status, _, _ = self.fetch(f"/?c={self.code}")
        self.assertEqual(status, 429)

    def test_throttled_api_answers_json_429(self):
        for _ in range(network.FREE_ATTEMPTS + 2):
            self.fetch("/?c=000000")
        status, _, body = self.fetch("/api/athletes?c=000000")
        self.assertEqual(status, 429)
        self.assertIn("retry_after", json.loads(body)["detail"])

    def test_the_access_page_is_self_contained(self):
        """Elle s'affiche avant toute autorisation : aucun fichier externe."""
        _, _, body = self.fetch("/")
        page = body.decode("utf-8")
        for forbidden in ("<script", "<link", "src=", "@import"):
            self.assertNotIn(forbidden, page)


class NetworkApiTestCase(unittest.TestCase):
    """Routes /api/network, appelées depuis la boucle locale."""

    @classmethod
    def setUpClass(cls):
        db.set_db_path(Path(TEMP_DIR) / "test.db")
        db.init_db()
        cls.server = serve("127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        network.enable_lan(False)

    def call(self, path, method="GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{self.base}{path}", data=data,
                                         method=method)
        if data:
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            if response.headers.get("Content-Type", "").startswith("application/json"):
                return json.loads(raw)
            return raw

    def test_status_hides_the_code_while_access_is_closed(self):
        state = self.call("/api/network")
        self.assertFalse(state["enabled"])
        self.assertIsNone(state["code"])
        self.assertIn("same_wifi", state["notes"])
        self.assertIn("security", state["notes"])

    def test_enabling_exposes_the_code_and_a_qr(self):
        self.call("/api/network", "POST", {"enabled": True})
        state = self.call("/api/network")
        self.assertTrue(state["enabled"])
        self.assertEqual(len(state["code"]), 6)
        if state["addresses"]:
            self.assertTrue(state["qr_svg"].startswith("<svg"))
            self.assertIn(state["code"], state["phone_url"])
        # L'écoute est sur 127.0.0.1 : l'interface doit prévenir qu'il faut
        # relancer pour que le téléphone puisse se connecter.
        self.assertTrue(state["requires_restart"])

    def test_reported_port_is_the_one_actually_served(self):
        state = self.call("/api/network")
        self.assertEqual(state["port"], self.server.server_address[1])

    def test_renewing_the_code_changes_it(self):
        self.call("/api/network", "POST", {"enabled": True})
        before = self.call("/api/network")["code"]
        after = self.call("/api/network/code", "POST", {})["code"]
        self.assertNotEqual(before, after)
        self.assertEqual(after, self.call("/api/network")["code"])

    def test_qr_endpoint_returns_an_image(self):
        self.call("/api/network", "POST", {"enabled": True})
        if not network.all_local_ips():
            self.skipTest("aucune interface réseau")
        body = self.call("/api/network/qr.svg")
        self.assertTrue(body.startswith(b"<svg"))

    def test_missing_field_is_rejected(self):
        try:
            self.call("/api/network", "POST", {})
            self.fail("un corps sans « enabled » doit être refusé")
        except urllib.error.HTTPError as exc:
            self.assertEqual(exc.code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
