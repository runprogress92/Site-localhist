"""Registre des connecteurs disponibles."""
from __future__ import annotations

from .. import settings
from .coros import CorosProvider
from .garmin import GarminProvider
from .polar import PolarProvider

PROVIDER_CLASSES = {
    "garmin": GarminProvider,
    "polar": PolarProvider,
    "coros": CorosProvider,
}


def get(key: str):
    cls = PROVIDER_CLASSES.get(key)
    if cls is None:
        raise KeyError(f"Connecteur inconnu : {key}")
    return cls(settings.provider_config(key))


def all_providers() -> list:
    return [get(key) for key in PROVIDER_CLASSES]


def describe_all() -> list[dict]:
    out = []
    for provider in all_providers():
        info = provider.describe()
        info["redirect_uri"] = provider.redirect_uri
        out.append(info)
    return out
