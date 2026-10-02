@echo off
setlocal enabledelayedexpansion
title Athlytics - acces depuis le telephone
cd /d "%~dp0"

rem Page de code Unicode : sans elle, les carres du QR code peuvent
rem s afficher comme des points d interrogation.
chcp 65001 >nul 2>&1

echo.
echo    ===============================================
echo      ATHLYTICS - Acces depuis le telephone
echo    ===============================================
echo.
echo   Ce raccourci fait la meme chose que
echo   "LANCER-LE-SITE", mais il ouvre en plus l acces
echo   depuis votre telephone et affiche un QR code
echo   a scanner.
echo.

if not exist "run.py" (
  echo   PROBLEME : le fichier "run.py" est introuvable.
  echo.
  echo   Ce raccourci doit se trouver dans le MEME dossier
  echo   que run.py. Verifiez que vous avez bien extrait
  echo   la totalite du fichier ZIP.
  echo.
  pause
  exit /b 1
)

set "PY="
for %%C in (py python python3) do (
  if not defined PY (
    %%C -c "import sys" >nul 2>&1
    if not errorlevel 1 set "PY=%%C"
  )
)

if not defined PY (
  echo   Python n est pas installe sur cet ordinateur.
  echo   C est le moteur necessaire pour faire tourner le site.
  echo.
  echo   Voici quoi faire :
  echo     1. Le Microsoft Store va s ouvrir
  echo     2. Installez "Python 3.12" ^(gratuit^)
  echo     3. Revenez ici et double-cliquez a nouveau
  echo        sur ce fichier
  echo.
  start "" "ms-windows-store://search?query=python"
  pause
  exit /b 1
)

echo   Demarrage...
echo.
echo   Le QR code va s afficher juste en dessous.
echo   Scannez-le avec l appareil photo du telephone.
echo.
echo   LAISSEZ CETTE FENETRE OUVERTE : le telephone
echo   affiche le site de cet ordinateur, pas une copie.
echo.
echo   Si Windows affiche une alerte de pare-feu,
echo   repondez "Autoriser l acces" pour les reseaux prives.
echo.

!PY! run.py --lan

echo.
echo   Le site est arrete.
pause
