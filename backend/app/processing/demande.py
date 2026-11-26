"""Outil preparer_demande (BF11) : résumé prérempli + liens vers l'AFI.

Il n'y a aucune intégration officielle : l'outil ne réserve aucun lot et ne dépose aucune demande.
Le dépôt reste une action de l'investisseur, après sa confirmation.
"""
from __future__ import annotations

from sqlalchemy import Connection

from app.processing.lots import _PRIX_EXCLUS, _connexion, balise_lot, construire_lot
from app.processing.reference import GOUVERNORATS, URL_CARTE_PUBLIQUE, URL_SERVICES_AFI, gouv_id_depuis_nom
from app.processing.schemas import (
    DATE_INSTANTANE_AFI, Avertissement, Balise, CodeAvertissement as C, DemarcheEntree, LienAction,
    PreparerDemandeDonnees, PreparerDemandeEntree, Projet, Provenance, ServiceAfiId, SortieOutil, StatutLot,
)
from app.processing.services import SERVICES, demarche
from app.repositories import afi as repo


def preparer_demande(entree: PreparerDemandeEntree, conn: Connection | None = None) -> SortieOutil[PreparerDemandeDonnees]:
    avert: list[Avertissement] = [Avertissement(code=C.confirmation_requise)]
    balises: list[Balise] = []
    ids = list(dict.fromkeys(entree.lot_ids))

    with _connexion(conn) as c:
        lignes = repo.lots_par_ids(c, ids, _PRIX_EXCLUS) if ids else []
        dem = demarche(DemarcheEntree(service=entree.service.value, variante=entree.variante), conn=c)

    trouves = {l.lot_id: construire_lot(l) for l in lignes}
    lots = [trouves[i] for i in ids if i in trouves]
    for i in ids:
        if i not in trouves:
            avert.append(Avertissement(code=C.lot_introuvable, lot_id=i))
    for lot in lots:
        balises.append(balise_lot(lot))
        if entree.service is ServiceAfiId.acquisition and lot.statut is not StatutLot.disponible:
            avert.append(Avertissement(code=C.lot_non_disponible, lot_id=lot.lot_id, detail=lot.statut.value))
            if lot.statut is StatutLot.aux_encheres:
                balises.append(Balise(type="CHOIX", libelle=SERVICES[ServiceAfiId.encheres].nom))
        for code in lot.avertissements:
            avert.append(Avertissement(code=code, lot_id=lot.lot_id))

    projet = entree.projet
    if projet.gouvernorat:
        gid = gouv_id_depuis_nom(projet.gouvernorat)
        if gid is None:
            avert.append(Avertissement(code=C.gouvernorat_non_reconnu, detail=projet.gouvernorat))
        else:
            projet = projet.model_copy(update={"gouvernorat": GOUVERNORATS[gid]})
    manquants = [k for k, v in projet.model_dump().items() if v is None]

    surfaces = [l.surface_m2 for l in lots]
    prix = [l.prix_total_indicatif_dt for l in lots]
    surface_totale = sum(surfaces) if lots and None not in surfaces else None
    prix_total = sum(prix) if lots and None not in prix else None

    fiches = dem.donnees.fiches
    pieces = [g for f in fiches for g in f.pieces]
    frais = [x for f in fiches for x in f.frais]
    lieu = list(dict.fromkeys(x for f in fiches for x in f.lieu_depot))
    avert += [a for a in dem.avertissements if a.code is not C.service_non_couvert]
    balises += [b for b in dem.balises if b.type == "CHOIX"]

    liens = [LienAction(libelle="Services de l'AFI (source des démarches)", url=URL_SERVICES_AFI)]
    if lots:
        liens.append(LienAction(libelle="Carte publique des lots AFI", url=URL_CARTE_PUBLIQUE))

    donnees = PreparerDemandeDonnees(
        service=SERVICES[entree.service], lots=lots, surface_totale_m2=surface_totale,
        prix_total_indicatif_dt=prix_total, projet=projet, informations_projet_manquantes=manquants,
        pieces_a_preparer=pieces, frais=frais, lieu_depot=lieu, liens=liens)
    prov = list(dem.provenance)
    if lots:
        prov.insert(0, Provenance(type="sql", table="afi.lots", ids=[str(l.lot_id) for l in lots],
                                  date_donnees=DATE_INSTANTANE_AFI))
    # Dédoublonnage des avertissements identiques
    vus, uniques = set(), []
    for a in avert:
        k = (a.code, a.lot_id, a.zone_id, a.detail)
        if k not in vus:
            vus.add(k)
            uniques.append(a)
    return SortieOutil[PreparerDemandeDonnees](
        outil="preparer_demande", donnees=donnees, provenance=prov, avertissements=uniques, balises=balises)
