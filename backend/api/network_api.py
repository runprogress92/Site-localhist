"""Endpoints « Connecter un téléphone »."""
from __future__ import annotations

from .. import db, network, qrcode, settings
from ..server import ROUTER, Response, bad_request


@ROUTER.get("/api/network")
def network_status(request):
    """État de l'accès réseau : adresses, code, QR code et mises en garde."""
    port = network.bound_port(settings.load()["port"])
    addresses = network.all_local_ips()
    enabled = network.lan_enabled()
    url = network.phone_url(port)

    return {
        "enabled": enabled,
        "listening": network.BOUND["host"],
        "port": port,
        "addresses": addresses,
        "urls": network.urls(port),
        "phone_url": url,
        "code": network.access_code() if enabled else None,
        "qr_svg": qrcode.svg(url, module=7, quiet=3,
                             dark="#0b0e13", light="#ffffff") if url else None,
        "requires_restart": enabled and not network.listening_on_lan(),
        "notes": {
            "same_wifi": "Le téléphone doit être connecté au même réseau Wi-Fi "
                         "que cet ordinateur, et l'ordinateur doit rester allumé "
                         "avec cette fenêtre ouverte.",
            "security": "L'échange se fait en HTTP simple : le code d'accès "
                        "empêche un voisin de réseau d'ouvrir l'application, "
                        "mais ne chiffre pas les données. À éviter sur un "
                        "réseau public.",
            "ios": "Sur iPhone : ouvrez le lien dans Safari, puis Partager › "
                   "Sur l'écran d'accueil. L'application s'ouvrira en plein "
                   "écran, sans barre d'adresse.",
            "android": "Sur Android : ouvrez le lien dans Chrome, puis menu ⋮ › "
                       "Ajouter à l'écran d'accueil. Le mode hors ligne reste "
                       "indisponible tant que la connexion n'est pas en HTTPS.",
        },
    }


@ROUTER.post("/api/network")
def set_network(request):
    """Active ou désactive l'accès depuis le réseau local."""
    payload = request.json
    if "enabled" not in payload:
        raise bad_request("Champ « enabled » attendu.")
    result = network.enable_lan(bool(payload["enabled"]))
    port = network.bound_port(settings.load()["port"])
    result["phone_url"] = network.phone_url(port)
    result["requires_restart"] = result["enabled"] and not network.listening_on_lan()
    return result


@ROUTER.post("/api/network/code")
def new_code(request):
    """Renouvelle le code : les appareils déjà reliés devront le ressaisir."""
    code = network.rotate_code()
    port = network.bound_port(settings.load()["port"])
    return {"code": code, "phone_url": network.phone_url(port)}


@ROUTER.get("/api/network/qr.svg")
def qr_image(request):
    """QR code en image, pour impression ou partage."""
    target = request.q("url") or network.phone_url(
        network.bound_port(settings.load()["port"]))
    if not target:
        raise bad_request("Aucune adresse réseau disponible sur cette machine.")
    module = max(2, min(20, request.q_int("module", 8)))
    markup = qrcode.svg(target, module=module, quiet=3,
                        dark=request.q("dark", "#000000"),
                        light=request.q("light", "#ffffff"))
    return Response(markup.encode("utf-8"), "image/svg+xml; charset=utf-8")
