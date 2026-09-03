"""Connecteur Garmin — Health API et Activity API.

Garmin fonctionne sur un modèle **push** : une fois l'utilisateur autorisé,
Garmin appelle les URL de rappel déclarées dans la console développeur dès
qu'une donnée est disponible. La méthode ``pull`` (backfill) reste possible
et sert au rattrapage d'historique.

Authentification : **OAuth 1.0a**, chaque requête étant signée en HMAC-SHA1
avec la clé consommateur et le secret du jeton.

Pour utiliser ce connecteur il faut un compte au *Garmin Connect Developer
Program* (accès partenaire sur demande). Sans clé, l'import de fichiers
``.fit`` exportés depuis Garmin Connect reste pleinement fonctionnel — le
décodeur FIT intégré lit exactement les mêmes données.
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta, timezone

from .. import db
from . import oauth
from .base import Provider, ProviderError

REQUEST_TOKEN_URL = "https://connectapi.garmin.com/oauth-service/oauth/request_token"
AUTHORIZE_URL = "https://connect.garmin.com/oauthConfirm"
ACCESS_TOKEN_URL = "https://connectapi.garmin.com/oauth-service/oauth/access_token"
API_BASE = "https://apis.garmin.com/wellness-api/rest"

# La Health API impose des fenêtres de 24 h maximum par requête de backfill.
MAX_WINDOW_S = 86400


class GarminProvider(Provider):
    key = "garmin"
    label = "Garmin"
    auth_kind = "oauth1"
    doc_url = "https://developer.garmin.com/gc-developer-program/health-api/"
    supports_push = True
    color = "#007cc3"

    # --------------------------------------------------------- autorisation
    def authorize_url(self, athlete_id: int, state: str) -> str:
        """Étape 1 : jeton de requête, puis redirection vers Garmin."""
        self.require_config()
        callback = f"{self.redirect_uri}?state={urllib.parse.quote(state)}"
        status, body, _ = oauth.oauth1_call(
            "POST", REQUEST_TOKEN_URL, self.client_id, self.client_secret,
            extra_oauth={"oauth_callback": callback})
        parsed = oauth.parse_qs_body(body)
        token = parsed.get("oauth_token")
        secret = parsed.get("oauth_token_secret")
        if not token:
            raise ProviderError(f"Garmin n'a pas renvoyé de jeton de requête : {body[:200]}")
        db.upsert("oauth_states", {
            "state": state, "provider": self.key, "athlete_id": athlete_id,
            "verifier": secret, "request_token": token}, ["state"])
        return f"{AUTHORIZE_URL}?oauth_token={urllib.parse.quote(token)}"

    def handle_callback(self, athlete_id: int, params: dict, stored: dict) -> dict:
        """Étape 2 : échange du jeton de requête vérifié contre un jeton d'accès."""
        self.require_config()
        verifier = params.get("oauth_verifier")
        token = params.get("oauth_token") or stored.get("request_token")
        secret = stored.get("verifier") or ""
        if not token:
            raise ProviderError("Rappel Garmin sans oauth_token.")
        status, body, _ = oauth.oauth1_call(
            "POST", ACCESS_TOKEN_URL, self.client_id, self.client_secret,
            token=token, token_secret=secret,
            extra_oauth={"oauth_verifier": verifier} if verifier else None)
        parsed = oauth.parse_qs_body(body)
        access = parsed.get("oauth_token")
        access_secret = parsed.get("oauth_token_secret")
        if not access:
            raise ProviderError(f"Échange de jeton Garmin refusé : {body[:200]}")
        user_id = self._user_id(access, access_secret)
        self.save_account(athlete_id, access_token=access, token_secret=access_secret,
                          provider_user_id=user_id, status="connected",
                          token_type="oauth1")
        return {"provider": self.key, "status": "connected", "user_id": user_id}

    def _user_id(self, token: str, secret: str) -> str | None:
        try:
            _s, body, _h = oauth.oauth1_call(
                "GET", f"{API_BASE}/user/id", self.client_id, self.client_secret,
                token=token, token_secret=secret)
            return json.loads(body).get("userId")
        except Exception:
            return None

    # ------------------------------------------------------------- requêtes
    def _get(self, athlete_id: int, path: str, params: dict) -> list | dict:
        account = self.account(athlete_id)
        if not account or not account.get("access_token"):
            raise ProviderError("Garmin : athlète non connecté.")
        url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
        _status, body, _headers = oauth.oauth1_call(
            "GET", url, self.client_id, self.client_secret,
            token=account["access_token"], token_secret=account.get("token_secret") or "")
        return json.loads(body) if body else []

    @staticmethod
    def _windows(since: datetime, until: datetime):
        """Découpe l'intervalle en fenêtres de 24 h (contrainte Garmin)."""
        start = int(since.timestamp())
        end = int(until.timestamp())
        while start < end:
            stop = min(start + MAX_WINDOW_S, end)
            yield start, stop
            start = stop

    def list_activities(self, athlete_id: int, since: datetime,
                        until: datetime | None = None) -> list[dict]:
        self.require_config()
        until = until or datetime.now(timezone.utc)
        out: list[dict] = []
        for start, stop in self._windows(since, until):
            batch = self._get(athlete_id, "/activities", {
                "uploadStartTimeInSeconds": start,
                "uploadEndTimeInSeconds": stop,
            })
            for item in batch or []:
                out.append({
                    "external_id": item.get("summaryId") or item.get("activityId"),
                    "name": item.get("activityName"),
                    "raw": item,
                })
        return out

    def fetch_activity_file(self, athlete_id: int, activity: dict):
        """Garmin expose le détail seconde par seconde via /activityDetails."""
        raw = activity.get("raw") or {}
        summary_id = raw.get("summaryId")
        if not summary_id:
            return None
        start = raw.get("startTimeInSeconds")
        if not start:
            return None
        details = self._get(athlete_id, "/activityDetails", {
            "uploadStartTimeInSeconds": int(start) - 60,
            "uploadEndTimeInSeconds": int(start) + int(raw.get("durationInSeconds", 0)) + 60,
        })
        for detail in details or []:
            if detail.get("summaryId") == summary_id:
                activity["details"] = detail
                return None       # traité par to_parsed, pas de fichier binaire
        return None

    # ------------------------------------------------ conversion des résumés
    SPORT_MAP = {
        "RUNNING": "running", "TRAIL_RUNNING": "trail_running",
        "TREADMILL_RUNNING": "running", "INDOOR_RUNNING": "running",
        "CYCLING": "cycling", "ROAD_BIKING": "cycling",
        "MOUNTAIN_BIKING": "cycling", "INDOOR_CYCLING": "cycling",
        "GRAVEL_CYCLING": "cycling", "VIRTUAL_RIDE": "cycling",
        "LAP_SWIMMING": "swimming", "OPEN_WATER_SWIMMING": "swimming",
        "WALKING": "walking", "HIKING": "hiking",
        "STRENGTH_TRAINING": "strength_training", "CARDIO_TRAINING": "training",
        "CROSS_COUNTRY_SKIING": "cross_country_skiing", "ROWING": "rowing",
    }

    def to_parsed(self, activity: dict) -> dict:
        raw = activity.get("raw") or {}
        detail = activity.get("details") or {}
        start = datetime.fromtimestamp(
            raw.get("startTimeInSeconds", 0), tz=timezone.utc)
        offset = raw.get("startTimeOffsetInSeconds", 0)
        streams: dict[str, list] = {}
        samples = detail.get("samples") or []
        if samples:
            base = samples[0].get("startTimeInSeconds", raw.get("startTimeInSeconds", 0))
            span = int(samples[-1].get("startTimeInSeconds", base) - base) + 1
            span = max(span, len(samples))
            keys = {"heartRate": "heart_rate", "powerInWatts": "power",
                    "bikeCadenceInRPM": "cadence", "stepsPerMinute": "cadence",
                    "speedMetersPerSecond": "speed", "elevationInMeters": "altitude",
                    "totalDistanceInMeters": "distance", "airTemperatureCelcius": "temperature",
                    "latitudeInDegree": "lat", "longitudeInDegree": "lon"}
            for target in set(keys.values()):
                streams[target] = [None] * span
            for sample in samples:
                i = int(sample.get("startTimeInSeconds", base) - base)
                if not (0 <= i < span):
                    continue
                for src, dst in keys.items():
                    if sample.get(src) is not None:
                        streams[dst][i] = sample[src]
            streams = {k: v for k, v in streams.items() if any(x is not None for x in v)}
            streams["time"] = list(range(span))
        return {
            "format": "garmin-api",
            "sport": self.SPORT_MAP.get(raw.get("activityType", ""), "other"),
            "start_time": start + timedelta(seconds=offset or 0),
            "duration_s": raw.get("durationInSeconds"),
            "moving_time_s": raw.get("durationInSeconds"),
            "distance_m": raw.get("distanceInMeters"),
            "elevation_gain_m": raw.get("totalElevationGainInMeters"),
            "elevation_loss_m": raw.get("totalElevationLossInMeters"),
            "calories": raw.get("activeKilocalories"),
            "device": "Garmin", "device_name": raw.get("deviceName"),
            "streams": streams, "laps": [],
        }

    # ------------------------------------------------------------ bien-être
    def fetch_wellness(self, athlete_id: int, since: datetime,
                       until: datetime | None = None) -> list[dict]:
        """Agrège /dailies, /sleeps et /stressDetails en lignes quotidiennes."""
        until = until or datetime.now(timezone.utc)
        by_date: dict[str, dict] = {}

        def slot(date_key: str) -> dict:
            return by_date.setdefault(date_key, {"date": date_key, "source": "garmin"})

        for start, stop in self._windows(since, until):
            window = {"uploadStartTimeInSeconds": start, "uploadEndTimeInSeconds": stop}
            try:
                for daily in self._get(athlete_id, "/dailies", window) or []:
                    date_key = daily.get("calendarDate")
                    if not date_key:
                        continue
                    row = slot(date_key)
                    row["resting_hr"] = daily.get("restingHeartRateInBeatsPerMinute")
                    row["steps"] = daily.get("steps")
                    row["active_kcal"] = daily.get("activeKilocalories")
                    row["total_kcal"] = daily.get("bmrKilocalories", 0) + \
                        (daily.get("activeKilocalories") or 0)
                    row["stress_avg"] = daily.get("averageStressLevel")
                    row["body_battery_max"] = daily.get("maxHeartRateInBeatsPerMinute")
                    row["respiration_avg"] = daily.get("averageRespirationValue")
            except Exception:
                pass
            try:
                for sleep in self._get(athlete_id, "/sleeps", window) or []:
                    date_key = sleep.get("calendarDate")
                    if not date_key:
                        continue
                    row = slot(date_key)
                    total = sleep.get("durationInSeconds")
                    row["sleep_total_min"] = round(total / 60, 1) if total else None
                    for src, dst in (("deepSleepDurationInSeconds", "sleep_deep_min"),
                                     ("remSleepInSeconds", "sleep_rem_min"),
                                     ("lightSleepDurationInSeconds", "sleep_light_min"),
                                     ("awakeDurationInSeconds", "sleep_awake_min")):
                        value = sleep.get(src)
                        if value is not None:
                            row[dst] = round(value / 60, 1)
                    row["sleep_score"] = (sleep.get("overallSleepScore") or {}).get("value") \
                        if isinstance(sleep.get("overallSleepScore"), dict) else sleep.get("overallSleepScore")
                    spo2 = sleep.get("averageSpO2Value")
                    if spo2:
                        row["spo2_avg"] = spo2
            except Exception:
                pass
        return list(by_date.values())

    # -------------------------------------------------------------- webhook
    def handle_push(self, payload: dict) -> dict:
        """Traite une notification push (ping ou données complètes).

        Garmin poste soit un *ping* (liste d'URL de rappel à interroger),
        soit directement les données (*push*), selon la configuration de la
        console développeur. Les deux cas sont gérés.
        """
        handled = {"activities": 0, "dailies": 0, "sleeps": 0}
        for kind in ("activities", "activityDetails", "dailies", "sleeps"):
            items = payload.get(kind) or []
            for item in items:
                user_id = item.get("userId")
                account = db.query_one(
                    "SELECT athlete_id FROM provider_accounts"
                    " WHERE provider='garmin' AND provider_user_id = ?", (user_id,))
                if not account:
                    continue
                athlete_id = account["athlete_id"]
                if kind == "activities":
                    try:
                        parsed = self.to_parsed({"raw": item})
                        from .. import profiles
                        from ..ingest import pipeline
                        ctx = profiles.athlete_context(
                            athlete_id, parsed["start_time"].date().isoformat())
                        metrics = pipeline.analyze(parsed, ctx)
                        pipeline.store_activity(
                            athlete_id, parsed, metrics, provider=self.key,
                            external_id=str(item.get("summaryId")))
                        pipeline.rebuild_daily(athlete_id)
                        handled["activities"] += 1
                    except Exception:
                        pass
        return handled
