#!/bin/bash
# Lanceur pour macOS et Linux : double-cliquez sur ce fichier.
cd "$(dirname "$0")" || exit 1

echo
echo "   ==========================================="
echo "     ATHLYTICS — Suivi d'athlètes"
echo "   ==========================================="
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
  echo "   C'est le moteur nécessaire pour faire tourner le site."
  echo
  echo "   Téléchargez-le sur https://www.python.org/downloads/"
  echo "   puis double-cliquez à nouveau sur ce fichier."
  echo
  command -v open >/dev/null 2>&1 && open "https://www.python.org/downloads/"
  read -r -p "   Appuyez sur Entrée pour fermer. "
  exit 1
fi

echo "   Démarrage du site…"
echo
echo "   Votre navigateur va s'ouvrir tout seul."
echo "   LAISSEZ CETTE FENÊTRE OUVERTE pendant que vous utilisez le site."
echo "   Pour arrêter : fermez cette fenêtre, ou appuyez sur Ctrl+C."
echo

"$PY" run.py

echo
read -r -p "   Le site est arrêté. Appuyez sur Entrée pour fermer. "
