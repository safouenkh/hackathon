"""Registre des outils du rôle 3 : nom -> fonction, schémas d'entrée/sortie, description.

Le rôle 1 peut générer les définitions d'outils du LLM à partir de `catalogue()`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel

from app.processing.avantages import avantages
from app.processing.demande import preparer_demande
from app.processing.lots import chercher_lots, comparer_lots, details_lot, lots_proches
from app.processing.schemas import (
    AvantagesDonnees, AvantagesEntree, ChercherLotsDonnees, ChercherLotsEntree, ComparerLotsDonnees,
    ComparerLotsEntree, DemarcheDonnees, DemarcheEntree, DetailsLotDonnees, DetailsLotEntree,
    LotsProchesDonnees, LotsProchesEntree, PreparerDemandeDonnees, PreparerDemandeEntree,
    ServicesAfiDonnees, ServicesAfiEntree, SortieOutil,
)
from app.processing.services import demarche, services_afi


@dataclass(frozen=True)
class Outil:
    nom: str
    description: str
    entree: type[BaseModel]
    donnees: type[BaseModel]
    fonction: Callable[..., SortieOutil]

    def sortie(self) -> type[BaseModel]:
        return SortieOutil[self.donnees]


OUTILS: dict[str, Outil] = {o.nom: o for o in [
    Outil("chercher_lots",
          "Lots candidats (SQL) filtrés par gouvernorat, zone, surface (m²), budget (DT), statut et proximité "
          "d'un équipement (pres_de + distance_max_km, ex. « près d'un port »). Tri par prix total indicatif "
          "croissant (« le moins cher ») ou par distance à l'équipement (tri=distance_equipement, « le plus proche »). "
          "Une seule recherche suffit pour « un lot de X m² près d'un port, le moins cher » : "
          "surface_min_m2=X, pres_de=port, distance_max_km=rayon. Statut par défaut : disponible.",
          ChercherLotsEntree, ChercherLotsDonnees, chercher_lots),
    Outil("details_lot", "Fiche d'un lot : zone, surface, statut, prix indicatif, commodités, services proches, documents.",
          DetailsLotEntree, DetailsLotDonnees, details_lot),
    Outil("comparer_lots", "Tableau comparatif de 2 à 10 lots (surface, prix, statut, distances) avec les meilleurs par critère.",
          ComparerLotsEntree, ComparerLotsDonnees, comparer_lots),
    Outil("lots_proches",
          "Zones triées par distance à un type d'équipement (port, gare, aéroport, autoroute, GP, banque…) "
          "ou à vol d'oiseau depuis un lot, une zone ou un point.",
          LotsProchesEntree, LotsProchesDonnees, lots_proches),
    Outil("avantages", "Incitations applicables à une activité / région, uniquement avec leurs sources (retrieval du rôle 2).",
          AvantagesEntree, AvantagesDonnees, lambda e, conn=None: avantages(e)),
    Outil("services_afi", "Les 8 services AFI et, si un besoin est donné, les services candidats (pour une question à choix).",
          ServicesAfiEntree, ServicesAfiDonnees, services_afi),
    Outil("demarche", "Conditions, étapes, pièces, frais, lieu de dépôt et lien source d'un service AFI ; "
          "service hors liste : contact AFI.",
          DemarcheEntree, DemarcheDonnees, demarche),
    Outil("preparer_demande", "Résumé prérempli d'une demande (lots, projet, pièces, frais) et liens vers l'AFI. "
          "Ne dépose rien : l'investisseur confirme et dépose lui-même.",
          PreparerDemandeEntree, PreparerDemandeDonnees, preparer_demande),
]}


def catalogue() -> list[dict[str, Any]]:
    return [{"nom": o.nom, "description": o.description,
             "entree": o.entree.model_json_schema(), "sortie": o.sortie().model_json_schema()}
            for o in OUTILS.values()]


def executer(nom: str, arguments: dict[str, Any]) -> SortieOutil:
    """Point d'entrée unique pour l'agent : valide les arguments puis exécute l'outil."""
    outil = OUTILS[nom]
    return outil.fonction(outil.entree.model_validate(arguments))
