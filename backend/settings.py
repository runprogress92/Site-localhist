"""Configuration de l'application.

Trois sources, par priorité croissante :
1. valeurs par défaut ci-dessous ;
2. fichier ``config.json`` à la racine du projet ;
3. variables d'environnement ``ATHLYTICS_*``.

Les clés d'API des montres peuvent aussi être saisies depuis l'interface
(page Connexions) : elles sont alors stockées dans la table ``settings`` de
la base, ce qui évite d'avoir à éditer un fichier à la main.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

DEFAULTS = {
    "host": "127.0.0.1",
    "port": 8420,
    "open_browser": True,
    "locale": "fr-FR",
    "timezone": "Europe/Paris",
    "units": "metric",
    "week_start": "monday",
    "coach_name": "Entraîneur",
    "providers": {
        "garmin": {"client_id": "", "client_secret": "", "redirect_uri": ""},
        "polar": {"client_id": "", "client_secret": "", "redirect_uri": ""},
        "coros": {"client_id": "", "client_secret": "", "redirect_uri": ""},
    },
    "readiness_weights": {
        "hrv": 0.30, "rhr": 0.15, "sleep": 0.20,
        "subjective": 0.20, "load": 0.15,
    },
    "thresholds": {
        "acwr_high": 1.50, "acwr_low": 0.80, "monotony": 2.0,
        "strain": 6000, "ctl_ramp": 8.0, "sleep_need_min": 480,
    },
}


def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


_cache: dict | None = None


def load(force: bool = False) -> dict:
    global _cache
    if _cache is not None and not force:
        return _cache
    config = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            config = _deep_merge(config, json.loads(CONFIG_PATH.read_text("utf-8")))
        except json.JSONDecodeError as exc:
            print(f"[config] config.json illisible ({exc}), valeurs par défaut utilisées.")
    if os.environ.get("ATHLYTICS_PORT"):
        config["port"] = int(os.environ["ATHLYTICS_PORT"])
    if os.environ.get("ATHLYTICS_HOST"):
        config["host"] = os.environ["ATHLYTICS_HOST"]
    for provider in ("garmin", "polar", "coros"):
        for field in ("client_id", "client_secret", "redirect_uri"):
            env_key = f"ATHLYTICS_{provider.upper()}_{field.upper()}"
            if os.environ.get(env_key):
                config["providers"][provider][field] = os.environ[env_key]
    _cache = config
    return config


def base_url() -> str:
    config = load()
    return f"http://{config['host']}:{config['port']}"


def provider_config(key: str) -> dict:
    """Config d'un connecteur : fichier/env complété par la base."""
    from . import db
    config = load()
    stored = {}
    try:
        stored = db.get_setting(f"provider.{key}", {}) or {}
    except Exception:
        pass
    merged = _deep_merge(config["providers"].get(key, {}), stored)
    if not merged.get("redirect_uri"):
        merged["redirect_uri"] = f"{base_url()}/api/devices/{key}/callback"
    return merged


def save_provider_config(key: str, values: dict) -> dict:
    from . import db
    allowed = {k: v for k, v in values.items()
               if k in ("client_id", "client_secret", "redirect_uri")}
    db.set_setting(f"provider.{key}", allowed)
    return provider_config(key)


def public_config() -> dict:
    """Version transmissible au navigateur : aucun secret."""
    config = load()
    return {
        "locale": config["locale"], "timezone": config["timezone"],
        "units": config["units"], "week_start": config["week_start"],
        "coach_name": config["coach_name"],
        "thresholds": config["thresholds"],
        "readiness_weights": config["readiness_weights"],
        "base_url": base_url(),
    }
