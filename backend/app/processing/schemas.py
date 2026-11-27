"""Contrat JSON des outils du rôle 3 (PROPOSITION, à valider avec le rôle 1).

Règles communes à toutes les sorties (`SortieOutil`) :
- `donnees` : uniquement des faits ou des extraits de source (jamais de texte rédigé : c'est le LLM qui rédige) ;
- `provenance` : d'où vient chaque fait (table + identifiants, ou URL) ;
- `avertissements` : codes que le LLM doit restituer ; ceux propres à un lot sont aussi dans `Lot.avertissements` ;
- `balises` : éléments prêts à insérer dans la réponse ([[ZONE:..]], [[LOT:..]], [[CHOIX:..]], [[PDF:..]]).
Un champ inconnu vaut `null` et s'accompagne d'un avertissement.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.processing.reference import TypeCommodite, TypeServiceProximite

# Date de génération du dump AFI utilisé (en-tête de afi.sql).
DATE_INSTANTANE_AFI = date(2026, 11, 13)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# =====================================================================
# Éléments communs
# =====================================================================

class CodeAvertissement(str, Enum):
    prix_indicatif = "prix_indicatif"              # prix tiré d'un instantané, jamais un prix actuel
    prix_inconnu = "prix_inconnu"                  # prix absent ou à 0 dans les données
    prix_suspect = "prix_suspect"                  # valeur aberrante connue : prix non communiqué
    prix_ecart_site_public = "prix_ecart_site_public"  # le site public affichait un autre prix le 26/11/2026
    statut_inconnu = "statut_inconnu"              # « gris » : pas d'information
    donnee_non_fraiche = "donnee_non_fraiche"      # disponibilité à reconfirmer auprès de l'AFI
    surface_invalide = "surface_invalide"          # surface ≤ 0 dans les données
    lot_orphelin = "lot_orphelin"                  # lot sans zone connue : zone jamais devinée
    lot_introuvable = "lot_introuvable"
    lot_non_disponible = "lot_non_disponible"
    zone_introuvable = "zone_introuvable"
    gouvernorat_non_reconnu = "gouvernorat_non_reconnu"
    gouvernorat_deduit = "gouvernorat_deduit"      # correspondance gouv_id déduite, non lue sur le site
    coordonnees_manquantes = "coordonnees_manquantes"
    distance_ambigue = "distance_ambigue"          # valeur de distance non exploitable (ex. « 127 - 115 km »)
    donnee_incoherente = "donnee_incoherente"      # ligne écartée (unité inattendue, valeur de test)
    # Valeur absente de la base AFI, reprise d'une autre source (assistant.zone_complements) :
    # à donner en précisant qu'elle est à confirmer auprès de l'AFI (detail = champ et source).
    valeur_complementaire = "valeur_complementaire"
    activite_non_filtree = "activite_non_filtree"  # aucune donnée SQL sur les activités autorisées
    budget_non_verifiable = "budget_non_verifiable"  # lots sans prix exclus d'une recherche par budget
    resultats_tronques = "resultats_tronques"
    aucun_resultat = "aucun_resultat"
    document_sans_lien = "document_sans_lien"      # aucune URL publique connue pour le fichier
    service_non_couvert = "service_non_couvert"    # orienter vers le contact AFI (BF24)
    besoin_non_reconnu = "besoin_non_reconnu"      # poser une question à choix (BF22)
    lieu_depot_non_precise = "lieu_depot_non_precise"
    frais_non_chiffres = "frais_non_chiffres"      # la source cite des frais sans montant
    extraction_partielle = "extraction_partielle"  # fiche source au format inattendu
    point_a_verifier = "point_a_verifier"          # une ligne porte une note : à confirmer auprès de l'AFI
    demarche_non_publiee = "demarche_non_publiee"  # aucun parcours publié : orienter vers le contact AFI
    parcours_a_choisir = "parcours_a_choisir"      # le service a plusieurs parcours : demander lequel
    parcours_inconnu = "parcours_inconnu"
    position_hors_parcours = "position_hors_parcours"
    source_indisponible = "source_indisponible"    # module de retrieval (rôle 2) non branché
    confirmation_requise = "confirmation_requise"  # rien n'est déposé sans l'investisseur (BF11)
    valeur_non_preremplie = "valeur_non_preremplie"  # lots aux valeurs différentes : le client choisit (detail = champ)
    formulaire_indisponible = "formulaire_indisponible"  # le parcours n'a pas de formulaire (ex. enchères)


class Avertissement(_Strict):
    code: CodeAvertissement
    lot_id: int | None = None
    zone_id: int | None = None
    detail: str | None = None                      # précision factuelle (jamais une phrase à afficher)


class Provenance(_Strict):
    type: Literal["sql", "url", "document"]
    table: str | None = None                       # ex. "afi.lots"
    ids: list[str] = Field(default_factory=list)   # identifiants des lignes utilisées
    url: str | None = None
    date_donnees: date | None = None               # date de l'instantané ou de la lecture


class Balise(_Strict):
    type: Literal["ZONE", "LOT", "CHOIX", "PDF"]
    id: str | None = None                          # code_zone, lot_id ou URL (PDF)
    libelle: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def texte(self) -> str:
        lib = _nettoyer_balise(self.libelle)
        if self.type == "CHOIX":
            return f"[[CHOIX:{lib}]]"
        return f"[[{self.type}:{self.id}:{lib}]]"


def _nettoyer_balise(s: str) -> str:
    # Le libellé ne doit pas casser le format [[TYPE:id:libellé]].
    return s.replace("[", "(").replace("]", ")").replace(":", " -").strip()


T = TypeVar("T")


class SortieOutil(_Strict, Generic[T]):
    outil: str
    donnees: T
    provenance: list[Provenance]
    avertissements: list[Avertissement] = Field(default_factory=list)
    balises: list[Balise] = Field(default_factory=list)


# =====================================================================
# Lots et zones
# =====================================================================

class StatutLot(str, Enum):
    disponible = "disponible"
    non_disponible = "non_disponible"   # déjà acheté / réservé / attribué
    aux_encheres = "aux_encheres"
    inconnu = "inconnu"                 # « gris » : pas d'information


class Coordonnees(_Strict):
    lat: float
    lon: float


class Lot(_Strict):
    lot_id: int
    numero: str | None
    zone_id: int | None                 # null si lot orphelin
    zone_nom: str | None
    gouvernorat: str | None
    surface_m2: int | None
    prix_indicatif_dt_m2: int | None
    prix_total_indicatif_dt: int | None  # surface_m2 × prix_indicatif_dt_m2, calculé par l'outil
    statut: StatutLot
    code_etape: int | None              # code brut LOT_ETAPE, pour traçabilité
    # Rempli par chercher_lots quand `pres_de` est donné : distance de la zone à cet équipement.
    distance_equipement_km: float | None = None
    equipement_nom: str | None = None
    avertissements: list[CodeAvertissement] = Field(default_factory=list)


class ZoneResume(_Strict):
    zone_id: int
    nom: str | None
    nom_ar: str | None
    gouvernorat: str | None
    prix_indicatif_dt_m2: int | None
    coordonnees: Coordonnees | None
    visible_carte_publique: bool


class Commodite(_Strict):
    type: TypeCommodite
    libelle_type: str                   # libellé officiel de la carte publique
    nom: str | None                     # ex. « Tunis Carthage », « A1 »
    valeur_texte: str | None            # tel que dans les données (« 3,5 km », « 100 Kva/Hec », « actif »)
    distance_km: float | None           # seulement pour aéroport/port/gare/autoroute/GP, si non ambigu


class ServiceProximite(_Strict):
    categorie: TypeServiceProximite
    nom: str | None
    distance_km: float | None
    source: str                         # « osm » = OpenStreetMap


class DocumentZone(_Strict):
    document_id: int
    type: str                           # cahier_charges, plan_lotissement
    nom: str | None
    url: str | None                     # null tant qu'aucune URL publique n'est configurée


# ---------- chercher_lots ----------

TypeProximite = TypeCommodite | TypeServiceProximite
_TYPES_NON_DISTANCE = (TypeCommodite.electricite, TypeCommodite.eau_potable, TypeCommodite.gaz_naturel,
                       TypeCommodite.maintenance_gmg, TypeCommodite.telephone, TypeCommodite.otc)


class TriLots(str, Enum):
    prix_total = "prix_total"                    # prix total indicatif croissant, puis surface
    distance_equipement = "distance_equipement"  # distance à `pres_de` croissante, puis prix total


class ChercherLotsEntree(_Strict):
    gouvernorat: str | None = None
    zone_ids: list[int] | None = Field(default=None, max_length=50)
    zone_nom: str | None = Field(default=None, max_length=100)
    surface_min_m2: int | None = Field(default=None, ge=0, description="Pour « un lot de X m² », mettre X.")
    surface_max_m2: int | None = Field(default=None, ge=0)
    budget_max_dt: int | None = Field(default=None, ge=0)   # comparé à prix_total_indicatif_dt
    pres_de: TypeProximite | None = Field(
        default=None, description="Équipement proche voulu (port, gare, aeroport, autoroute, route_gp, bank…).")
    distance_max_km: float | None = Field(
        default=None, gt=0, description="Distance maximale de la zone à `pres_de`, en km (distance AFI/OSM).")
    tri: TriLots = TriLots.prix_total
    activite: str | None = Field(default=None, max_length=200)  # non filtrable en SQL : avertissement
    statuts: list[StatutLot] = Field(default_factory=lambda: [StatutLot.disponible], min_length=1)
    limite: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _bornes(self):
        if self.surface_min_m2 is not None and self.surface_max_m2 is not None \
                and self.surface_min_m2 > self.surface_max_m2:
            raise ValueError("surface_min_m2 > surface_max_m2")
        if self.pres_de in _TYPES_NON_DISTANCE:
            raise ValueError("pres_de doit être un équipement mesuré en distance (port, gare, aeroport…)")
        if (self.distance_max_km is not None or self.tri is TriLots.distance_equipement) and self.pres_de is None:
            raise ValueError("distance_max_km et tri=distance_equipement exigent pres_de")
        # « Près de » sans rayon ni tri par distance ne filtrerait rien : refusé pour éviter
        # de présenter comme « proche » un lot à 150 km.
        if self.pres_de is not None and self.distance_max_km is None and self.tri is not TriLots.distance_equipement:
            raise ValueError("pres_de exige distance_max_km (rayon en km) ou tri=distance_equipement")
        return self


class ChercherLotsDonnees(_Strict):
    lots: list[Lot]
    total_correspondants: int           # avant application de la limite
    criteres_appliques: ChercherLotsEntree
    tri: TriLots


# ---------- details_lot ----------

class DetailsLotEntree(_Strict):
    lot_id: int


class DetailsLotDonnees(_Strict):
    lot: Lot | None
    zone: ZoneResume | None
    commodites_zone: list[Commodite] = Field(default_factory=list)
    services_proximite: list[ServiceProximite] = Field(default_factory=list)
    documents_zone: list[DocumentZone] = Field(default_factory=list)
    a_un_polygone: bool = False         # polygone KML présent pour (zone, numéro)


# ---------- comparer_lots ----------

class ComparerLotsEntree(_Strict):
    lot_ids: list[int] = Field(min_length=2, max_length=10)


class LigneComparaison(_Strict):
    lot: Lot
    distances_km: dict[TypeCommodite, float | None]   # aéroport, port, gare, autoroute, GP


class ComparerLotsDonnees(_Strict):
    lignes: list[LigneComparaison]
    # Calculés par l'outil (ex-aequo possibles) ; vides si la valeur manque partout.
    prix_total_le_plus_bas: list[int]
    prix_m2_le_plus_bas: list[int]
    surface_la_plus_grande: list[int]
    plus_proche: dict[TypeCommodite, list[int]]


# ---------- lots_proches ----------

class LotsProchesEntree(_Strict):
    """Deux usages :
    - `type` seul : zones triées par leur distance à ce type d'équipement (données AFI / OSM) ;
    - une référence (`lot_id`, `zone_id` ou `point`) : zones triées par distance à vol d'oiseau
      depuis cette référence ; si `type` est aussi donné, sa distance est ajoutée à chaque zone.
    """
    type: TypeProximite | None = None
    lot_id: int | None = None
    zone_id: int | None = None
    point: Coordonnees | None = None
    gouvernorat: str | None = None
    distance_max_km: float | None = Field(default=None, gt=0)
    uniquement_avec_lots_disponibles: bool = True
    limite: int = Field(default=10, ge=1, le=50)

    @model_validator(mode="after")
    def _au_moins_un(self):
        refs = [x for x in (self.lot_id, self.zone_id, self.point) if x is not None]
        if len(refs) > 1:
            raise ValueError("une seule référence parmi lot_id, zone_id, point")
        if not refs and self.type is None:
            raise ValueError("donner un type d'équipement ou une référence (lot_id, zone_id, point)")
        if self.type in _TYPES_NON_DISTANCE:
            raise ValueError("ce type n'est pas une distance ; voir details_lot")
        return self


class ZoneProche(_Strict):
    zone: ZoneResume
    distance_km: float                  # clé de tri
    mode_distance: Literal["equipement_selon_donnees", "vol_oiseau_depuis_reference"]
    equipement_nom: str | None = None
    equipement_distance_km: float | None = None
    nb_lots_disponibles: int
    nb_lots_aux_encheres: int


class LotsProchesDonnees(_Strict):
    zones: list[ZoneProche]
    reference: Coordonnees | None
    total_correspondants: int


# =====================================================================
# Services AFI et démarches
# =====================================================================

# Les services, leurs parcours et leur contenu viennent du schéma `assistant` (versions publiées) ;
# les synonymes et les liens vers les fiches de l'AFI, de l'ontologie (ontology/afi_ontology.ttl).

class ServiceAfi(_Strict):
    id: str                             # assistant.services.code
    nom: str
    besoin: str | None                  # besoin de l'investisseur (cahier §IV.6)
    fiches: list[int]                   # afi.chatbot_connaissances.id liées (ontologie)


class ServiceCandidat(_Strict):
    service: ServiceAfi
    score: int                          # somme des longueurs des mots-clés reconnus (plus = plus spécifique)
    mots_cles_reconnus: list[str]


class ContactAfi(_Strict):
    adresse: str | None
    telephone: str | None
    site: str | None
    fiche: int | None                   # afi.chatbot_connaissances.id d'où vient le contact


class ServicesAfiEntree(_Strict):
    besoin: str | None = Field(default=None, max_length=500)


class ServicesAfiDonnees(_Strict):
    services: list[ServiceAfi]          # services actifs, dans l'ordre de la base
    candidats: list[ServiceCandidat]    # triés, si un besoin est donné
    contact_afi: ContactAfi


class DemarcheEntree(_Strict):
    service: str = Field(max_length=100, description="Code d'un service renvoyé par services_afi (champ id).")
    parcours: str | None = Field(
        default=None, max_length=100,
        description="Code du parcours choisi quand le service en a plusieurs (ex. selon la zone) ; sinon vide.")


class ElementDemarche(_Strict):
    """Une ligne d'une fiche publiée, telle quelle, avec ses sous-lignes."""
    id: int                             # assistant.parcours_elements.id
    type: str                           # condition, etape, piece, frais, lien, description…
    groupe: str | None                  # ex. « I – Phase de réservation : »
    ordre: int
    texte: str
    url: str | None = None
    montant_dt: float | None = None     # seulement pour type = frais
    unite_montant: str | None = None    # ex. « par copie »
    a_verifier: bool = False            # écart entre sources : à confirmer auprès de l'AFI
    note_verification: str | None = None
    corrige: bool = False               # texte différent de la fiche source (correction sourcée)
    enfants: list["ElementDemarche"] = Field(default_factory=list)


