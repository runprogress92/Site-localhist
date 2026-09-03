"""Connecteur COROS — Open API.

COROS expose une API OAuth 2.0 doublée d'un mécanisme de *webhook* : après
autorisation, chaque nouvelle activité est notifiée à l'URL déclarée. Les
activités sont téléchargeables au format FIT, ce qui permet de réutiliser
intégralement le décodeur interne.

Inscription développeur : https://open.coros.com
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .. import db
from . import oauth
from .base import Provider, ProviderError

AUTHORIZE_URL = "https://open.coros.com/oauth2/authorize"
TOKEN_URL = "https://open.coros.com/oauth2/accesstoken"
REFRESH_URL = "https://open.coros.com/oauth2/refresh-token"
API_BASE = "https://open.coros.com/v2/coros"


class CorosProvider(Provider):
    key = "coros"
    label = "COROS"
    auth_kind = "oauth2"
    doc_url = "https://open.coros.com"
    scopes = "workout,daily"
    supports_push = True
    color = "#f26722"

    def authorize_url(self, athlete_id: int, state: str) -> str:
        self.require_config()
        db.upsert("oauth_states", {"state": state, "provider": self.key,
                                   "athlete_id": athlete_id}, ["state"])
        return oauth.build_authorize_url(
            AUTHORIZE_URL, self.client_id, self.redirect_uri, state=state)

    def handle_callback(self, athlete_id: int, params: dict, stored: dict) -> dict:
        self.require_config()
        code = params.get("code")
        if not code:
            raise ProviderError(f"Rappel COROS sans code : {params.get('error', '')}")
        token = oauth.exchange_code(TOKEN_URL, self.client_id, self.client_secret,
                                    code, self.redirect_uri, auth_style="body")
        access = token.get("access_token")
        if not access:
            raise ProviderError(f"COROS n'a pas délivré de jeton : {token}")
        expires_at = None
        if token.get("expires_in"):
            expires_at = (datetime.now(timezone.utc) +
                          timedelta(seconds=int(token["expires_in"]))).strftime(
                              "%Y-%m-%dT%H:%M:%SZ")
        self.save_account(athlete_id, access_token=access,
                          refresh_token=token.get("refresh_token"),
                          provider_user_id=str(token.get("openId") or ""),
                          expires_at=expires_at, status="connected",
                          token_type="Bearer", scope=self.scopes)
        return {"provider": self.key, "status": "connected",
                "user_id": token.get("openId")}

    def refresh(self, athlete_id: int, account: dict) -> str:
        token = oauth.refresh_token(REFRESH_URL, self.client_id, self.client_secret,
                                    account["refresh_token"], auth_style="body")
        access = token.get("access_token")
        if not access:
            self.save_account(athlete_id, status="expired",
                              last_error="Rafraîchissement refusé")
            raise ProviderError("COROS : rafraîchissement du jeton refusé, "
                                "reconnexion nécessaire.")
        expires_at = (datetime.now(timezone.utc) +
                      timedelta(seconds=int(token.get("expires_in", 3600)))).strftime(
                          "%Y-%m-%dT%H:%M:%SZ")
        self.save_account(athlete_id, access_token=access,
                          refresh_token=token.get("refresh_token") or account["refresh_token"],
                          expires_at=expires_at, status="connected")
        return access

    def _params(self, athlete_id: int) -> dict:
        account = self.account(athlete_id)
        return {"token": self.access_token(athlete_id),
                "openId": account.get("provider_user_id") or ""}

    def list_activities(self, athlete_id: int, since: datetime,
                        until: datetime | None = None) -> list[dict]:
        self.require_config()
        import urllib.parse
        until = until or datetime.now(timezone.utc)
        query = {**self._params(athlete_id),
                 "startDate": since.strftime("%Y%m%d"),
                 "endDate": until.strftime("%Y%m%d")}
        payload = oauth.http_json(
            f"{API_BASE}/sport/list?{urllib.parse.urlencode(query)}",
            headers={"Accept": "application/json"})
        if not payload or payload.get("result") not in ("0000", 0, None):
            raise ProviderError(f"COROS a refusé la requête : {payload}")
        items = (payload.get("data") or {}).get("dataList") or []
        return [{"external_id": str(item.get("labelId")),
                 "name": item.get("name"), "raw": item} for item in items]

    def fetch_activity_file(self, athlete_id: int, activity: dict):
        """Récupère le FIT via l'URL de téléchargement fournie par COROS."""
        import urllib.parse
        raw = activity.get("raw") or {}
        label = raw.get("labelId")
        if not label:
            return None
        query = {**self._params(athlete_id), "labelId": label,
                 "sportType": raw.get("sportType", ""), "fileType": "4"}  # 4 = FIT
        try:
            payload = oauth.http_json(
                f"{API_BASE}/sport/detail?{urllib.parse.urlencode(query)}",
                headers={"Accept": "application/json"})
        except oauth.HttpError:
            return None
        url = ((payload or {}).get("data") or {}).get("fitUrl") or \
            ((payload or {}).get("data") or {}).get("url")
        if not url:
            return None
        try:
            status, body, _ = oauth.http_request(url)
            if status == 200 and body:
                return body, f"coros-{label}.fit"
        except oauth.HttpError:
            return None
        return None

    COROS_SPORT_MAP = {
        8: "running", 9: "running", 10: "trail_running", 11: "running",
        100: "cycling", 101: "cycling", 102: "cycling",
        200: "swimming", 201: "swimming",
        13: "hiking", 14: "walking", 15: "training",
    }

    def to_parsed(self, activity: dict) -> dict:
        raw = activity.get("raw") or {}
        date_key = str(raw.get("date") or "")
        start_time = str(raw.get("startTime") or 0)
        try:
            start = datetime.fromtimestamp(int(start_time), tz=timezone.utc)
        except (ValueError, OSError):
            start = datetime.strptime(date_key, "%Y%m%d").replace(tzinfo=timezone.utc) \
                if len(date_key) == 8 else datetime.now(timezone.utc)
        return {
            "format": "coros-api",
            "sport": self.COROS_SPORT_MAP.get(raw.get("sportType"), "other"),
            "start_time": start,
            "duration_s": raw.get("totalTime"),
            "distance_m": raw.get("distance"),
            "calories": raw.get("calories"),
            "elevation_gain_m": raw.get("ascent"),
            "elevation_loss_m": raw.get("descent"),
            "device": "COROS", "device_name": raw.get("deviceName"),
            "streams": {}, "laps": [],
        }

    def fetch_wellness(self, athlete_id: int, since: datetime,
                       until: datetime | None = None) -> list[dict]:
        import urllib.parse
        until = until or datetime.now(timezone.utc)
        query = {**self._params(athlete_id),
                 "startDate": since.strftime("%Y%m%d"),
                 "endDate": until.strftime("%Y%m%d")}
        try:
            payload = oauth.http_json(
                f"{API_BASE}/daily/activity?{urllib.parse.urlencode(query)}",
                headers={"Accept": "application/json"})
        except oauth.HttpError:
            return []
        out = []
        for item in ((payload or {}).get("data") or {}).get("dataList") or []:
            date_key = str(item.get("date") or "")
            if len(date_key) != 8:
                continue
            iso = f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:]}"
            row = {"date": iso, "source": "coros"}
            if item.get("steps"):
                row["steps"] = item["steps"]
            if item.get("calorie"):
                row["active_kcal"] = item["calorie"]
            if item.get("rhr"):
                row["resting_hr"] = item["rhr"]
            if item.get("sleepTime"):
                row["sleep_total_min"] = round(item["sleepTime"] / 60, 1)
            out.append(row)
        return out

    def handle_push(self, payload: dict) -> dict:
        """Webhook COROS : liste d'activités nouvellement disponibles."""
        from ..ingest import pipeline
        from .. import profiles
        count = 0
        for item in payload.get("sportDataList") or payload.get("data") or []:
            open_id = item.get("openId")
            account = db.query_one(
                "SELECT athlete_id FROM provider_accounts"
                " WHERE provider='coros' AND provider_user_id = ?", (open_id,))
            if not account:
                continue
            athlete_id = account["athlete_id"]
            activity = {"external_id": str(item.get("labelId")), "raw": item}
            try:
                fetched = self.fetch_activity_file(athlete_id, activity)
                parsed = (pipeline.parse_file(*fetched) if fetched
                          else self.to_parsed(activity))
                ctx = profiles.athlete_context(
                    athlete_id, parsed["start_time"].date().isoformat())
                metrics = pipeline.analyze(parsed, ctx)
                pipeline.store_activity(athlete_id, parsed, metrics,
                                        provider=self.key,
                                        external_id=activity["external_id"])
                pipeline.rebuild_daily(athlete_id)
                count += 1
            except Exception:
                continue
        return {"activities": count}
