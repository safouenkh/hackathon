"""Relecture et publication des brouillons de parcours (en attendant l'espace admin).

Usage (depuis la racine du projet) :
    .venv\\Scripts\\python.exe -m scripts.publier_parcours
        -> écrit la relecture dans afi-services-markdown/revue_brouillons.md, ne publie rien
    .venv\\Scripts\\python.exe -m scripts.publier_parcours --appliquer --par "Safouen" [--parcours copie-conforme ...]
        -> publie le dernier brouillon de chaque parcours (ou des parcours indiqués)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402
from app.sources.publication import brouillons, publier, revue_markdown  # noqa: E402

REVUE = Path(__file__).resolve().parents[1] / "afi-services-markdown" / "revue_brouillons.md"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--parcours", nargs="*", help="codes des parcours (défaut : tous)")
    p.add_argument("--appliquer", action="store_true", help="publier (sinon : relecture seulement)")
    p.add_argument("--par", default="", help="nom de la personne qui valide la publication")
    a = p.parse_args()
    codes = a.parcours or None
    with psycopg.connect(get_settings().conninfo(admin=True)) as conn:
        liste = brouillons(conn, codes)
        if not a.appliquer:
            REVUE.write_text(revue_markdown(conn, codes), encoding="utf-8")
            for b in liste:
                print(f"{b.parcours:<38} brouillon v{b.numero}  (publiée : "
                      f"{'v' + str(b.publiee_actuelle) if b.publiee_actuelle else 'aucune'})")
            print(f"\n{len(liste)} brouillon(s). Relecture : {REVUE}. Rien n'a été publié "
                  "(ajouter --appliquer --par \"Nom\").")
            return 0
        faits = publier(conn, a.par, codes)
    print(f"Publié(s) par {a.par} : {', '.join(f'{b.parcours} v{b.numero}' for b in faits) or 'aucun'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
