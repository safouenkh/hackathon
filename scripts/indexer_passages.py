"""Reconstruit l'index Qdrant des passages (cahiers des charges) avec BGE-M3.

Usage (Qdrant lancé : docker compose up -d qdrant) :
    .venv\\Scripts\\python.exe -m scripts.indexer_passages

Lit les passages de la dernière version de chaque cahier dans PostgreSQL (compte de lecture),
recrée la collection, puis encode et ajoute tous les passages. Le premier lancement télécharge
le modèle (≈ 2,3 Go). L'identifiant de chaque point est l'UUID du passage.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.repositories.documents import passages_a_indexer  # noqa: E402
from app.semantique import passages  # noqa: E402


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    s = get_settings()
    with get_engine().connect() as c:
        lignes = passages_a_indexer(c)
    if not lignes:
        print("Aucun passage en base : lancer d'abord scripts.importer_cahiers --appliquer.")
        return 1
    debut = time.perf_counter()

    def progression(n: int, total: int) -> None:
        print(f"  {n}/{total} passages ({time.perf_counter() - debut:.0f} s)", flush=True)

    n = passages.indexer(passages.client_qdrant(), passages.encodeur(), lignes, s.qdrant_collection_passages,
                         progression=progression)
    print(f"OK : {n} passages indexés dans « {s.qdrant_collection_passages} » ({s.embedding_model}) "
          f"en {time.perf_counter() - debut:.0f} s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
