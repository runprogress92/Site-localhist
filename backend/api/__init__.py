"""Enregistrement de toutes les routes de l'API.

L'import de ce paquet suffit : chaque module s'enregistre auprès du routeur
global au moment de son import.
"""
from . import (activities, admin, athletes, devices, lab, metrics, planning,
               wellness)  # noqa: F401

__all__ = ["activities", "admin", "athletes", "devices", "lab", "metrics",
           "planning", "wellness"]
