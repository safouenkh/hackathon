"""Mesure le temps de réponse des outils du rôle 3 (pour le tableau de mesures).

Usage : .venv\\Scripts\\python.exe -m scripts.mesurer_outils [repetitions]
Affiche p50 / p95 / max en millisecondes, caches chauds (le premier appel est mesuré à part).
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.processing.registre import executer  # noqa: E402
from app.repositories import afi as repo  # noqa: E402

APPELS = [
    ("chercher_lots", {"gouvernorat": "Monastir", "surface_min_m2": 3000, "budget_max_dt": 500000}),
    ("details_lot", {"lot_id": 7079}),
    ("comparer_lots", {"lot_ids": [7079, 4138, 7094]}),
    ("lots_proches", {"type": "port", "distance_max_km": 40}),
    ("lots_proches", {"zone_id": 932119, "distance_max_km": 60}),
    ("avantages", {"activite": "textile", "gouvernorat": "Sfax"}),
    ("services_afi", {"besoin": "La banque me demande un papier pour mon prêt"}),
    ("demarche", {"service": "acquisition"}),
    ("preparer_demande", {"lot_ids": [7079], "variante": "littoral_grand_tunis"}),
]


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    repo.vider_caches()
    t = time.perf_counter()
    executer(*APPELS[0])
    print(f"premier appel (chargement des caches) : {(time.perf_counter() - t) * 1000:.1f} ms\n")
    print(f"{'outil':<16}{'arguments':<48}{'p50 ms':>8}{'p95 ms':>8}{'max ms':>8}")
    for nom, args in APPELS:
        durees = []
        for _ in range(n):
            t = time.perf_counter()
            executer(nom, args)
            durees.append((time.perf_counter() - t) * 1000)
        durees.sort()
        p95 = durees[max(0, int(round(0.95 * n)) - 1)]
        print(f"{nom:<16}{str(args)[:46]:<48}{statistics.median(durees):>8.1f}{p95:>8.1f}{durees[-1]:>8.1f}")
    print(f"\n{n} répétitions par appel")


if __name__ == "__main__":
    main()