class VarianteFormulaire(_Strict):
    langue: str
    titre_officiel: str
    url_page: str | None
    url_fichier: str | None


class FormulaireService(_Strict):
    code: str
    titre: str
    valeurs_imposees: dict[str, Any]    # ex. {"document_demande": "3"} : ligne à cocher
    a_verifier: bool
    note_verification: str | None
    variantes: list[VarianteFormulaire]


class ParcoursDemarche(_Strict):
    code: str
    titre: str                          # intitulé d'origine
    critere_choix: str | None           # ex. « zones de développement régional »
    version: int
    publie_le: datetime
    url_source: str | None
    date_collecte: date | None
    description: list[ElementDemarche]
    pour_qui: list[ElementDemarche]
    conditions: list[ElementDemarche]
    etapes: list[ElementDemarche]
    pieces: list[ElementDemarche]
    frais: list[ElementDemarche]        # montants en dinars cités par la fiche
    liens: list[ElementDemarche]
    remarques: list[ElementDemarche]
    lieu_depot: list[str]               # phrases de la fiche qui disent où déposer (vide : non précisé)
    frais_sans_montant: list[str]       # lignes qui citent un paiement sans montant
    formulaires: list[FormulaireService]


class FicheAfi(_Strict):
    fiche: int                          # afi.chatbot_connaissances.id
    question: str
    reponse: str                        # texte intégral validé par l'AFI


