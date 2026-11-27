"""Importe les cahiers des charges des zones (passages) et les compléments de zone du paquet GraphRAG.

Usage (depuis la racine du projet, après scripts.migrer --appliquer) :
    .venv\\Scripts\\python.exe -m scripts.importer_cahiers               # contrôle (écrit puis annule)
    .venv\\Scripts\\python.exe -m scripts.importer_cahiers --revue       # écrit docs/revue_paquet_graphrag.md
    .venv\\Scripts\\python.exe -m scripts.importer_cahiers --appliquer   # écrit en base

Le dossier du paquet n'est pas dans Git (`--paquet`, par défaut afi_graphrag_package/).
Un document déjà importé avec le même contenu (SHA-256) n'est pas réimporté.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "backend"))

from app.config import get_settings  # noqa: E402
from app.sources.cahiers import analyser, importer, revue_markdown  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--paquet", type=Path, default=RACINE / "afi_graphrag_package")
    p.add_argument("--recu-le", type=date.fromisoformat, default=date.today(),
                   help="date de réception du paquet (AAAA-MM-JJ), gardée comme date de collecte")
    p.add_argument("--appliquer", action="store_true", help="écrire en base (sinon : contrôle seulement)")
    p.add_argument("--revue", action="store_true", help="écrire la relecture (docs/revue_paquet_graphrag.md)")
    a = p.parse_args()
    if a.revue:      # lecture seule (compte de lecture), possible avant la migration 0003
        r = analyser(get_settings().conninfo(), a.paquet)
        cible = RACINE / "docs" / "revue_paquet_graphrag.md"
        cible.write_text(revue_markdown(r), encoding="utf-8")
        print(f"Relecture écrite : {cible}")
    else:
        r = importer(get_settings().conninfo(admin=True), a.paquet, a.recu_le, appliquer=a.appliquer)
    print(f"documents liés à une zone AFI : {sum(z is not None for z in r.liens.values())}/{len(r.liens)}")
    print(f"compléments proposés : {len(r.complements)} ; écarts (non appliqués) : {len(r.ecarts)}")
    for x in r.avertissements:
        print(f"  avertissement : {x}")
    for x in r.erreurs:
        print(f"  ERREUR : {x}")
    if not r.ok:
        print("\nÉCHEC : rien n'a été écrit.")
        return 1
    if a.revue:
        return 0
    etat = "écrit en base" if a.appliquer else "contrôle seulement (écrit puis annulé, ajouter --appliquer)"
    print(f"\nOK : {len(r.documents)} document(s), {r.chunks} passage(s), {len(r.inchanges)} inchangé(s) ; {etat}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
