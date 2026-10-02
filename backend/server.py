"""Serveur HTTP — bibliothèque standard uniquement.

Un routeur minimal à motifs (``/api/athletes/<int:athlete_id>/summary``),
la sérialisation JSON, la compression gzip, le service des fichiers
statiques et la lecture des envois multipart. Suffisant et robuste pour un
usage local, sans imposer d'installation de dépendances.
"""
from __future__ import annotations

import gzip
import json
import mimetypes
import re
import traceback
import urllib.parse
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from . import db, network

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "frontend"

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/png", ".png")


class HttpProblem(Exception):
    """Erreur applicative traduite en réponse JSON propre."""

    def __init__(self, status: int, message: str, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


def bad_request(message: str, detail=None):
    return HttpProblem(400, message, detail)


def not_found(message: str = "Ressource introuvable"):
    return HttpProblem(404, message)


class JsonEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, (bytes, bytearray)):
            return o.decode("utf-8", "replace")
        if isinstance(o, set):
            return sorted(o)
        return super().default(o)


# ------------------------------------------------------------------ requête
class Request:
    def __init__(self, method: str, path: str, query: dict, headers,
                 body: bytes, params: dict):
        self.method = method
        self.path = path
        self.query = query
        self.headers = headers
        self.body = body
        self.params = params
        self._json = None

    def q(self, key: str, default=None, cast=None):
        values = self.query.get(key)
        value = values[0] if values else None
        if value is None or value == "":
            return default
        if cast is None:
            return value
        try:
            return cast(value)
        except (TypeError, ValueError):
            return default

    def q_int(self, key: str, default=None):
        return self.q(key, default, int)

    def q_float(self, key: str, default=None):
        return self.q(key, default, float)

    def q_bool(self, key: str, default=False):
        value = self.q(key)
        if value is None:
            return default
        return value.lower() in ("1", "true", "yes", "oui", "on")

    @property
    def json(self) -> dict:
        if self._json is None:
            if not self.body:
                self._json = {}
            else:
                try:
                    self._json = json.loads(self.body.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise bad_request(f"Corps JSON invalide : {exc}")
            if not isinstance(self._json, dict):
                self._json = {"value": self._json}
        return self._json

    def files(self) -> list[dict]:
        """Analyse un corps ``multipart/form-data``."""
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            return []
        match = re.search(r'boundary="?([^";]+)"?', content_type)
        if not match:
            raise bad_request("Frontière multipart absente.")
        boundary = ("--" + match.group(1)).encode()
        out = []
        for part in self.body.split(boundary):
            if not part or part in (b"--\r\n", b"--", b"\r\n"):
                continue
            head, _, payload = part.partition(b"\r\n\r\n")
            if not payload:
                continue
            headers_text = head.decode("utf-8", "replace")
            name = re.search(r'name="([^"]*)"', headers_text)
            filename = re.search(r'filename="([^"]*)"', headers_text)
            out.append({
                "name": name.group(1) if name else "",
                "filename": filename.group(1) if filename else "",
                "data": payload.rstrip(b"\r\n--").rstrip(b"\r\n"),
            })
        return [f for f in out if f["filename"]]


# ------------------------------------------------------------------ routeur
PARAM_RE = re.compile(r"<(?:(int|str|float):)?([a-zA-Z_][a-zA-Z0-9_]*)>")
CASTS = {"int": int, "float": float, "str": str}


class Router:
    def __init__(self):
        self.routes: list[tuple[str, re.Pattern, dict, Callable, str]] = []

    def add(self, method: str, pattern: str, handler: Callable, name: str = "") -> None:
        casts: dict[str, Callable] = {}

        def replace(match):
            kind, key = match.group(1) or "str", match.group(2)
            casts[key] = CASTS[kind]
            fragment = r"[^/]+" if kind == "str" else (
                r"-?\d+" if kind == "int" else r"-?[\d.]+")
            return f"(?P<{key}>{fragment})"

        regex = re.compile("^" + PARAM_RE.sub(replace, pattern) + "/?$")
        self.routes.append((method.upper(), regex, casts, handler,
                            name or handler.__name__))

    def route(self, method: str, pattern: str, name: str = ""):
        def decorator(fn):
            self.add(method, pattern, fn, name)
            return fn
        return decorator

    def get(self, pattern, name=""):
        return self.route("GET", pattern, name)

    def post(self, pattern, name=""):
        return self.route("POST", pattern, name)

    def put(self, pattern, name=""):
        return self.route("PUT", pattern, name)

    def patch(self, pattern, name=""):
        return self.route("PATCH", pattern, name)

    def delete(self, pattern, name=""):
        return self.route("DELETE", pattern, name)

    def match(self, method: str, path: str):
        allowed = set()
        for route_method, regex, casts, handler, _name in self.routes:
            match = regex.match(path)
            if not match:
                continue
            if route_method != method.upper():
                allowed.add(route_method)
                continue
            params = {}
            for key, value in match.groupdict().items():
                params[key] = casts.get(key, str)(value)
            return handler, params
        if allowed:
            raise HttpProblem(405, f"Méthode {method} non autorisée ici "
                                   f"(autorisées : {', '.join(sorted(allowed))}).")
        return None, None

    def list_routes(self) -> list[dict]:
        return [{"method": m, "pattern": r.pattern, "name": n}
                for m, r, _c, _h, n in self.routes]


ROUTER = Router()


# ---------------------------------------------------------------- gestionnaire
class Handler(BaseHTTPRequestHandler):
    server_version = "Athlytics"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------- réponses
    def _send(self, status: int, body: bytes, content_type: str,
              extra_headers: dict | None = None, cacheable: bool = False) -> None:
        accepts_gzip = "gzip" in (self.headers.get("Accept-Encoding") or "")
        compressed = False
        if accepts_gzip and len(body) > 1024 and (
                content_type.startswith(("text/", "application/json",
                                          "application/javascript",
                                          "image/svg"))):
            body = gzip.compress(body, 5)
            compressed = True
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Cache-Control",
                         "public, max-age=3600" if cacheable else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        pending = getattr(self, "_pending_cookie", None)
        if pending:
            self.send_header("Set-Cookie", pending)
            self._pending_cookie = None
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, data: Any, status: int = 200, headers: dict | None = None) -> None:
        body = json.dumps(data, cls=JsonEncoder, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", headers)

    def send_error_json(self, status: int, message: str, detail=None) -> None:
        self.send_json({"error": message, "detail": detail, "status": status}, status)

    # ---------------------------------------------------------------- verbes
    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_PATCH(self):
        self._handle("PATCH")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Allow", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ------------------------------------------------------------ traitement
    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > 200 * 1024 * 1024:
            raise HttpProblem(413, "Fichier trop volumineux (limite 200 Mo).")
        return self.rfile.read(length)

    def _handle(self, method: str) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        try:
            if not self._authorised(path, query):
                return
            if path.startswith("/api/"):
                handler, params = ROUTER.match(method, path)
                if handler is None:
                    raise not_found(f"Route inconnue : {method} {path}")
                request = Request(method, path, query, self.headers,
                                  self._read_body(), params)
                result = handler(request)
                if isinstance(result, tuple):
                    data, status = result
                    self.send_json(data, status)
                elif isinstance(result, Response):
                    self._send(result.status, result.body, result.content_type,
                               result.headers)
                else:
                    self.send_json(result)
                return
            self._serve_static(path)
        except HttpProblem as problem:
            self.send_error_json(problem.status, problem.message, problem.detail)
        except BrokenPipeError:
            pass
        except Exception as exc:
            trace = traceback.format_exc()
            print(f"\n[500] {method} {path}\n{trace}")
            self.send_error_json(500, f"Erreur interne : {exc}",
                                 trace.splitlines()[-3:])
        finally:
            try:
                db.close_thread_connection() if False else None
            except Exception:
                pass

    # ------------------------------------------------------- contrôle d'accès
    def _authorised(self, path: str, query: dict) -> bool:
        """Filtre les requêtes venant du réseau local.

        Rien n'est demandé tant que l'accès réseau n'est pas activé, ni aux
        requêtes issues de la machine elle-même : l'entraîneur sur son poste
        ne doit jamais avoir à saisir quoi que ce soit.
        """
        if not network.lan_enabled():
            return True
        client = self.client_address[0] if self.client_address else "127.0.0.1"
        if network.is_loopback(client):
            return True

        code = (query.get("c") or [None])[0]
        wait = network.retry_after(client)
        if wait > 0:
            # Attente en cours : on ne regarde même pas le code, sinon la
            # temporisation ne coûterait rien à qui les essaie tous.
            if path.startswith("/api/"):
                self.send_error_json(429, "Trop d'essais. Patientez.",
                                     {"retry_after": round(wait)})
            else:
                self._send(429, _access_page(wait=wait).encode("utf-8"),
                           "text/html; charset=utf-8")
            return False

        if network.check_access(client, self.headers.get("Cookie", ""), code):
            network.clear_failures(client)
            if code:
                # Le code devient un cookie : il n'est demandé qu'une fois par
                # appareil. HttpOnly parce qu'aucun script du site ne le lit —
                # autant qu'il reste hors de portée du JavaScript.
                self._pending_cookie = (
                    f"{network.COOKIE_NAME}={code}; Path=/; Max-Age=31536000; "
                    "SameSite=Lax; HttpOnly")
                if not path.startswith("/api/"):
                    # …et on renvoie vers l'adresse sans le paramètre, pour
                    # que le code ne reste pas inscrit dans la barre d'adresse
                    # ni dans l'historique du téléphone. Le fragment (#/route)
                    # n'est pas transmis au serveur : le navigateur le
                    # conserve de lui-même à travers la redirection.
                    clean = {k: v for k, v in query.items() if k != "c"}
                    target = path or "/"
                    if clean:
                        target += "?" + urllib.parse.urlencode(clean, doseq=True)
                    self._send(302, b"", "text/plain",
                               extra_headers={"Location": target})
                    return False
            return True

        # Un essai manqué ne compte que si un code a réellement été présenté :
        # la page de saisie elle-même ne doit pas consommer de tentative.
        if code is not None:
            network.note_failure(client)

        if path.startswith("/api/"):
            self.send_error_json(401, "Code d'accès requis.",
                                 {"needs_code": True})
        else:
            self._send(401, _access_page(wrong=code is not None).encode("utf-8"),
                       "text/html; charset=utf-8")
        return False

    # --------------------------------------------------------------- statique
    def _serve_static(self, path: str) -> None:
        if path in ("/", ""):
            path = "/index.html"
        candidate = (STATIC_DIR / path.lstrip("/")).resolve()
        try:
            candidate.relative_to(STATIC_DIR.resolve())
        except ValueError:
            raise HttpProblem(403, "Chemin hors du répertoire public.")
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.exists():
            # application monopage : toute route inconnue renvoie l'index
            index = STATIC_DIR / "index.html"
            if index.exists() and "." not in Path(path).name:
                candidate = index
            else:
                raise not_found(f"Fichier absent : {path}")
        content_type, _ = mimetypes.guess_type(str(candidate))
        content_type = content_type or "application/octet-stream"
        if content_type.startswith("text/") or content_type in (
                "application/javascript", "application/json", "image/svg+xml",
                "application/manifest+json"):
            content_type += "; charset=utf-8"
        body = candidate.read_bytes()
        extra = {}
        # Le service worker doit être relu à chaque chargement, sinon une
        # version corrigée resterait piégée derrière le cache qu'elle gère.
        if candidate.name == "sw.js":
            cacheable = False
            extra["Service-Worker-Allowed"] = "/"
        else:
            cacheable = candidate.suffix in (".css", ".js", ".svg", ".woff2",
                                             ".png", ".webmanifest")
        self._send(200, body, content_type, extra_headers=extra, cacheable=cacheable)


def _access_page(wrong: bool = False, wait: float = 0.0) -> str:
    """Page minimale de saisie du code d'accès.

    Volontairement autonome — ni CSS ni JavaScript du site — puisqu'elle
    doit s'afficher avant toute autorisation.
    """
    if wait > 0:
        delay = round(wait)
        message = (f"<p class=\"warn\">Trop d'essais. Réessayez dans "
                   f"{delay} seconde{'s' if delay > 1 else ''}.</p>")
    elif wrong:
        message = '<p class="warn">Ce code ne correspond pas. Vérifiez-le ' \
                  'sur l\'ordinateur et recommencez.</p>'
    else:
        message = ""
    return """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Athlytics — code d'accès</title><style>
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;
 background:#0b0e13;color:#e6eaf0;
 font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}
.box{width:100%;max-width:340px;text-align:center}
.mark{width:56px;height:56px;border-radius:14px;margin:0 auto 20px;
 background:linear-gradient(135deg,#5b9bff,#7b56c9);display:grid;place-items:center;
 font-size:26px;font-weight:700;color:#fff}
h1{font-size:19px;margin:0 0 8px}
p{color:#8d9aab;font-size:14px;line-height:1.6;margin:0 0 24px}
input{width:100%;padding:16px;font-size:26px;text-align:center;letter-spacing:10px;
 border-radius:12px;border:1px solid #2f3a4a;background:#12161e;color:#e6eaf0;
 font-variant-numeric:tabular-nums}
input:focus{outline:none;border-color:#4f8ff7;box-shadow:0 0 0 3px rgba(79,143,247,.18)}
button{width:100%;margin-top:14px;padding:15px;font-size:16px;font-weight:600;
 border:none;border-radius:12px;background:#4f8ff7;color:#fff}
small{display:block;margin-top:22px;color:#5d6878;font-size:12px;line-height:1.6}
.warn{color:#f2a33c;font-size:13px;margin:0 0 16px;font-weight:600}
</style></head><body><div class="box">
<div class="mark">A</div>
<h1>Code d'accès</h1>
<p>Saisissez le code à six chiffres affiché sur l'ordinateur,
dans Réglages &rsaquo; Connecter mon téléphone.</p>
__MESSAGE__
<form method="get" action="/">
<input name="c" inputmode="numeric" pattern="[0-9]*" maxlength="6"
 autocomplete="one-time-code" placeholder="000000" autofocus>
<button type="submit">Ouvrir Athlytics</button>
</form>
<small>Ce code n'est demandé qu'une fois par appareil.
Il protège l'accès depuis votre réseau local ; l'échange n'est pas chiffré,
évitez les réseaux publics.</small>
</div></body></html>""".replace("__MESSAGE__", message)


class Response:
    """Réponse brute (fichier binaire, CSV, redirection)."""

    def __init__(self, body: bytes, content_type: str = "application/octet-stream",
                 status: int = 200, headers: dict | None = None):
        self.body = body if isinstance(body, bytes) else str(body).encode("utf-8")
        self.content_type = content_type
        self.status = status
        self.headers = headers or {}


def redirect(location: str) -> Response:
    return Response(b"", "text/plain", 302, {"Location": location})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    verbose = False


def serve(host: str = "127.0.0.1", port: int = 8420, verbose: bool = False) -> Server:
    httpd = Server((host, port), Handler)
    httpd.verbose = verbose
    # server_address, et non « port » : avec port=0 le système en choisit un,
    # et c'est celui-là que l'interface doit afficher au téléphone.
    network.set_bound(host, httpd.server_address[1])
    return httpd
