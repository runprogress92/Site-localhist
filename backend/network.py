"""Accès depuis le réseau local.

Par défaut, le serveur n'écoute que sur ``127.0.0.1`` : il est injoignable
depuis un téléphone, et c'est voulu — aucune donnée ne sort de la machine.
Pour consulter l'application sur un téléphone, il faut ouvrir l'écoute au
réseau local, et cette ouverture doit s'accompagner d'une protection : les
données de santé d'athlètes ne doivent pas être lisibles par tout le monde
sur le Wi-Fi d'un club.

Le modèle retenu : un code à six chiffres, demandé une fois par appareil,
mémorisé ensuite dans un cookie. Les requêtes venant de la machine elle-même
(boucle locale) en sont dispensées, afin que le poste de l'entraîneur
continue de fonctionner sans rien saisir.

**Limite à connaître** : l'échange se fait en HTTP simple. Le code protège
d'un accès opportuniste depuis le même réseau, il ne chiffre rien. Sur un
réseau public, mieux vaut s'abstenir.
"""
from __future__ import annotations

import ipaddress
import secrets
import socket
import threading
import time

from . import db

COOKIE_NAME = "athlytics_access"
SETTING_ENABLED = "lan.enabled"
SETTING_CODE = "lan.code"

# Six chiffres, c'est un million de combinaisons : à pleine vitesse sur un
# réseau local, un script en viendrait à bout. On impose donc une attente
# après quelques essais ratés, qui double à chaque fois. Cinq essais restent
# gratuits — personne ne doit être puni pour une faute de frappe — puis
# l'attente rend la recherche exhaustive hors de portée.
FREE_ATTEMPTS = 5
MAX_DELAY_S = 300.0
_failures: dict[str, tuple[int, float]] = {}
_failures_lock = threading.Lock()


# ------------------------------------------------- adresse réellement servie
# Les réglages conservent le port *souhaité*. Le serveur peut en avoir choisi
# un autre si celui-là était occupé, et « run.py --lan » ouvre l'écoute sans
# rien écrire dans les réglages. L'interface doit afficher l'adresse vraie,
# pas celle demandée : on la note au démarrage.
BOUND: dict = {"host": "127.0.0.1", "port": None}


def set_bound(host: str, port: int) -> None:
    BOUND["host"] = host
    BOUND["port"] = int(port)


def bound_port(fallback: int) -> int:
    return int(BOUND["port"]) if BOUND["port"] else int(fallback)


def listening_on_lan() -> bool:
    """L'écoute est-elle ouverte au réseau, ou limitée à la boucle locale ?"""
    return BOUND["host"] in ("0.0.0.0", "::", "")


# ------------------------------------------------------------- adresses
def local_ip() -> str | None:
    """Adresse de la machine sur le réseau local.

    On ouvre une socket UDP « vers » une adresse publique : aucun paquet
    n'est émis, mais le système choisit l'interface qu'il utiliserait, et
    nous renseigne donc sur l'adresse visible par les autres appareils du
    réseau. Interroger le nom d'hôte renverrait souvent 127.0.1.1.
    """
    for probe in ("10.255.255.255", "8.8.8.8", "192.168.1.1"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(0.3)
            sock.connect((probe, 1))
            address = sock.getsockname()[0]
            if address and not address.startswith("127."):
                return address
        except OSError:
            continue
        finally:
            sock.close()
    return None


def all_local_ips() -> list[str]:
    """Toutes les adresses locales plausibles, la principale en tête.

    Une machine peut être à la fois en Wi-Fi et sur un câble : proposer les
    deux évite d'avoir à deviner laquelle le téléphone peut joindre.
    """
    found: list[str] = []
    primary = local_ip()
    if primary:
        found.append(primary)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = info[4][0]
            if address.startswith("127.") or address in found:
                continue
            found.append(address)
    except OSError:
        pass
    return found


def is_private(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_private
    except ValueError:
        return False


def is_loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:
        return address in ("localhost", "")


# ---------------------------------------------------------- code d'accès
def lan_enabled() -> bool:
    return bool(db.get_setting(SETTING_ENABLED, False))


def access_code() -> str:
    """Code à six chiffres, créé à la première demande."""
    code = db.get_setting(SETTING_CODE)
    if not code:
        code = f"{secrets.randbelow(900000) + 100000}"
        db.set_setting(SETTING_CODE, code)
    return str(code)


def rotate_code() -> str:
    code = f"{secrets.randbelow(900000) + 100000}"
    db.set_setting(SETTING_CODE, code)
    return code


def enable_lan(enabled: bool) -> dict:
    db.set_setting(SETTING_ENABLED, bool(enabled))
    return {"enabled": bool(enabled), "code": access_code() if enabled else None}


def retry_after(client_ip: str) -> float:
    """Secondes restantes avant que cette adresse puisse réessayer."""
    with _failures_lock:
        count, until = _failures.get(client_ip, (0, 0.0))
    return max(0.0, until - time.monotonic())


def note_failure(client_ip: str) -> float:
    """Enregistre un essai manqué et renvoie l'attente imposée."""
    now = time.monotonic()
    with _failures_lock:
        count, _ = _failures.get(client_ip, (0, 0.0))
        count += 1
        delay = 0.0 if count <= FREE_ATTEMPTS else min(
            MAX_DELAY_S, 5.0 * 2 ** (count - FREE_ATTEMPTS - 1))
        _failures[client_ip] = (count, now + delay)
    return delay


def clear_failures(client_ip: str) -> None:
    """Un code juste efface l'ardoise de cet appareil."""
    with _failures_lock:
        _failures.pop(client_ip, None)


def check_access(client_ip: str, cookie_header: str, query_code: str | None) -> bool:
    """Cette requête a-t-elle le droit d'être servie ?

    La machine elle-même passe toujours. Les autres doivent présenter le
    code, en paramètre d'URL (premier accès, via le QR) ou en cookie.
    """
    if is_loopback(client_ip):
        return True
    if not lan_enabled():
        # L'accès réseau n'a pas été activé : on refuse même si l'écoute
        # est ouverte, par exemple après un changement de réglage à chaud.
        return False
    expected = access_code()
    if query_code and secrets.compare_digest(str(query_code), expected):
        return True
    for part in (cookie_header or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE_NAME and secrets.compare_digest(value, expected):
            return True
    return False


def urls(port: int) -> list[str]:
    return [f"http://{address}:{port}" for address in all_local_ips()]


def phone_url(port: int, with_code: bool = True) -> str | None:
    """URL à encoder dans le QR code, code d'accès compris."""
    addresses = all_local_ips()
    if not addresses:
        return None
    base = f"http://{addresses[0]}:{port}"
    if with_code and lan_enabled():
        return f"{base}/?c={access_code()}"
    return base
