"""Importe en base les pages des organismes et les règles d'orientation (après migration 0004).

Usage :
    .venv\\Scripts\\python.exe -m scripts.lire_sources          # lit les liens configurés
    .venv\\Scripts\\python.exe -m scripts.extraire_sources      # Markdown dans sources-organismes/md/
    .venv\\Scripts\\python.exe -m scripts.importer_organismes                # contrôle (écrit puis annule)
    .venv\\Scripts\\python.exe -m scripts.importer_organismes --appliquer    # écrit en base
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "backend"))

from app.config import get_settings  # noqa: E402
from app.sources.organismes import importer  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dossier", type=Path, default=RACINE / "sources-organismes")
    p.add_argument("--appliquer", action="store_true")
    a = p.parse_args()
    r = importer(get_settings().conninfo(admin=True), a.dossier, appliquer=a.appliquer)
    for x in r.avertissements:
        print(f"  avertissement : {x}")
    for x in r.erreurs:
        print(f"  ERREUR : {x}")
    if not r.ok:
        print("\nÉCHEC : rien n'a été écrit.")
        return 1
    etat = "écrit en base" if a.appliquer else "contrôle seulement (écrit puis annulé, ajouter --appliquer)"
    print(f"\nOK : {len(r.versions_creees)} version(s) créée(s), {len(r.inchangees)} inchangée(s), "
          f"{r.passages} passage(s), {r.regles_ajoutees} règle(s) ; {etat}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
