@echo off
setlocal enabledelayedexpansion
title Athlytics - suivi d athletes
cd /d "%~dp0"

echo.
echo    ===========================================
echo      ATHLYTICS - Suivi d athletes
echo    ===========================================
echo.

rem --- Verifier que le fichier est au bon endroit ---
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

rem --- Chercher Python (py, puis python, puis python3) ---
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

echo   Demarrage du site...
echo.
echo   Votre navigateur va s ouvrir tout seul.
echo   LAISSEZ CETTE FENETRE OUVERTE pendant que
echo   vous utilisez le site.
echo.
echo   Pour arreter : fermez cette fenetre.
echo.

!PY! run.py

echo.
echo   Le site est arrete.
pause
