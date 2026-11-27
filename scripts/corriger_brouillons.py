"""Applique aux brouillons les corrections et signalements sourcés (afi-services-markdown/corrections.json).

Usage (depuis la racine du projet) :
    .venv\\Scripts\\python.exe -m scripts.corriger_brouillons                          # contrôle seulement
    .venv\\Scripts\\python.exe -m scripts.corriger_brouillons --appliquer --par "Nom"  # écrit dans les brouillons

Rien n'est publié. À relancer après un nouvel import qui crée un nouveau brouillon.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402
from app.sources.corrections import corriger  # noqa: E402

DOSSIER = Path(__file__).resolve().parents[1] / "afi-services-markdown"


def main() -> int:
    for flux in (sys.stdout, sys.stderr):
        flux.reconfigure(encoding="utf-8")          # citations en arabe sur une console Windows
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dossier", type=Path, default=DOSSIER)
    p.add_argument("--appliquer", action="store_true", help="écrire dans les brouillons (sinon : contrôle seulement)")
    p.add_argument("--par", help="nom de la personne qui a validé les corrections (obligatoire avec --appliquer)")
    a = p.parse_args()
    if a.appliquer and not (a.par or "").strip():
        p.error("--appliquer exige --par \"Nom\"")
    r = corriger(get_settings().conninfo(admin=True), a.dossier, par=a.par, appliquer=a.appliquer)
    for x in r.faites:
        print(f"  {'fait' if a.appliquer else 'à faire'} : {x}")
    for x in r.erreurs:
        print(f"  ERREUR : {x}")
    print(f"\n{'OK' if r.ok else 'ÉCHEC, rien écrit'} : {len(r.faites)} changement(s) "
          f"{'appliqué(s)' if a.appliquer else 'prévu(s), rien écrit'}, {len(r.deja_faites)} déjà en place.")
    return 0 if r.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