class DemarcheDonnees(_Strict):
    service: ServiceAfi | None
    parcours: list[ParcoursDemarche]    # référence : fiches publiées
    fiches_afi: list[FicheAfi]          # compléments : réponses validées par l'AFI
    contact_afi: ContactAfi


# ---------- guider_service : un point à la fois ----------

# Les liens de la fiche sont repris par le formulaire et par le texte des pièces : pas de rubrique à part.
RubriqueGuide = Literal["presentation", "description", "pour_qui", "condition", "piece", "formulaire",
                        "etape", "frais", "remarque", "lieu_depot"]


class GuiderServiceEntree(_Strict):
    parcours: str = Field(max_length=100, description="Code du parcours (champ parcours[].code de demarche).")
    position: int = Field(default=0, ge=0, le=500,
                          description="Point à montrer : 0 au début, puis la valeur `suivant` de la réponse précédente.")


class PointGuide(_Strict):
    rubrique: RubriqueGuide
    groupe: str | None = None
    element: ElementDemarche | None = None
    formulaire: FormulaireService | None = None
    fiches_afi: list[FicheAfi] = Field(default_factory=list)
    lieu_depot: list[str] = Field(default_factory=list)
    contact_afi: ContactAfi | None = None


class EtapePlan(_Strict):
    rubrique: RubriqueGuide
    debut: int                          # position du premier point de cette rubrique
    nombre: int


