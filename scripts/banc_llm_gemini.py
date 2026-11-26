"""Banc de test des 8 outils du rôle 3 avec Gemini, en ligne de commande.

Ce n'est PAS l'agent de Dalila (rôle 1). Le cœur est dans backend/app/banc/gemini.py ;
l'interface web équivalente est servie par l'API sur /banc (voir README).

Usage :
    .venv\\Scripts\\python.exe -m scripts.banc_llm_gemini                 # conversation
    .venv\\Scripts\\python.exe -m scripts.banc_llm_gemini -q "question"   # une seule question
Commandes en conversation : /reset (nouvelle conversation), /quit.
Prérequis : GEMINI_API_KEY dans .env (la clé n'est jamais affichée).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.banc.gemini import CONSIGNES, Banc, creer_banc, declarations, executer_outil  # noqa: E402,F401
from app.config import get_settings  # noqa: E402
from app.processing.registre import OUTILS  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-q", "--question", help="poser une seule question puis quitter")
    p.add_argument("--modele", help="modèle Gemini (défaut : GEMINI_MODEL du .env)")
    a = p.parse_args()

    s = get_settings()
    cle = s.gemini_api_key.get_secret_value()
    if not cle:
        print("GEMINI_API_KEY est vide : ajoute-la dans .env (voir .env.example).", file=sys.stderr)
        return 1
    if a.modele:
        s = s.model_copy(update={"gemini_model": a.modele})
    banc = creer_banc(s)
    print(f"Banc de test Dalila — modèle {banc.modele} (repli : {', '.join(banc.modeles_repli) or 'aucun'}) "
          f"— {len(OUTILS)} outils. /reset, /quit\n")

    def une(question: str) -> None:
        debut = time.perf_counter()
        reponse = banc.poser(question)
        print(f"\nDalila : {reponse}\n")
        c = banc.controler(question, reponse)
        if not c["ok"]:
            print(f"  !! CONTRÔLE : nombres non trouvés {c['nombres_non_trouves']} ; "
                  f"chiffres modifiés {c['chiffres_modifies']} ; balises inventées {c['balises_inventees']}")
        print(f"  ({time.perf_counter() - debut:.1f} s ; jetons cumulés : entrée {banc.jetons['entree']}, "
              f"sortie {banc.jetons['sortie']})\n")

    if a.question:
        une(a.question)
        return 0
    while True:
        try:
            q = input("Vous : ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if q in ("/quit", "/q"):
            return 0
        if q == "/reset":
            banc.reset()
            print("(nouvelle conversation)\n")
            continue
        if q:
            une(q)


if __name__ == "__main__":
    raise SystemExit(main())
