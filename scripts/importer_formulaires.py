"""Importe les champs des formulaires officiels (afi-services-markdown/formulaires_champs.json).

Usage (depuis la racine du projet, après scripts.importer_services --appliquer) :
    .venv\\Scripts\\python.exe -m scripts.importer_formulaires               # contrôle (écrit puis annule)
    .venv\\Scripts\\python.exe -m scripts.importer_formulaires --appliquer   # écrit en base
    .venv\\Scripts\\python.exe -m scripts.importer_formulaires --revue       # écrit revue_formulaires.md

Un formulaire qui a déjà des champs en base n'est pas modifié.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402
from app.sources.formulaires import importer, lire, revue_markdown  # noqa: E402

DOSSIER = Path(__file__).resolve().parents[1] / "afi-services-markdown"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dossier", type=Path, default=DOSSIER)
    p.add_argument("--appliquer", action="store_true", help="écrire en base (sinon : contrôle seulement)")
    p.add_argument("--revue", action="store_true", help="écrire le tableau de relecture, sans toucher la base")
    a = p.parse_args()
    if a.revue:
        fichier, erreurs = lire(a.dossier)
        cible = a.dossier / "revue_formulaires.md"
        cible.write_text(revue_markdown(fichier), encoding="utf-8")
        print(f"Relecture écrite : {cible}" + "".join(f"\n  ERREUR : {e}" for e in erreurs))
        return 1 if erreurs else 0
    r = importer(get_settings().conninfo(admin=True), a.dossier, appliquer=a.appliquer)
    for code, n in r.importes.items():
        print(f"{code:<34} {n}")
    for x in r.avertissements:
        print(f"  avertissement : {x}")
    for x in r.erreurs:
        print(f"  ERREUR : {x}")
    if not r.ok:
        print("\nÉCHEC : rien n'a été écrit.")
        return 1
    if not a.appliquer:
        print("\nOK : contrôle seulement (écrit puis annulé), rien n'a été gardé (ajouter --appliquer).")
        return 0
    print(f"\nOK : {len(r.importes)} formulaire(s) importé(s), {len(r.deja_presents)} déjà présent(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
