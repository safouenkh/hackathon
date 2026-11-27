"""Exporte le graphe RDF (ontologie + zones, cahiers, passages lus en base) en Turtle, pour Jena Fuseki.

Usage :
    .venv\\Scripts\\python.exe -m scripts.exporter_graphe                      # ontology/genere/graphe_zones.ttl
    .venv\\Scripts\\python.exe -m scripts.exporter_graphe --sortie autre.ttl

Le fichier est régénéré à partir de la base : il n'est pas dans Git (ontology/genere/).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "backend"))

from app.semantique.graphe_familles import graphe_complet, tester_familles  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--sortie", type=Path, default=RACINE / "ontology" / "genere" / "graphe_complet.ttl")
    a = p.parse_args()
    a.sortie.parent.mkdir(parents=True, exist_ok=True)
    g = graphe_complet()
    g.serialize(destination=a.sortie, format="turtle", encoding="utf-8")
    print(f"{len(g)} triplets écrits dans {a.sortie}")
    for famille, n in tester_familles(g).items():
        print(f"  SPARQL de test « {famille} » : {n} réponse(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