class GuiderServiceDonnees(_Strict):
    service: ServiceAfi | None
    parcours: str
    titre: str | None
    url_source: str | None
    position: int
    total: int
    point: PointGuide | None
    precedent: int | None
    suivant: int | None                 # null : dernier point
    plan: list[EtapePlan]


# =====================================================================
# Avantages (incitations) : interface vers le retrieval du rôle 2
# =====================================================================

class AvantagesEntree(_Strict):
    activite: str | None = Field(default=None, max_length=200)
    gouvernorat: str | None = None
    zone_id: int | None = None


class Incitation(_Strict):
    intitule: str
    extrait: str                        # texte exact de la source
    organisme: str | None
    url: str | None
    document: str | None
    page: int | None
    date_source: date | None


class AvantagesDonnees(_Strict):
    incitations: list[Incitation]
    zone_developpement_regional: bool | None   # zones.zone_devreg, signification non confirmée -> null


# =====================================================================
# preparer_demande
# =====================================================================

class Projet(_Strict):
    """Données du projet, sans aucune donnée personnelle (pas de nom, CIN, téléphone, RNE)."""
    activite: str | None = Field(default=None, max_length=200)
    nombre_emplois: int | None = Field(default=None, ge=0)
    investissement_dt: int | None = Field(default=None, ge=0)
    surface_souhaitee_m2: int | None = Field(default=None, ge=0)
    gouvernorat: str | None = None


