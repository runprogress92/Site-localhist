"""Socle commun aux connecteurs de montres.

Chaque marque expose une API différente, mais la logique de synchronisation
est la même : autoriser → obtenir un jeton → lister les activités depuis une
date → télécharger le détail (idéalement le fichier FIT) → passer au
pipeline d'analyse. Cette classe factorise ce déroulé ; chaque connecteur
n'implémente que ce qui lui est propre.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import db
from ..ingest import pipeline


class ProviderError(Exception):
    """Erreur fonctionnelle d'un connecteur (identifiants, quota, format)."""


class NotConfigured(ProviderError):
    """Le connecteur n'a pas d'identifiants d'application configurés."""


class Provider:
    key: str = "base"
    label: str = "Fournisseur"
    auth_kind: str = "oauth2"          # oauth1 | oauth2 | file
    doc_url: str = ""
    scopes: str = ""
    supports_push: bool = False
    color: str = "#888"

    def __init__(self, config: dict):
        self.config = config or {}

    # ---------------------------------------------------------- utilitaires
    @property
    def client_id(self) -> str:
        return self.config.get("client_id") or ""

    @property
    def client_secret(self) -> str:
        return self.config.get("client_secret") or ""

    @property
    def redirect_uri(self) -> str:
        return self.config.get("redirect_uri") or ""

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def require_config(self) -> None:
        if not self.is_configured():
            raise NotConfigured(
                f"{self.label} : aucune clé d'application enregistrée. "
                f"Renseignez client_id et client_secret dans Réglages → "
                f"Connexions, après inscription sur {self.doc_url}.")

    # ------------------------------------------------------------- jetons
    def account(self, athlete_id: int) -> dict | None:
        return db.query_one(
            "SELECT * FROM provider_accounts WHERE athlete_id = ? AND provider = ?",
            (athlete_id, self.key))

    def save_account(self, athlete_id: int, **fields) -> None:
        payload = {"athlete_id": athlete_id, "provider": self.key,
                   "updated_at": db.now_iso(), **fields}
        db.upsert("provider_accounts", payload, ["athlete_id", "provider"])

    def disconnect(self, athlete_id: int) -> None:
        db.execute(
            "UPDATE provider_accounts SET status='disconnected', access_token=NULL,"
            " refresh_token=NULL, token_secret=NULL, updated_at=?"
            " WHERE athlete_id=? AND provider=?",
            (db.now_iso(), athlete_id, self.key))

    def token_expired(self, account: dict) -> bool:
        expires = account.get("expires_at")
        if not expires:
            return False
        try:
            return datetime.fromisoformat(expires.replace("Z", "+00:00")) <= \
                datetime.now(timezone.utc) + timedelta(minutes=2)
        except ValueError:
            return False

    def access_token(self, athlete_id: int) -> str:
        account = self.account(athlete_id)
        if not account or not account.get("access_token"):
            raise ProviderError(f"{self.label} : compte non connecté pour cet athlète.")
        if self.token_expired(account) and account.get("refresh_token"):
            return self.refresh(athlete_id, account)
        return account["access_token"]

    # ------------------------------------------------- à implémenter
    def authorize_url(self, athlete_id: int, state: str) -> str:
        raise NotImplementedError

    def handle_callback(self, athlete_id: int, params: dict, stored: dict) -> dict:
        raise NotImplementedError

    def refresh(self, athlete_id: int, account: dict) -> str:
        raise ProviderError(f"{self.label} : rafraîchissement de jeton non pris en charge.")

    def list_activities(self, athlete_id: int, since: datetime,
                        until: datetime | None = None) -> list[dict]:
        raise NotImplementedError

    def fetch_activity_file(self, athlete_id: int, activity: dict) -> tuple[bytes, str] | None:
        """Télécharge le fichier brut (FIT/TCX/GPX) si l'API le propose."""
        return None

    def fetch_wellness(self, athlete_id: int, since: datetime,
                       until: datetime | None = None) -> list[dict]:
        return []

    # ---------------------------------------------------- synchronisation
    def sync(self, athlete_id: int, days: int = 30) -> dict:
        """Déroulé complet de synchronisation, journalisé en base."""
        started = db.now_iso()
        log_id = db.insert("sync_log", {
            "provider": self.key, "athlete_id": athlete_id,
            "started_at": started, "status": "running"})
        imported = skipped = failed = 0
        errors: list[str] = []
        since = datetime.now(timezone.utc) - timedelta(days=days)
        try:
            activities = self.list_activities(athlete_id, since)
            for activity in activities:
                external_id = str(activity.get("external_id") or activity.get("id") or "")
                if external_id and db.query_one(
                        "SELECT id FROM activities WHERE athlete_id=? AND provider=?"
                        " AND external_id=?", (athlete_id, self.key, external_id)):
                    skipped += 1
                    continue
                try:
                    fetched = self.fetch_activity_file(athlete_id, activity)
                    if fetched:
                        data, filename = fetched
                        parsed = pipeline.parse_file(data, filename)
                    else:
                        parsed = self.to_parsed(activity)
                    from .. import profiles
                    ctx = profiles.athlete_context(
                        athlete_id, parsed["start_time"].date().isoformat())
                    metrics = pipeline.analyze(parsed, ctx)
                    pipeline.store_activity(
                        athlete_id, parsed, metrics, provider=self.key,
                        external_id=external_id, name=activity.get("name"))
                    imported += 1
                except Exception as exc:            # une séance ne bloque pas les autres
                    failed += 1
                    errors.append(f"{external_id}: {exc}")

            for entry in self.fetch_wellness(athlete_id, since):
                entry["athlete_id"] = athlete_id
                entry.setdefault("source", self.key)
                try:
                    db.upsert("wellness", entry, ["athlete_id", "date"])
                except Exception as exc:
                    errors.append(f"wellness {entry.get('date')}: {exc}")

            if imported:
                pipeline.rebuild_daily(athlete_id)
            status = "ok" if not failed else "partial"
            message = f"{imported} importée(s), {skipped} déjà présente(s), {failed} en échec"
        except Exception as exc:
            status = "error"
            message = str(exc)
            errors.append(message)

        db.update("sync_log", log_id, {
            "finished_at": db.now_iso(), "status": status, "imported": imported,
            "skipped": skipped, "failed": failed, "message": message,
            "detail": json.dumps(errors[:20], ensure_ascii=False) if errors else None})
        self.save_account(athlete_id, last_sync_at=db.now_iso(),
                          last_error=None if status == "ok" else message)
        return {"status": status, "imported": imported, "skipped": skipped,
                "failed": failed, "message": message, "errors": errors[:10]}

    def to_parsed(self, activity: dict) -> dict:
        """Convertit un résumé d'API en structure du pipeline (sans fichier)."""
        raise ProviderError(
            f"{self.label} : ni fichier téléchargeable ni conversion de résumé "
            "disponible pour cette activité.")

    def describe(self) -> dict:
        return {
            "key": self.key, "label": self.label, "auth_kind": self.auth_kind,
            "doc_url": self.doc_url, "scopes": self.scopes,
            "configured": self.is_configured(), "supports_push": self.supports_push,
            "color": self.color,
        }
