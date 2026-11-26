"""Contrôle après rédaction (PROTOTYPE pour le rôle 1, exigence BNF1).

Vérifie qu'une réponse rédigée par le LLM n'apporte ni nombre ni balise absents des sorties
des outils du tour. Ne juge pas le style : il signale seulement, pour que l'agent régénère
ou bascule sur une réponse neutre.
"""
from __future__ import annotations

import re
from typing import Any

BALISE_RE = re.compile(r"\[\[(?:ZONE|LOT|CHOIX|PDF):[^\]]*\]\]")
# 218 540 / 218540 / 3,5 / 1.800 ; espaces fines et insécables acceptées comme séparateur de milliers
_NOMBRE_RE = re.compile(r"(?<![\w.,/])\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?(?![\w])|(?<![\w.,/])\d+(?:[.,]\d+)?(?![\w])")
_PUCE_RE = re.compile(r"(?m)^\s*\d{1,2}[.)]\s")
_DATE_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_CHIFFRES_ARABES = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_MODIFICATEURS = re.compile(
    r"(?i)(plus de|moins de|environ|près de|au moins|approximativement|presque|quasiment|"
    r"more than|less than|about|around|approximately|"
    r"أكثر من|أقل من|حوالي|تقريبا|تقريباً|barcha)\s+(\d[\d   .,]*)")


def _interpretations(jeton: str) -> set[float]:
    """Valeurs possibles d'un nombre écrit (« 3,500 » peut valoir 3.5 ou 3500)."""
    brut = re.sub(r"[   ]", "", jeton)
    vals: set[float] = set()
    for dec, mil in ((",", "."), (".", ",")):
        t = brut.replace(mil, "")
        try:
            vals.add(round(float(t.replace(dec, ".")), 6))
        except ValueError:
            pass
    try:
        vals.add(round(float(re.sub(r"[.,]", "", brut)), 6))
    except ValueError:
        pass
    return vals


def nombres_du_texte(texte: str) -> list[str]:
    t = (texte or "").translate(_CHIFFRES_ARABES)
    t = BALISE_RE.sub(" ", t)          # les nombres des balises sont contrôlés avec les balises
    t = _PUCE_RE.sub(" ", t)           # « 1. », « 2) » : numérotation de liste
    t = _DATE_RE.sub(" ", t)
    return [m.group(0).strip() for m in _NOMBRE_RE.finditer(t)]


def valeurs_des_sources(*sources: Any) -> set[float]:
    """Tous les nombres présents dans les sorties d'outils (valeurs et nombres cités dans les textes)."""
    vals: set[float] = set()

    def parcourir(x: Any) -> None:
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            vals.add(round(float(x), 6))
        elif isinstance(x, str):
            for n in nombres_du_texte(x):
                vals.update(_interpretations(n))
        elif isinstance(x, dict):
            for v in x.values():
                parcourir(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                parcourir(v)

    for s in sources:
        parcourir(s)
    return vals


def controler(reponse: str, sorties_outils: list[dict], balises_outils: set[str],
              textes_autorises: list[str] = ()) -> dict[str, Any]:
    """Résultat du contrôle : nombres non trouvés, chiffres modifiés, balises inventées."""
    sources = valeurs_des_sources(sorties_outils, list(textes_autorises))
    non_trouves = [n for n in nombres_du_texte(reponse) if not (_interpretations(n) & sources)]
    modifies = [f"{m.group(1)} {m.group(2).strip()}" for m in _MODIFICATEURS.finditer(reponse or "")]
    inventees = [b for b in BALISE_RE.findall(reponse or "") if b not in balises_outils]
    return {
        "ok": not (non_trouves or modifies or inventees),
        "nombres_non_trouves": list(dict.fromkeys(non_trouves)),
        "chiffres_modifies": list(dict.fromkeys(modifies)),
        "balises_inventees": list(dict.fromkeys(inventees)),
    }
