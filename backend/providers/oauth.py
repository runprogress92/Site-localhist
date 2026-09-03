"""Signature OAuth et client HTTP, sur la bibliothèque standard uniquement.

Garmin utilise historiquement **OAuth 1.0a** (signature HMAC-SHA1 de chaque
requête) ; Polar et Coros utilisent **OAuth 2.0** (jeton porteur + jeton de
rafraîchissement). Les deux mécanismes sont implémentés ici pour éviter
toute dépendance externe : ``hmac``, ``hashlib``, ``urllib`` et ``secrets``
suffisent.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "Athlytics/1.0 (+localhost)"
TIMEOUT = 30


class HttpError(Exception):
    def __init__(self, status: int, body: str, url: str = ""):
        super().__init__(f"HTTP {status} sur {url} : {body[:400]}")
        self.status = status
        self.body = body
        self.url = url


def http_request(url: str, *, method: str = "GET", headers: dict | None = None,
                 data: bytes | None = None, timeout: int = TIMEOUT) -> tuple[int, bytes, dict]:
    """Requête HTTP brute. Renvoie (statut, corps, en-têtes)."""
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("User-Agent", USER_AGENT)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        raise HttpError(exc.code, body.decode("utf-8", "replace"), url) from exc
    except urllib.error.URLError as exc:
        raise HttpError(0, f"Connexion impossible : {exc.reason}", url) from exc


def http_json(url: str, **kwargs) -> Any:
    status, body, _headers = http_request(url, **kwargs)
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HttpError(status, body.decode("utf-8", "replace")[:400], url)


# ------------------------------------------------------------- OAuth 1.0a
def _quote(value: str) -> str:
    """Encodage percent d'OAuth 1.0a (RFC 5849 §3.6) : réservés stricts."""
    return urllib.parse.quote(str(value), safe="-._~")


def oauth1_signature(method: str, url: str, params, consumer_secret: str,
                     token_secret: str = "") -> str:
    """Signature HMAC-SHA1 : base = MÉTHODE&url&paramètres normalisés.

    ``params`` accepte un dictionnaire ou une liste de paires : la RFC 5849
    autorise une même clé plusieurs fois (paramètre présent à la fois dans
    l'URL et dans le corps), ce qu'un dictionnaire ne peut pas représenter.
    Le tri se fait sur la clé *encodée* puis sur la valeur encodée.
    """
    pairs = list(params.items()) if hasattr(params, "items") else list(params)
    encoded = sorted((_quote(str(k)), _quote(str(v))) for k, v in pairs)
    normalized = "&".join(f"{k}={v}" for k, v in encoded)
    base = "&".join([method.upper(), _quote(url), _quote(normalized)])
    key = f"{_quote(consumer_secret)}&{_quote(token_secret)}"
    digest = hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def oauth1_header(method: str, url: str, consumer_key: str, consumer_secret: str,
                  token: str = "", token_secret: str = "",
                  extra: dict | None = None, realm: str | None = None) -> str:
    """Construit l'en-tête ``Authorization: OAuth …`` complet."""
    params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_version": "1.0",
    }
    if token:
        params["oauth_token"] = token
    params.update(extra or {})

    # Les paramètres de la requête entrent dans la base de signature
    query = urllib.parse.urlparse(url).query
    signing = dict(params)
    if query:
        for key, values in urllib.parse.parse_qs(query, keep_blank_values=True).items():
            signing[key] = values[0]
    base_url = url.split("?")[0]

    params["oauth_signature"] = oauth1_signature(
        method, base_url, signing, consumer_secret, token_secret)
    pieces = [f'{_quote(k)}="{_quote(v)}"' for k, v in sorted(params.items())]
    if realm:
        pieces.insert(0, f'realm="{realm}"')
    return "OAuth " + ", ".join(pieces)


def oauth1_call(method: str, url: str, consumer_key: str, consumer_secret: str,
                token: str = "", token_secret: str = "", data: bytes | None = None,
                extra_oauth: dict | None = None) -> tuple[int, bytes, dict]:
    header = oauth1_header(method, url, consumer_key, consumer_secret,
                           token, token_secret, extra_oauth)
    return http_request(url, method=method, headers={"Authorization": header}, data=data)


# --------------------------------------------------------------- OAuth 2.0
def pkce_pair() -> tuple[str, str]:
    """Couple (code_verifier, code_challenge) pour PKCE S256 (RFC 7636)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def build_authorize_url(base: str, client_id: str, redirect_uri: str,
                        scope: str = "", state: str = "",
                        challenge: str | None = None, extra: dict | None = None) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
    }
    if scope:
        params["scope"] = scope
    if state:
        params["state"] = state
    if challenge:
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "S256"
    params.update(extra or {})
    return f"{base}?{urllib.parse.urlencode(params)}"


def basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def exchange_code(token_url: str, client_id: str, client_secret: str, code: str,
                  redirect_uri: str, verifier: str | None = None,
                  auth_style: str = "basic") -> dict:
    """Échange le code d'autorisation contre un jeton d'accès.

    ``auth_style`` : ``basic`` (identifiants en en-tête, exigé par Polar) ou
    ``body`` (identifiants dans le corps, accepté par Coros).
    """
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if verifier:
        payload["code_verifier"] = verifier
    headers = {"Content-Type": "application/x-www-form-urlencoded",
               "Accept": "application/json"}
    if auth_style == "basic":
        headers["Authorization"] = basic_auth_header(client_id, client_secret)
    else:
        payload["client_id"] = client_id
        payload["client_secret"] = client_secret
    body = urllib.parse.urlencode(payload).encode()
    return http_json(token_url, method="POST", headers=headers, data=body)


def refresh_token(token_url: str, client_id: str, client_secret: str,
                  refresh: str, auth_style: str = "basic") -> dict:
    payload = {"grant_type": "refresh_token", "refresh_token": refresh}
    headers = {"Content-Type": "application/x-www-form-urlencoded",
               "Accept": "application/json"}
    if auth_style == "basic":
        headers["Authorization"] = basic_auth_header(client_id, client_secret)
    else:
        payload["client_id"] = client_id
        payload["client_secret"] = client_secret
    body = urllib.parse.urlencode(payload).encode()
    return http_json(token_url, method="POST", headers=headers, data=body)


def parse_qs_body(body: bytes | str) -> dict:
    """Réponse ``application/x-www-form-urlencoded`` (OAuth 1.0a)."""
    if isinstance(body, bytes):
        body = body.decode("utf-8", "replace")
    return {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}