class PreparerDemandeEntree(_Strict):
    service: str = Field(max_length=100, description="Code du service (services_afi), ex. celui de l'acquisition.")
    parcours: str | None = Field(default=None, max_length=100, description="Code du parcours choisi, si plusieurs.")
    lot_ids: list[int] = Field(default_factory=list, max_length=10)
    projet: Projet = Field(default_factory=Projet)


class LienAction(_Strict):
    libelle: str
    url: str


class ChampACompleter(_Strict):
    code: str
    libelle: str                                # libellé officiel dans la langue du formulaire


class FormulairePrerempli(_Strict):
    """Page du formulaire préremplie : le client y complète son contact, relit, imprime ou envoie."""
    parcours: str
    formulaire: str
    langue: str                                 # langue officielle de cette variante
    url_page: str                               # page de Dalila (aucune donnée de contact dans l'URL)
    valeurs: dict[str, str]                     # champs « projet » préremplis ou imposés, par code
    champs_projet_a_completer: list[ChampACompleter]  # l'agent peut les demander dans le chat


class PreparerDemandeDonnees(_Strict):
    service: ServiceAfi | None
    parcours: list[str]                         # codes des parcours utilisés
    lots: list[Lot]
    surface_totale_m2: int | None
    prix_total_indicatif_dt: int | None
    projet: Projet
    informations_projet_manquantes: list[str]   # champs de Projet non renseignés
    pieces_a_preparer: list[ElementDemarche]
    frais: list[ElementDemarche]
    frais_sans_montant: list[str]
    lieu_depot: list[str]
    formulaires: list[FormulaireService]
    formulaires_preremplis: list[FormulairePrerempli]
    liens: list[LienAction]
    depot_effectue: Literal[False] = False      # l'outil ne dépose jamais rien
    confirmation_requise: Literal[True] = True


