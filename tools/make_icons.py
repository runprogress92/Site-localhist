#!/usr/bin/env python3
"""Génère les PNG de l'application depuis les SVG sources.

Les icônes sont livrées déjà rendues dans le dépôt : ce script ne sert qu'à
les régénérer après modification du dessin. Il utilise Chromium via
Playwright, qui n'est donc **pas** une dépendance de l'application — juste
un outil d'atelier.

    python3 tools/make_icons.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "frontend" / "assets"
ICONS = ASSETS / "icons"

# (fichier source, taille, nom de sortie)
TARGETS = [
    ("icon.svg", 180, "apple-touch-icon.png"),      # écran d'accueil iOS
    ("icon.svg", 192, "icon-192.png"),              # manifeste, Android
    ("icon.svg", 512, "icon-512.png"),              # splash et magasins
    ("icon.svg", 32, "favicon-32.png"),
    ("icon-maskable.svg", 192, "icon-maskable-192.png"),
    ("icon-maskable.svg", 512, "icon-maskable-512.png"),
]

RENDER_SCRIPT = r"""
const { chromium } = require(process.env.PW_PATH);
const fs = require('fs');
(async () => {
  const jobs = JSON.parse(process.argv[2]);
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH });
  for (const job of jobs) {
    const page = await browser.newPage({
      viewport: { width: job.size, height: job.size },
      deviceScaleFactor: 1,
    });
    const svg = fs.readFileSync(job.src, 'utf8');
    await page.setContent(
      `<!doctype html><style>
         html,body{margin:0;padding:0;width:${job.size}px;height:${job.size}px;
                   background:transparent;overflow:hidden}
         svg{display:block;width:${job.size}px;height:${job.size}px}
       </style>${svg}`,
      { waitUntil: 'load' });
    await page.screenshot({ path: job.out, omitBackground: true });
    await page.close();
    console.log(`  ${job.out.split('/').pop().padEnd(26)} ${job.size}×${job.size}`);
  }
  await browser.close();
})();
"""


def main() -> int:
    ICONS.mkdir(parents=True, exist_ok=True)
    jobs = [{"src": str(ASSETS / src), "size": size, "out": str(ICONS / out)}
            for src, size, out in TARGETS]

    script = ROOT / "tools" / "_render_icons.js"
    script.write_text(RENDER_SCRIPT)
    print("\n  Rendu des icônes\n")
    try:
        result = subprocess.run(
            ["node", str(script), json.dumps(jobs)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=180)
    finally:
        script.unlink(missing_ok=True)

    print(result.stdout, end="")
    if result.returncode != 0:
        print(result.stderr[:1500])
        print("\n  Échec. Ce script a besoin de Node, de Playwright et de "
              "Chromium ; ils ne sont pas nécessaires pour utiliser "
              "l'application, seulement pour redessiner ses icônes.\n")
        return 1
    print(f"\n  Écrites dans {ICONS}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
