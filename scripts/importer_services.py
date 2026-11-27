"""Importe les fiches de services et les formulaires (afi-services-markdown) dans le schéma `assistant`.

Usage (depuis la racine du projet) :
    .venv\\Scripts\\python.exe -m scripts.importer_services               # lecture et contrôle seulement
    .venv\\Scripts\\python.exe -m scripts.importer_services --appliquer   # écrit en base (brouillons)

Chaque fiche devient une version brouillon de son parcours : rien n'est publié.
Relecture et publication : scripts/publier_parcours.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402
from app.sources.import_services import importer  # noqa: E402

DOSSIER = Path(__file__).resolve().parents[1] / "afi-services-markdown"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dossier", type=Path, default=DOSSIER)
    p.add_argument("--appliquer", action="store_true", help="écrire en base (sinon : contrôle seulement)")
    a = p.parse_args()
    r = importer(get_settings().conninfo(admin=True), a.dossier, appliquer=a.appliquer)
    for f in r.fiches:
        print(f"{f.parcours.code:<38} {f.fiche.compter()}")
    for x in r.avertissements:
        print(f"  avertissement : {x}")
    for x in r.erreurs:
        print(f"  ERREUR : {x}")
    if not a.appliquer:
        print(f"\n{'OK' if r.ok else 'ÉCHEC'} : contrôle seulement, rien n'a été écrit (ajouter --appliquer).")
        return 0 if r.ok else 1
    if not r.ok:
        print(f"\nÉCHEC : rien n'a été écrit (journal : ingestion_runs.id={r.run_id}).")
        return 1
    print(f"\nOK : {len(r.versions_creees)} brouillon(s) créé(s), {len(r.inchangees)} fiche(s) inchangée(s) "
          f"(journal : ingestion_runs.id={r.run_id}). Relire puis publier : python -m scripts.publier_parcours")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
