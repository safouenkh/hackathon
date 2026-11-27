"""Registre des outils du rôle 3 : nom -> fonction, schémas d'entrée/sortie, description.

Le rôle 1 peut générer les définitions d'outils du LLM à partir de `catalogue()`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel

from app.processing.avantages import avantages
from app.processing.connaissances_afi import connaissances_afi
from app.processing.demande import preparer_demande
from app.processing.demarches_admin import demarches_administratives
from app.processing.lots import chercher_lots, comparer_lots, details_lot, lots_proches
from app.processing.schemas import (
    AvantagesDonnees, AvantagesEntree, ChercherLotsDonnees, ConnaissancesAfiDonnees, ConnaissancesAfiEntree, ChercherLotsEntree, ComparerLotsDonnees,
    ComparerLotsEntree, DemarcheDonnees, DemarcheEntree, DemarchesAdministrativesDonnees,
    DemarchesAdministrativesEntree, DetailsLotDonnees, DetailsLotEntree,
    GuiderServiceDonnees, GuiderServiceEntree, LotsProchesDonnees, LotsProchesEntree, NoterBesoinDonnees,
    NoterBesoinEntree, PreparerDemandeDonnees, PreparerDemandeEntree, ReglesZoneDonnees, ReglesZoneEntree,
    ServicesAfiDonnees, ServicesAfiEntree, SortieOutil,
)
from app.processing.formulaire import noter_besoin
from app.processing.regles import regles_zone
from app.processing.services import demarche, guider_service, services_afi


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
    Outil("services_afi", "Les services AFI et, si un besoin est donné, les services candidats (pour une question à choix).",
          ServicesAfiEntree, ServicesAfiDonnees, services_afi),
    Outil("demarche", "Fiche publiée d'un service AFI : conditions, étapes, pièces, frais, lieu de dépôt, formulaire "
          "et lien source, plus les fiches validées de l'AFI en complément. Plusieurs parcours (ex. selon la zone) : "
          "demander lequel. Service hors liste : contact AFI.",
          DemarcheEntree, DemarcheDonnees, demarche),
    Outil("guider_service", "Guide l'investisseur pas à pas dans un parcours : un point à la fois (condition, pièce, "
          "formulaire, étape, frais, lieu de dépôt), avec sa source. Commencer à position=0, puis passer `suivant`.",
          GuiderServiceEntree, GuiderServiceDonnees, guider_service),
    Outil("preparer_demande", "Résumé prérempli d'une demande (lots, projet, pièces, frais, formulaire) et lien vers "
          "la page du formulaire prérempli, où l'investisseur complète son contact, relit, imprime ou envoie. "
          "Ne dépose rien. Ne jamais demander dans le chat le nom, la CIN, le passeport, le téléphone ou l'adresse.",
          PreparerDemandeEntree, PreparerDemandeDonnees, preparer_demande),
    Outil("noter_besoin", "Note une question hors des services AFI pour l'analyse des besoins (BF24), après avoir "
          "donné le contact AFI. Recopier la question sans nom ni numéro personnel.",
          NoterBesoinEntree, NoterBesoinDonnees, noter_besoin),
    Outil("regles_zone", "Règles du cahier des charges d'une zone (hauteur, recul, activités, clôtures, rejets…) : "
          "extraits exacts avec article et pages, recherchés dans le cahier de CETTE zone seulement. Donner la zone "
          "(zone_id, zone_nom ou lot_id) et la question. Si le cahier distingue des catégories (categorie_a_preciser), "
          "demander laquelle. Zone sans cahier : le dire, ne jamais prendre les règles d'une autre zone.",
          ReglesZoneEntree, ReglesZoneDonnees, regles_zone),
    Outil("demarches_administratives",
          "Démarches administratives HORS AFI utiles au projet (fiches du portail SICAD) : raccordement à "
          "l'assainissement, étude d'impact sur l'environnement, importation, exportation et aides à l'export, "
          "contrôle qualité, métrologie, énergie, activités soumises à un cahier des charges d'activité "
          "(commerce, distribution, métiers)… Rend pour chaque fiche les conditions, pièces, étapes, lieu de dépôt, "
          "délai, références et l'organisme, avec le lien. Donner le besoin et l'activité EN FRANÇAIS. Fiches "
          "datées (donnee_non_fraiche) : dire de vérifier sur le lien. Pour les 8 services de l'AFI : outil demarche.",
          DemarchesAdministrativesEntree, DemarchesAdministrativesDonnees, demarches_administratives),
    Outil("connaissances_afi",
          "Fiches validées par l'AFI (texte intégral) les plus proches de la question : présentation, missions et "
          "chiffres de l'AFI, zones aménagées, en cours ou programmées, obligations de l'acquéreur (délais de "
          "construction, clôture), règles générales de construction et réseaux, déclaration de projet à l'APII "
          "(pièces, TRE, fonds propres), études et données industrielles par gouvernorat ou secteur. Donner la "
          "question EN FRANÇAIS. Pour les règles d'UNE zone : regles_zone d'abord ; pour un service AFI : demarche.",
          ConnaissancesAfiEntree, ConnaissancesAfiDonnees, connaissances_afi),
]}


def catalogue() -> list[dict[str, Any]]:
    return [{"nom": o.nom, "description": o.description,
             "entree": o.entree.model_json_schema(), "sortie": o.sortie().model_json_schema()}
            for o in OUTILS.values()]


def executer(nom: str, arguments: dict[str, Any]) -> SortieOutil:
    """Point d'entrée unique pour l'agent : valide les arguments puis exécute l'outil."""
    outil = OUTILS[nom]
    return outil.fonction(outil.entree.model_validate(arguments))
