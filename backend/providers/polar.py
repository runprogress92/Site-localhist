"""Connecteur Polar — AccessLink v3.

Polar impose un modèle **transactionnel** : on ouvre une transaction, on
liste les ressources qu'elle contient, on les récupère, puis on la valide
(``PUT``). Tant qu'une transaction n'est pas validée, les données restent
disponibles ; une fois validée, elles ne seront plus proposées. Ce protocole
garantit qu'aucune séance n'est perdue en cas d'interruption, mais impose de
ne valider qu'après import réussi — c'est exactement ce que fait ce module.

Authentification : OAuth 2.0, identifiants du client transmis en
``Authorization: Basic`` lors de l'échange du code (exigence Polar).

Inscription : https://admin.polaraccesslink.com
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .. import db
from . import oauth
from .base import Provider, ProviderError

AUTHORIZE_URL = "https://flow.polar.com/oauth2/authorization"
TOKEN_URL = "https://polarremote.com/v2/oauth2/token"
API_BASE = "https://www.polaraccesslink.com/v3"


class PolarProvider(Provider):
    key = "polar"
    label = "Polar"
    auth_kind = "oauth2"
    doc_url = "https://www.polar.com/accesslink-api/"
    scopes = "accesslink.read_all"
    color = "#e2001a"

    # --------------------------------------------------------- autorisation
    def authorize_url(self, athlete_id: int, state: str) -> str:
        self.require_config()
        db.upsert("oauth_states", {"state": state, "provider": self.key,
                                   "athlete_id": athlete_id}, ["state"])
        return oauth.build_authorize_url(
            AUTHORIZE_URL, self.client_id, self.redirect_uri,
            scope=self.scopes, state=state)

    def handle_callback(self, athlete_id: int, params: dict, stored: dict) -> dict:
        self.require_config()
        code = params.get("code")
        if not code:
            raise ProviderError(f"Rappel Polar sans code : {params.get('error', '')}")
        token = oauth.exchange_code(TOKEN_URL, self.client_id, self.client_secret,
                                    code, self.redirect_uri, auth_style="basic")
        access = token.get("access_token")
        if not access:
            raise ProviderError(f"Polar n'a pas délivré de jeton : {token}")
        expires_at = None
        if token.get("expires_in"):
            expires_at = (datetime.now(timezone.utc) +
                          timedelta(seconds=int(token["expires_in"]))).strftime(
                              "%Y-%m-%dT%H:%M:%SZ")
        user_id = str(token.get("x_user_id") or "")
        self.save_account(athlete_id, access_token=access, provider_user_id=user_id,
                          token_type=token.get("token_type", "Bearer"),
                          expires_at=expires_at, status="connected",
                          scope=self.scopes)
        # Polar exige un enregistrement explicite de l'utilisateur
        self._register_user(access, user_id, athlete_id)
        return {"provider": self.key, "status": "connected", "user_id": user_id}

    def _register_user(self, access: str, user_id: str, athlete_id: int) -> None:
        """POST /users — obligatoire avant toute lecture de données."""
        body = json.dumps({"member-id": f"athlytics-{athlete_id}"}).encode()
        try:
            oauth.http_request(f"{API_BASE}/users", method="POST", data=body,
                               headers={"Authorization": f"Bearer {access}",
                                        "Content-Type": "application/json",
                                        "Accept": "application/json"})
        except oauth.HttpError as exc:
            if exc.status != 409:      # 409 = déjà enregistré, cas normal
                raise

    # ------------------------------------------------------------- requêtes
    def _headers(self, athlete_id: int) -> dict:
        return {"Authorization": f"Bearer {self.access_token(athlete_id)}",
                "Accept": "application/json"}

    def _user_id(self, athlete_id: int) -> str:
        account = self.account(athlete_id)
        if not account or not account.get("provider_user_id"):
            raise ProviderError("Polar : identifiant utilisateur inconnu.")
        return account["provider_user_id"]

    def _transaction(self, athlete_id: int, kind: str) -> tuple[str, list] | None:
        """Ouvre une transaction et renvoie (url, liste des ressources)."""
        user_id = self._user_id(athlete_id)
        url = f"{API_BASE}/users/{user_id}/{kind}"
        try:
            status, body, _ = oauth.http_request(
                url, method="POST", headers=self._headers(athlete_id))
        except oauth.HttpError as exc:
            if exc.status == 204:
                return None
            raise
        if status == 204 or not body:
            return None                  # aucune donnée nouvelle
        payload = json.loads(body)
        transaction_url = payload.get("resource-uri")
        listing = oauth.http_json(transaction_url, headers=self._headers(athlete_id))
        key = next((k for k in ("exercises", "activity-log", "physical-informations")
                    if isinstance(listing, dict) and k in listing), None)
        return transaction_url, (listing.get(key) if key else []) or []

    def _commit(self, athlete_id: int, transaction_url: str) -> None:
        oauth.http_request(transaction_url, method="PUT",
                           headers=self._headers(athlete_id))

    def list_activities(self, athlete_id: int, since: datetime,
                        until: datetime | None = None) -> list[dict]:
        """Ouvre une transaction d'exercices et renvoie leurs résumés."""
        self.require_config()
        transaction = self._transaction(athlete_id, "exercise-transactions")
        if not transaction:
            return []
        transaction_url, urls = transaction
        out = []
        for url in urls:
            try:
                summary = oauth.http_json(url, headers=self._headers(athlete_id))
            except oauth.HttpError:
                continue
            out.append({
                "external_id": str(summary.get("id")),
                "name": summary.get("detailed-sport-info") or summary.get("sport"),
                "raw": summary, "url": url,
            })
        # La transaction n'est validée qu'après import effectif (voir sync()).
        self._pending_transaction = (athlete_id, transaction_url)
        return out

    def fetch_activity_file(self, athlete_id: int, activity: dict):
        """Polar expose le FIT et le TCX de chaque exercice."""
        url = activity.get("url")
        if not url:
            return None
        for suffix, filename in (("/fit", "polar.fit"), ("/tcx", "polar.tcx"),
                                 ("/gpx", "polar.gpx")):
            try:
                status, body, _ = oauth.http_request(
                    url + suffix,
                    headers={"Authorization": f"Bearer {self.access_token(athlete_id)}",
                             "Accept": "*/*"})
                if status == 200 and body:
                    return body, filename
            except oauth.HttpError:
                continue
        return None

    POLAR_SPORT_MAP = {
        "RUNNING": "running", "TRAIL_RUNNING": "trail_running",
        "TREADMILL_RUNNING": "running", "CYCLING": "cycling",
        "ROAD_BIKING": "cycling", "MOUNTAIN_BIKING": "cycling",
        "INDOOR_CYCLING": "cycling", "SWIMMING": "swimming",
        "POOL_SWIMMING": "swimming", "OPEN_WATER_SWIMMING": "swimming",
        "WALKING": "walking", "HIKING": "hiking",
        "STRENGTH_TRAINING": "strength_training", "OTHER_INDOOR": "training",
    }

    @staticmethod
    def _iso_duration(value: str | None) -> float | None:
        """Convertit une durée ISO-8601 (« PT1H23M45.5S ») en secondes."""
        if not value or not value.startswith("PT"):
            return None
        import re
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?", value)
        if not match:
            return None
        hours, minutes, seconds = match.groups()
        return (int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0))

    def to_parsed(self, activity: dict) -> dict:
        raw = activity.get("raw") or {}
        start = raw.get("start-time")
        start_dt = datetime.fromisoformat(start) if start else datetime.now(timezone.utc)
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        heart = raw.get("heart-rate") or {}
        return {
            "format": "polar-api",
            "sport": self.POLAR_SPORT_MAP.get(raw.get("sport", ""), "other"),
            "start_time": start_dt,
            "duration_s": self._iso_duration(raw.get("duration")),
            "distance_m": raw.get("distance"),
            "calories": raw.get("calories"),
            "device": "Polar", "device_name": raw.get("device"),
            "streams": {}, "laps": [],
            "summary_avg_hr": heart.get("average"), "summary_max_hr": heart.get("maximum"),
        }

    def fetch_wellness(self, athlete_id: int, since: datetime,
                       until: datetime | None = None) -> list[dict]:
        """Sommeil et Nightly Recharge (VFC nocturne, FC de repos)."""
        user_id = self._user_id(athlete_id)
        out: dict[str, dict] = {}
        headers = self._headers(athlete_id)
        try:
            sleeps = oauth.http_json(f"{API_BASE}/users/sleep", headers=headers) or {}
            for night in sleeps.get("nights", []):
                date_key = night.get("date")
                if not date_key:
                    continue
                row = out.setdefault(date_key, {"date": date_key, "source": "polar"})
                total = night.get("sleep_end_time") and night.get("sleep_start_time")
                for src, dst, scale in (("light_sleep", "sleep_light_min", 1 / 60),
                                        ("deep_sleep", "sleep_deep_min", 1 / 60),
                                        ("rem_sleep", "sleep_rem_min", 1 / 60),
                                        ("total_interruption_duration", "sleep_awake_min", 1 / 60)):
                    if night.get(src) is not None:
                        row[dst] = round(night[src] * scale, 1)
                if night.get("sleep_score") is not None:
                    row["sleep_score"] = night["sleep_score"]
                pieces = [row.get(k) or 0 for k in
                          ("sleep_light_min", "sleep_deep_min", "sleep_rem_min")]
                if any(pieces):
                    row["sleep_total_min"] = round(sum(pieces), 1)
        except oauth.HttpError:
            pass
        try:
            recharge = oauth.http_json(f"{API_BASE}/users/nightly-recharge",
                                       headers=headers) or {}
            for night in recharge.get("recharges", []):
                date_key = night.get("date")
                if not date_key:
                    continue
                row = out.setdefault(date_key, {"date": date_key, "source": "polar"})
                if night.get("heart_rate_avg"):
                    row["resting_hr"] = night["heart_rate_avg"]
                if night.get("hrv_avg"):
                    row["hrv_rmssd"] = night["hrv_avg"]
                    import math
                    row["hrv_ln_rmssd"] = round(math.log(night["hrv_avg"]), 3)
                if night.get("breathing_rate_avg"):
                    row["respiration_avg"] = night["breathing_rate_avg"]
        except oauth.HttpError:
            pass
        return list(out.values())

    def sync(self, athlete_id: int, days: int = 30) -> dict:
        """Surcharge : valide la transaction Polar une fois l'import réussi."""
        self._pending_transaction = None
        result = super().sync(athlete_id, days)
        pending = getattr(self, "_pending_transaction", None)
        if pending and result.get("status") in ("ok", "partial"):
            try:
                self._commit(*pending)
                result["message"] += " — transaction Polar validée"
            except Exception as exc:
                result["message"] += f" — transaction non validée ({exc})"
        return result
