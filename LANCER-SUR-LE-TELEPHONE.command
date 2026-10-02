#!/bin/bash
# Lanceur « accès téléphone » pour macOS et Linux : double-cliquez dessus.
# Identique à LANCER-LE-SITE, mais ouvre l'accès au réseau local et
# affiche un QR code à scanner avec le téléphone.
cd "$(dirname "$0")" || exit 1

echo
echo "   ==============================================="
echo "     ATHLYTICS — Accès depuis le téléphone"
echo "   ==============================================="
echo

if [ ! -f run.py ]; then
  echo "   PROBLÈME : le fichier « run.py » est introuvable."
  echo "   Ce raccourci doit rester dans le même dossier que run.py."
  echo
  read -r -p "   Appuyez sur Entrée pour fermer. "
  exit 1
fi

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c "import sys" >/dev/null 2>&1; then
    PY="$candidate"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "   Python n'est pas installé sur cet ordinateur."
  echo
  echo "   Téléchargez-le sur https://www.python.org/downloads/"
  echo "   puis double-cliquez à nouveau sur ce fichier."
  echo
  command -v open >/dev/null 2>&1 && open "https://www.python.org/downloads/"
  read -r -p "   Appuyez sur Entrée pour fermer. "
  exit 1
fi

echo "   Démarrage…"
echo
echo "   Le QR code va s'afficher juste en dessous."
echo "   Scannez-le avec l'appareil photo du téléphone."
echo
echo "   LAISSEZ CETTE FENÊTRE OUVERTE : le téléphone affiche le site"
echo "   de cet ordinateur, pas une copie."
echo

"$PY" run.py --lan

echo
read -r -p "   Le site est arrêté. Appuyez sur Entrée pour fermer. "
