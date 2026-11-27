"""Outil preparer_demande (BF11) : résumé prérempli, page du formulaire prérempli, liens vers l'AFI.

Il n'y a aucune intégration officielle : l'outil ne réserve aucun lot et ne dépose aucune demande.
Le dépôt reste une action de l'investisseur, après sa confirmation. Le service, ses pièces, ses
frais et son formulaire viennent de `demarche` (parcours publiés) ; le lien entre le statut d'un
lot et un service vient de l'ontologie ; les champs préremplis viennent de la base (formulaire.py).
"""
from __future__ import annotations

from sqlalchemy import Connection

from app.processing.formulaire import formulaires_preremplis, normaliser_projet
from app.processing.lots import _PRIX_EXCLUS, _connexion, balise_lot, construire_lot
from app.processing.reference import URL_CARTE_PUBLIQUE
from app.processing.schemas import (
    DATE_INSTANTANE_AFI, Avertissement, Balise, CodeAvertissement as C, DemarcheEntree, LienAction,
    PreparerDemandeDonnees, PreparerDemandeEntree, Provenance, SortieOutil,
)
from app.processing.services import demarche, services_par_code
from app.repositories import afi as repo
from app.semantique.ontologie import ontologie


def preparer_demande(entree: PreparerDemandeEntree, conn: Connection | None = None) -> SortieOutil[PreparerDemandeDonnees]:
    onto = ontologie()
    avert: list[Avertissement] = [Avertissement(code=C.confirmation_requise)]
    balises: list[Balise] = []
    ids = list(dict.fromkeys(entree.lot_ids))

    projet, a = normaliser_projet(entree.projet)
    avert += a
    with _connexion(conn) as c:
        lignes = repo.lots_par_ids(c, ids, _PRIX_EXCLUS) if ids else []
        dem = demarche(DemarcheEntree(service=entree.service, parcours=entree.parcours), conn=c)
        services = services_par_code(c, onto)
        trouves = {l.lot_id: construire_lot(l) for l in lignes}
        lots = [trouves[i] for i in ids if i in trouves]
        preremplis, a = formulaires_preremplis(c, [p.code for p in dem.donnees.parcours], lots, projet)
        avert += a

    statut_requis = onto.service(entree.service).exige_statut_lot
    for i in ids:
        if i not in trouves:
            avert.append(Avertissement(code=C.lot_introuvable, lot_id=i))
    for lot in lots:
        balises.append(balise_lot(lot))
        if statut_requis and lot.statut.value != statut_requis:
            avert.append(Avertissement(code=C.lot_non_disponible, lot_id=lot.lot_id, detail=lot.statut.value))
        autre = onto.service_du_statut(lot.statut.value)
        if autre and autre != entree.service and autre in services:
            balises.append(Balise(type="CHOIX", libelle=services[autre].nom))
        for code in lot.avertissements:
            avert.append(Avertissement(code=code, lot_id=lot.lot_id))

    manquants = [k for k, v in projet.model_dump().items() if v is None]

    surfaces = [l.surface_m2 for l in lots]
    prix = [l.prix_total_indicatif_dt for l in lots]
    surface_totale = sum(surfaces) if lots and None not in surfaces else None
    prix_total = sum(prix) if lots and None not in prix else None

    parcours = dem.donnees.parcours
    avert += dem.avertissements
    balises += dem.balises
    liens = [LienAction(libelle="Source de la démarche (AFI)", url=u)
             for u in dict.fromkeys(p.url_source for p in parcours if p.url_source)]
    if lots:
        liens.append(LienAction(libelle="Carte publique des lots AFI", url=URL_CARTE_PUBLIQUE))

    donnees = PreparerDemandeDonnees(
        service=dem.donnees.service, parcours=[p.code for p in parcours], lots=lots,
        surface_totale_m2=surface_totale, prix_total_indicatif_dt=prix_total, projet=projet,
        informations_projet_manquantes=manquants,
        pieces_a_preparer=[e for p in parcours for e in p.pieces],
        frais=[e for p in parcours for e in p.frais],
        frais_sans_montant=list(dict.fromkeys(x for p in parcours for x in p.frais_sans_montant)),
        lieu_depot=list(dict.fromkeys(x for p in parcours for x in p.lieu_depot)),
        formulaires=list({f.code: f for p in parcours for f in p.formulaires}.values()),
        formulaires_preremplis=preremplis, liens=liens)
    prov = list(dem.provenance)
    if lots:
        prov.insert(0, Provenance(type="sql", table="afi.lots", ids=[str(l.lot_id) for l in lots],
                                  date_donnees=DATE_INSTANTANE_AFI))
    # Dédoublonnage des avertissements et des balises identiques
    vus, uniques = set(), []
    for a in avert:
        k = (a.code, a.lot_id, a.zone_id, a.detail)
        if k not in vus:
            vus.add(k)
            uniques.append(a)
    return SortieOutil[PreparerDemandeDonnees](
        outil="preparer_demande", donnees=donnees, provenance=prov, avertissements=uniques,
        balises=list({b.texte: b for b in balises}.values()))