# ---------------------------------------------------------------------
# BF24 : question hors des services, notée pour l'analyse des besoins
# ---------------------------------------------------------------------

class NoterBesoinEntree(_Strict):
    question: str = Field(min_length=1, max_length=500,
                          description="La question de l'investisseur, telle quelle, sans nom ni numéro personnel.")
    langue: str | None = Field(default=None, max_length=20)


class NoterBesoinDonnees(_Strict):
    note: bool                                  # false : enregistrement indisponible (rien n'est perdu côté client)


# ---------------------------------------------------------------------
# Page formulaire (front React) et envoi d'une demande
# ---------------------------------------------------------------------

CategorieChamp = Literal["projet", "contact", "non_enregistre", "reserve_afi"]


class ChoixPage(_Strict):
    valeur: str
    libelle: str | None                         # dans la langue du formulaire
    traduction: str | None                      # dans la langue d'aide, si différente


class ChampPage(_Strict):
    code: str
    type: str
    categorie: CategorieChamp
    unite: str | None
    obligatoire: bool | None                    # null : le formulaire ne le précise pas
    libelle: str                                # libellé officiel de la variante
    aide: str | None                            # texte imprimé à côté (ex. « (Norme AFI =100 Kva/Ha) »)
    traduction: str | None                      # libellé dans la langue d'aide ; officiel=false si traduction
    traduction_officielle: bool | None
    choix: list[ChoixPage] | None
    valeur: str | None                          # préremplie ou imposée (champs « projet » seulement)
    origine_valeur: str | None                  # ex. « lot.zone_nom », « projet.activite », « parcours »
    impose: bool


class MentionPage(_Strict):
    texte: str
    si_champ: str | None
    si_valeur: str | None


class SectionPage(_Strict):
    code: str
    libelle: str | None
    traduction: str | None
    champs: list[ChampPage]
    mentions: list[MentionPage]


class Consentement(_Strict):
    version: str
    texte: str


class FormulairePage(_Strict):
    parcours: str
    parcours_titre: str
    service: str
    version: int                                # version publiée du parcours
    formulaire: str
    titre_officiel: str
    langue: str                                 # langue officielle affichée
    langues: list[str]                          # variantes officielles disponibles
    langue_aide: str | None                     # langue des traductions affichées
    url_fichier: str | None                     # PDF vierge officiel
    url_source: str | None                      # page AFI du service
    sections: list[SectionPage]
    lots: list[Lot]
    avertissements: list[Avertissement]
    note_verification: str | None               # point du formulaire à confirmer auprès de l'AFI
    consentement: Consentement


class EnvoiDemande(_Strict):
    parcours: str = Field(max_length=100)
    langue: str = Field(max_length=10)
    lot_ids: list[int] = Field(default_factory=list, max_length=10)
    valeurs: dict[str, str] = Field(default_factory=dict, max_length=80)    # champs « projet »
    contact: dict[str, str] = Field(default_factory=dict, max_length=30)    # champs « contact »
    consentement: bool
    consentement_version: str = Field(max_length=40)
    langue_aide: str | None = Field(default=None, max_length=10)   # langue du texte d'accord affiché


class DemandeEnvoyee(_Strict):
    reference: str
    envoyee_le: datetime
    depot_officiel_effectue: Literal[False] = False   # le client dépose encore le formulaire signé à l'AFI
