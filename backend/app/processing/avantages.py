"""Outil avantages : incitations applicables, toujours avec leurs sources.

Les incitations viennent des documents officiels (TIA, APII, APIA, FIPA, JORT…), indexés par le
rôle 2 (Qdrant / Jena). Ce module code contre une interface `SourceIncitations` ;
tant que le rôle 2 n'a pas branché son implémentation, `SourceIncitationsIndisponible` (STUB)
renvoie une liste vide et l'avertissement `source_indisponible` : jamais d'incitation inventée.
"""
from __future__ import annotations

from typing import Protocol

from app.processing.lots import _zones_par_code
from app.processing.reference import GOUVERNORATS, gouv_id_depuis_nom
from app.processing.schemas import (
    DATE_INSTANTANE_AFI, AvantagesDonnees, AvantagesEntree, Avertissement, CodeAvertissement as C,
    Incitation, Provenance, SortieOutil,
)


class SourceIncitations(Protocol):
    """Interface attendue du rôle 2 (retrieval)."""

    def rechercher(self, activite: str | None, gouvernorat: str | None, zone_id: int | None,
                   limite: int = 5) -> list[Incitation]:
        """Extraits exacts de sources officielles, chacun avec URL ou document + page."""
        ...


class SourceIncitationsIndisponible:
    """STUB — à remplacer par l'implémentation du rôle 2. Ne renvoie jamais de contenu."""

    disponible = False

    def rechercher(self, activite, gouvernorat, zone_id, limite=5) -> list[Incitation]:
        return []


_source: SourceIncitations = SourceIncitationsIndisponible()


def brancher_source(source: SourceIncitations) -> None:
    """Point d'injection pour le rôle 2 (appelé au démarrage de l'application)."""
    global _source
    _source = source


def avantages(entree: AvantagesEntree) -> SortieOutil[AvantagesDonnees]:
    avert: list[Avertissement] = []
    gouv_nom = None
    if entree.gouvernorat:
        gid = gouv_id_depuis_nom(entree.gouvernorat)
        if gid is None:
            avert.append(Avertissement(code=C.gouvernorat_non_reconnu, detail=entree.gouvernorat))
        else:
            gouv_nom = GOUVERNORATS[gid]
    if entree.zone_id is not None and entree.zone_id not in _zones_par_code():
        avert.append(Avertissement(code=C.zone_introuvable, zone_id=entree.zone_id))

    incitations = [i for i in _source.rechercher(entree.activite, gouv_nom, entree.zone_id)
                   if i.url or i.document]          # une incitation sans source est écartée
    if getattr(_source, "disponible", True) is False:
        avert.append(Avertissement(code=C.source_indisponible, detail="retrieval rôle 2 non branché"))
    if not incitations:
        avert.append(Avertissement(code=C.aucun_resultat))

    prov = [Provenance(type="url" if i.url else "document", url=i.url,
                       ids=[i.document] if i.document else [], date_donnees=i.date_source) for i in incitations]
    if entree.zone_id is not None:
        prov.append(Provenance(type="sql", table="afi.zones", ids=[str(entree.zone_id)],
                               date_donnees=DATE_INSTANTANE_AFI))
    # zones.zone_devreg (0/1) évoque « zone de développement régional », mais aucune définition
    # n'est confirmée : on ne l'expose pas comme un fait (null) tant que l'AFI ne l'a pas validé.
    return SortieOutil[AvantagesDonnees](
        outil="avantages",
        donnees=AvantagesDonnees(incitations=incitations, zone_developpement_regional=None),
        provenance=prov, avertissements=avert)
