#!/usr/bin/env python3
"""Athlytics — plateforme locale de suivi d'athlètes.

Lancement :

    python3 run.py                  # démarre sur http://127.0.0.1:8420
    python3 run.py --port 9000      # autre port
    python3 run.py --seed           # (re)génère le jeu de démonstration
    python3 run.py --lan            # accessible depuis le téléphone (même Wi-Fi)
    python3 run.py --no-browser     # sans ouverture automatique du navigateur
    python3 run.py --check          # vérifie l'installation et sort

Aucune dépendance externe : bibliothèque standard de Python 3.10 ou plus.
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

MIN_PYTHON = (3, 10)

BANNER = r"""
   ___   _   _      _        _   _
  / _ \ | | | |    | |      | | (_)             ATHLYTICS
 / /_\ \| |_| |__  | |_   _ | |_ _  ___ ___     Suivi scientifique d'athlètes
 |  _  || __| '_ \ | | | | || __| |/ __/ __|    Garmin · Polar · COROS
 | | | || |_| | | || | |_| || |_| | (__\__ \    100 % local, aucune dépendance
 \_| |_/ \__|_| |_||_|\__, | \__|_|\___|___/
                       __/ |
                      |___/
"""


def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        print(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} ou plus récent est requis "
              f"(version détectée : {sys.version.split()[0]}).")
        sys.exit(1)


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
            return True
        except OSError:
            return False


def find_port(host: str, port: int, attempts: int = 20) -> int:
    for offset in range(attempts):
        if port_available(host, port + offset):
            return port + offset
    raise SystemExit(f"Aucun port libre entre {port} et {port + attempts}.")


def self_check() -> int:
    """Vérifie que chaque brique répond correctement."""
    from backend import db, network, qrcode, settings
    # Ces modules sont importés pour vérifier qu'ils se chargent : une erreur
    # de syntaxe ou une dépendance manquante se manifeste ici, avant que
    # l'utilisateur ne rencontre une page blanche.
    from backend.ingest import fit, fit_writer, pipeline, xmlformats  # noqa: F401
    from backend.science import (hrv, load, physiology, pmc, power,  # noqa: F401
                                 readiness, risk, running, zones)
    checks: list[tuple[str, bool, str]] = []

    checks.append(("Version de Python", sys.version_info >= MIN_PYTHON,
                   sys.version.split()[0]))
    db.init_db()
    tables = db.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='table'", default=0)
    checks.append(("Schéma de base de données", tables >= 25, f"{tables} tables"))

    # Codec FIT : aller-retour complet
    from datetime import datetime, timezone
    from io import BytesIO
    writer = fit_writer.FitWriter()
    start = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    writer.write_file_id(start)
    writer.write_records(start, {"heart_rate": [140] * 120, "power": [200] * 120,
                                 "speed": [8.0] * 120})
    writer.write_session(start, 120, 960, sport=2, avg_hr=140, avg_power=200)
    decoded = fit.decode(BytesIO(writer.build()))
    ok = (len(decoded["records"]) == 120
          and decoded["records"][50]["heart_rate"] == 140
          and decoded["sessions"][0]["avg_power"] == 200)
    checks.append(("Codec FIT (aller-retour)", ok, f"{len(decoded['records'])} points"))

    # Ancrages scientifiques : une heure au seuil doit valoir 100 points
    checks.append(("TSS : 1 h à la FTP = 100", abs(load.tss(3600, 250, 250) - 100) < 0.1,
                   f"{load.tss(3600, 250, 250)}"))
    checks.append(("hrTSS : 1 h au seuil = 100",
                   abs(load.hrtss(3600, None, 170, 45, 195, 170, "M") - 100) < 0.5,
                   f"{load.hrtss(3600, None, 170, 45, 195, 170, 'M')}"))
    checks.append(("NP d'un effort constant = moyenne",
                   power.normalized_power([250] * 600) == 250.0, "250 W"))
    checks.append(("GAP : coût sur le plat = 3,6 J/kg/m",
                   abs(running.grade_cost(0) - 3.6) < 0.001, "Minetti 2002"))
    vdot = running.vdot(5000, 1200)
    checks.append(("VDOT : 5 km en 20 min ≈ 49", 47 <= (vdot or 0) <= 51, str(vdot)))

    # Routeur
    from backend import api  # noqa: F401
    from backend.server import ROUTER
    checks.append(("Routes de l'API", len(ROUTER.routes) >= 90,
                   f"{len(ROUTER.routes)} routes"))

    # QR code : on vérifie le vecteur de référence Reed-Solomon de la norme
    # ISO/IEC 18004, puis qu'une URL réaliste tient dans la grille.
    rs = qrcode._rs_encode([32, 91, 11, 120, 209, 114, 220, 77, 67, 64,
                            236, 17, 236, 17, 236, 17], 10)
    checks.append(("QR code : correcteur d'erreurs",
                   rs == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23],
                   "vecteur ISO/IEC 18004"))
    sample = qrcode.make("http://192.168.1.24:8420/?c=123456")
    checks.append(("QR code : encodage d'une adresse", sample.size >= 21,
                   f"version {sample.version}, {sample.size}×{sample.size}"))

    addresses = network.all_local_ips()
    checks.append(("Adresse réseau de la machine", True,
                   addresses[0] if addresses else "aucune (accès téléphone "
                                                  "indisponible)"))

    frontend = ROOT / "frontend" / "index.html"
    checks.append(("Interface web", frontend.exists(), str(frontend.name)))
    pwa = [ROOT / "frontend" / "manifest.webmanifest", ROOT / "frontend" / "sw.js"]
    checks.append(("Application mobile (PWA)", all(f.exists() for f in pwa),
                   "manifeste + service worker"))

    width = max(len(name) for name, _, _ in checks)
    failures = 0
    print("\n  Vérification de l'installation\n")
    for name, ok, detail in checks:
        mark = "OK " if ok else "ÉCHEC"
        if not ok:
            failures += 1
        print(f"   [{mark:5s}] {name.ljust(width)}   {detail}")
    stats = db.db_stats()
    print(f"\n   Base : {stats['path']} ({stats['size_mb']} Mo, "
          f"{stats['counts'].get('athletes', 0)} athlètes, "
          f"{stats['counts'].get('activities', 0)} séances)")
    print(f"\n   {'Tout est en ordre.' if not failures else f'{failures} vérification(s) en échec.'}\n")
    return 1 if failures else 0


def console_supports_blocks() -> bool:
    """La console peut-elle afficher les demi-blocs Unicode du QR code ?

    Sur une console Windows restée en page de code ancienne, les écrire lève
    une UnicodeEncodeError et le lancement s'arrêterait net, juste au moment
    où l'utilisateur attend son QR code. On vérifie avant d'écrire.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        "▀█▄".encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def render_qr(qrcode, text: str) -> str:
    if console_supports_blocks():
        return qrcode.terminal(text)
    return qrcode.terminal_ascii(text)


def print_phone_block(network, qrcode, port: int) -> None:
    """Affiche l'adresse, le code et le QR code à scanner avec le téléphone.

    Le QR encode l'URL *avec* le code d'accès : scanner suffit, il n'y a ni
    adresse IP à recopier ni chiffres à saisir. Le code reste affiché en
    clair juste en dessous, car un deuxième téléphone peut arriver plus tard
    sans que l'on veuille relire ce bloc au QR.
    """
    addresses = network.all_local_ips()
    code = network.access_code()
    print("   " + "=" * 52)
    print("     ACCÈS DEPUIS LE TÉLÉPHONE")
    print("   " + "=" * 52)
    if not addresses:
        print("     Aucune adresse réseau détectée : cet ordinateur n'est")
        print("     relié à aucun réseau local. Branchez le Wi-Fi ou le câble,")
        print("     puis relancez.\n")
        return
    link = network.phone_url(port)
    print("     1. Le téléphone doit être sur le MÊME Wi-Fi que ce PC.")
    print("     2. Scannez ce QR code avec l'appareil photo :\n")
    for line in render_qr(qrcode, link).splitlines():
        print("      " + line)
    print()
    print(f"     Ou tapez cette adresse :  http://{addresses[0]}:{port}")
    print(f"     Code d'accès          :  {code}")
    for extra in addresses[1:]:
        print(f"     (autre adresse possible : http://{extra}:{port})")
    print()
    print("     3. Puis « Ajouter à l'écran d'accueil » pour avoir")
    print("        l'icône de l'application sur le téléphone.")
    print()
    print("     Le code protège l'accès, mais n'est pas du chiffrement :")
    print("     à réserver à votre réseau, pas à un Wi-Fi public.")
    print("   " + "=" * 52)


def main() -> None:
    check_python()
    parser = argparse.ArgumentParser(
        description="Athlytics — plateforme locale de suivi d'athlètes.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=None, help="adresse d'écoute")
    parser.add_argument("--port", type=int, default=None, help="port d'écoute")
    parser.add_argument("--no-browser", action="store_true",
                        help="ne pas ouvrir le navigateur")
    parser.add_argument("--lan", action="store_true",
                        help="ouvre l'accès au réseau local (téléphone, tablette) "
                             "et affiche un QR code à scanner")
    parser.add_argument("--seed", action="store_true",
                        help="génère le jeu de démonstration puis démarre")
    parser.add_argument("--seed-athletes", type=int, default=8)
    parser.add_argument("--seed-days", type=int, default=400)
    parser.add_argument("--reset", action="store_true",
                        help="efface la base avant de générer")
    parser.add_argument("--check", action="store_true",
                        help="vérifie l'installation et quitte")
    parser.add_argument("--verbose", action="store_true", help="journalise les requêtes")
    args = parser.parse_args()

    from backend import db, network, qrcode, settings
    from backend import api  # noqa: F401  (enregistre les routes)
    from backend.server import serve

    config = settings.load()
    # --lan ouvre l'écoute à toutes les interfaces : sans cela, le serveur
    # n'accepte que la boucle locale et le téléphone obtient un refus de
    # connexion sans explication. --host, s'il est fourni, reste prioritaire.
    host = args.host or ("0.0.0.0" if args.lan else config["host"])
    port = args.port or int(config["port"])
    db.init_db()

    if args.lan:
        network.enable_lan(True)

    if args.check:
        sys.exit(self_check())

    if args.reset:
        from backend.seed.generate import generate
        generate(athletes=0, days=0, reset=True, verbose=False)
        print("  Base réinitialisée.")

    # La génération de démonstration ne doit JAMAIS précéder le démarrage du
    # serveur. Poser la question ici bloquait le lancement sur une invite que
    # rien ne signale comme telle : l'utilisateur voyait une fenêtre figée et
    # un site injoignable. L'écran d'accueil de l'interface propose la même
    # génération, avec un bouton, une fois le site accessible.
    if args.seed:
        from backend.seed.generate import generate
        # Environ 18 s par athlète pour 400 jours : chaque séance récente est
        # produite sous forme de flux à 1 Hz puis passée dans le pipeline
        # d'analyse réel, exactement comme un fichier importé.
        estimate = round(args.seed_athletes * args.seed_days / 22)
        print(f"\n  Génération du jeu de démonstration : {args.seed_athletes} "
              f"athlètes sur {args.seed_days} jours, environ "
              f"{estimate // 60} min {estimate % 60:02d} s.\n")
        generate(athletes=args.seed_athletes, days=args.seed_days,
                 stream_days=min(130, args.seed_days), reset=True)

    athletes = db.scalar("SELECT COUNT(*) FROM athletes", default=0)

    actual_port = find_port(host, port)
    if actual_port != port:
        print(f"  Port {port} occupé, bascule sur {actual_port}.")
    # « 0.0.0.0 » désigne toutes les interfaces : c'est une adresse d'écoute,
    # pas une adresse à ouvrir dans un navigateur.
    own_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    url = f"http://{own_host}:{actual_port}"

    httpd = serve(host, actual_port, verbose=args.verbose)
    stats = db.db_stats()
    print(BANNER)
    print("   " + "-" * 52)
    print(f"     LE SITE EST EN LIGNE :  {url}")
    print("     Ouvrez cette adresse dans votre navigateur")
    print("     si elle ne s'ouvre pas toute seule.")
    print("   " + "-" * 52 + "\n")
    if athletes == 0:
        print("   La base est vide : la page d'accueil vous proposera de")
        print("   générer un jeu de démonstration, ou de créer un athlète.\n")
    else:
        print(f"   Contenu       {stats['counts'].get('athletes', 0)} athlètes · "
              f"{stats['counts'].get('activities', 0)} séances · "
              f"{stats['counts'].get('wellness', 0)} relevés quotidiens")
    print(f"   Base          {stats['path']}")
    print(f"   Python        {sys.version.split()[0]} — aucune dépendance externe")
    if args.lan:
        print_phone_block(network, qrcode, actual_port)
    else:
        print("   Téléphone     relancez avec « --lan » pour y accéder "
              "(ou LANCER-SUR-LE-TELEPHONE)")
    print("\n   Laissez cette fenêtre ouverte. Ctrl+C pour arrêter.\n")

    if not args.no_browser and config.get("open_browser", True):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n   Arrêt du serveur…")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
