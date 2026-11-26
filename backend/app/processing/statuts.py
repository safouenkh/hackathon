"""Correspondance LOT_ETAPE -> statut public du lot.

Source : code JavaScript de la carte publique https://afi.e-industrie.gov.tn/
(fonction onEachLot, `switch(feature.properties.LOT_ETAPE)`), lu le 26/11/2026,
recoupé avec liste.php (720 lots « disponibles ») ; décisions de Safouen pour 0 et 5.
Preuves : docs/statuts_lots.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.processing.schemas import CodeAvertissement, StatutLot

_PAR_ETAPE: dict[int, StatutLot] = {
    1: StatutLot.disponible,      # carte : vert, « disponible »
    2: StatutLot.non_disponible,  # carte : bleu, « réservé »
    3: StatutLot.non_disponible,  # carte : rouge, « Attribué »
    4: StatutLot.aux_encheres,    # carte : violet, « Mis aux enchères »
    5: StatutLot.inconnu,         # carte : gris -> « gris = pas d'information » (décision Safouen)
    0: StatutLot.non_disponible,  # carte : branche default, rouge « Non disponible » (décision Safouen)
}


@dataclass(frozen=True)
class StatutCalcule:
    statut: StatutLot
    avertissements: tuple[CodeAvertissement, ...]


ETAPES_CONNUES: tuple[int, ...] = tuple(sorted(_PAR_ETAPE))


def etapes_pour(statuts: list[StatutLot]) -> tuple[list[int], bool]:
    """Codes LOT_ETAPE à sélectionner pour ces statuts, et s'il faut inclure les codes non prévus
    (NULL ou valeur hors correspondance), qui valent `inconnu`."""
    voulus = set(statuts)
    etapes = sorted(e for e, s in _PAR_ETAPE.items() if s in voulus)
    return etapes, StatutLot.inconnu in voulus


def statut_depuis_etape(etape: int | None) -> StatutCalcule:
    statut = _PAR_ETAPE.get(etape, StatutLot.inconnu) if etape is not None else StatutLot.inconnu
    if statut is StatutLot.inconnu:
        return StatutCalcule(statut, (CodeAvertissement.statut_inconnu,))
    if statut in (StatutLot.disponible, StatutLot.aux_encheres):
        # Le dump est un instantané : la disponibilité doit être reconfirmée auprès de l'AFI.
        return StatutCalcule(statut, (CodeAvertissement.donnee_non_fraiche,))
    return StatutCalcule(statut, ())
