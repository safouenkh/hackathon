import time

import pytest

from app.processing.lots import chercher_lots, comparer_lots, details_lot, lots_proches
from app.processing.reference import TypeCommodite
from app.processing.schemas import (
    ChercherLotsEntree, CodeAvertissement as C, ComparerLotsEntree, DetailsLotEntree,
    LotsProchesEntree, StatutLot,
)
from tests.conftest import (
    LOT_COORD_INVALIDES, LOT_ENCHERES_ARIANA, LOT_GRIS, LOT_ORPHELIN, LOT_PRIX_ABERRANT,
    LOT_RAS_EL_MORJ_37, LOT_SURFACE_NEGATIVE, assert_aucun_champ_interdit,
)

pytestmark = pytest.mark.usefixtures("base_disponible")


def codes(sortie):
    return {a.code for a in sortie.avertissements}


# ---------- chercher_lots ----------

def test_chercher_nominal_tri_et_calcul():
    r = chercher_lots(ChercherLotsEntree(gouvernorat="Monastir", surface_min_m2=3000, limite=5))
    lots = r.donnees.lots
    assert lots and all(l.statut is StatutLot.disponible for l in lots)
    assert all(l.gouvernorat == "Monastir" and l.surface_m2 >= 3000 for l in lots)
    for l in lots:
        if l.prix_total_indicatif_dt is not None:
            assert l.prix_total_indicatif_dt == l.surface_m2 * l.prix_indicatif_dt_m2
    totaux = [l.prix_total_indicatif_dt for l in lots if l.prix_total_indicatif_dt is not None]
    assert totaux == sorted(totaux)
    assert C.prix_indicatif in codes(r) and C.donnee_non_fraiche in codes(r)
    assert {b.type for b in r.balises} == {"LOT", "ZONE"}
    assert_aucun_champ_interdit(r)


def test_chercher_budget():
    r = chercher_lots(ChercherLotsEntree(gouvernorat="Monastir", budget_max_dt=200_000, limite=50))
    assert r.donnees.lots
    assert all(l.prix_total_indicatif_dt is not None and l.prix_total_indicatif_dt <= 200_000
               for l in r.donnees.lots)


def test_chercher_aucun_resultat():
    r = chercher_lots(ChercherLotsEntree(gouvernorat="Tozeur", surface_min_m2=10_000_000))
    assert r.donnees.lots == [] and r.donnees.total_correspondants == 0
    assert C.aucun_resultat in codes(r)


def test_chercher_gouvernorat_inconnu():
    r = chercher_lots(ChercherLotsEntree(gouvernorat="Paris"))
    assert r.donnees.lots == [] and C.gouvernorat_non_reconnu in codes(r)


def test_chercher_zone_par_nom():
    r = chercher_lots(ChercherLotsEntree(zone_nom="ras el morj", limite=50))
    assert r.donnees.lots and {l.zone_id for l in r.donnees.lots} == {932119}


def test_chercher_activite_signalee_non_filtree():
    r = chercher_lots(ChercherLotsEntree(gouvernorat="Sfax", activite="textile"))
    assert C.activite_non_filtree in codes(r)


def test_chercher_resultats_tronques():
    r = chercher_lots(ChercherLotsEntree(limite=1))
    assert len(r.donnees.lots) == 1 and r.donnees.total_correspondants > 1
    assert C.resultats_tronques in codes(r)


def test_chercher_statut_gris_sur_demande():
    r = chercher_lots(ChercherLotsEntree(statuts=[StatutLot.inconnu], limite=50))
    assert r.donnees.lots and all(l.statut is StatutLot.inconnu for l in r.donnees.lots)
    assert r.donnees.total_correspondants == 501      # LOT_ETAPE = 5 dans le dump


def test_chercher_ne_renvoie_jamais_de_vendu_par_defaut():
    r = chercher_lots(ChercherLotsEntree(limite=50))
    assert all(l.statut is StatutLot.disponible for l in r.donnees.lots)


def test_chercher_pres_de_tri_par_distance():
    r = chercher_lots(ChercherLotsEntree(pres_de=TypeCommodite.port, tri="distance_equipement", limite=50))
    d = [l.distance_equipement_km for l in r.donnees.lots]
    assert d and None not in d and d == sorted(d)
    assert r.donnees.tri.value == "distance_equipement"


def test_chercher_pres_de_rayon_respecte():
    r = chercher_lots(ChercherLotsEntree(pres_de=TypeCommodite.aeroport, distance_max_km=10, limite=50))
    assert all(l.distance_equipement_km <= 10 for l in r.donnees.lots)


def test_chercher_pres_de_rayon_vide():
    r = chercher_lots(ChercherLotsEntree(pres_de=TypeCommodite.port, distance_max_km=0.0001, gouvernorat="Kasserine"))
    assert r.donnees.lots == [] and C.aucun_resultat in codes(r)


def test_chercher_pres_de_exige_un_type_de_distance():
    with pytest.raises(ValueError):
        ChercherLotsEntree(pres_de=TypeCommodite.electricite)
    with pytest.raises(ValueError):
        ChercherLotsEntree(distance_max_km=10)
    with pytest.raises(ValueError):           # « près d'un port » sans rayon ni tri par distance
        ChercherLotsEntree(pres_de=TypeCommodite.port)


# ---------- details_lot ----------

def test_details_nominal():
    r = details_lot(DetailsLotEntree(lot_id=LOT_RAS_EL_MORJ_37))
    d = r.donnees
    assert d.lot.numero == "37" and d.lot.surface_m2 == 3122 and d.lot.statut is StatutLot.disponible
    assert d.zone.zone_id == 932119 and d.zone.gouvernorat == "Monastir"
    port = [c for c in d.commodites_zone if c.type is TypeCommodite.port]
    assert port and port[0].distance_km == 35.0
    assert d.services_proximite and d.a_un_polygone
    assert C.prix_ecart_site_public in d.lot.avertissements
    assert_aucun_champ_interdit(r)


def test_details_lot_orphelin():
    r = details_lot(DetailsLotEntree(lot_id=LOT_ORPHELIN))
    lot = r.donnees.lot
    assert lot.zone_id is None and lot.zone_nom is None and lot.prix_indicatif_dt_m2 is None
    assert C.lot_orphelin in lot.avertissements and r.donnees.zone is None


def test_details_statut_gris():
    lot = details_lot(DetailsLotEntree(lot_id=LOT_GRIS)).donnees.lot
    assert lot.statut is StatutLot.inconnu and C.statut_inconnu in lot.avertissements


def test_details_surface_negative():
    lot = details_lot(DetailsLotEntree(lot_id=LOT_SURFACE_NEGATIVE)).donnees.lot
    assert lot.surface_m2 is None and lot.prix_total_indicatif_dt is None
    assert C.surface_invalide in lot.avertissements


def test_details_prix_aberrant_non_communique():
    lot = details_lot(DetailsLotEntree(lot_id=LOT_PRIX_ABERRANT)).donnees.lot
    assert lot.prix_indicatif_dt_m2 is None and lot.prix_total_indicatif_dt is None
    assert C.prix_suspect in lot.avertissements


def test_details_coordonnees_manquantes():
    r = details_lot(DetailsLotEntree(lot_id=LOT_COORD_INVALIDES))
    assert r.donnees.zone.coordonnees is None and C.coordonnees_manquantes in codes(r)


def test_details_lot_introuvable():
    r = details_lot(DetailsLotEntree(lot_id=99_999_999))
    assert r.donnees.lot is None and C.lot_introuvable in codes(r)


def test_details_documents_sans_lien():
    r = details_lot(DetailsLotEntree(lot_id=LOT_RAS_EL_MORJ_37))
    assert r.donnees.documents_zone and all(d.url is None for d in r.donnees.documents_zone)
    assert C.document_sans_lien in codes(r)
    assert not [b for b in r.balises if b.type == "PDF"]


# ---------- comparer_lots ----------

def test_comparer():
    r = comparer_lots(ComparerLotsEntree(lot_ids=[LOT_RAS_EL_MORJ_37, LOT_ENCHERES_ARIANA, 99_999_999]))
    d = r.donnees
    assert [l.lot.lot_id for l in d.lignes] == [LOT_RAS_EL_MORJ_37, LOT_ENCHERES_ARIANA]
    # 3122 × 70 = 218 540 ; 34 735 × 100 = 3 473 500
    assert d.prix_total_le_plus_bas == [LOT_RAS_EL_MORJ_37]
    assert d.surface_la_plus_grande == [LOT_ENCHERES_ARIANA]
    # Aéroport : Ras El Morj 45 km (Monastir), Ariana Aéroport 3,5 km (Tunis Carthage)
    assert d.plus_proche[TypeCommodite.aeroport] == [LOT_ENCHERES_ARIANA]
    assert d.lignes[1].distances_km[TypeCommodite.aeroport] == 3.5
    assert C.lot_introuvable in codes(r)
    assert_aucun_champ_interdit(r)


def test_comparer_avec_orphelin():
    r = comparer_lots(ComparerLotsEntree(lot_ids=[LOT_ORPHELIN, LOT_RAS_EL_MORJ_37]))
    orphelin = r.donnees.lignes[0]
    assert all(v is None for v in orphelin.distances_km.values())
    assert r.donnees.prix_total_le_plus_bas == [LOT_RAS_EL_MORJ_37]


# ---------- lots_proches ----------

def test_proches_par_port_trie():
    r = lots_proches(LotsProchesEntree(type=TypeCommodite.port, limite=50))
    zones = r.donnees.zones
    assert zones and all(z.mode_distance == "equipement_selon_donnees" for z in zones)
    assert [z.distance_km for z in zones] == sorted(z.distance_km for z in zones)
    assert all(z.nb_lots_disponibles > 0 for z in zones)


def test_proches_autour_d_une_zone():
    r = lots_proches(LotsProchesEntree(zone_id=932119, distance_max_km=60, limite=50))
    zones = r.donnees.zones
    assert zones[0].zone.zone_id == 932119 and zones[0].distance_km == 0
    assert all(z.distance_km <= 60 for z in zones)


def test_proches_zones_sans_coordonnees_ecartees_et_signalees():
    # 38 zones ont des coordonnées vides ou invalides ; aucune n'a de lot disponible,
    # d'où le filtre désactivé pour les voir.
    r = lots_proches(LotsProchesEntree(zone_id=932119, uniquement_avec_lots_disponibles=False, limite=50))
    assert any(a.code is C.coordonnees_manquantes and a.detail == "38 zones écartées" for a in r.avertissements)
    assert all(z.zone.coordonnees is not None for z in r.donnees.zones)


def test_proches_lot_orphelin():
    r = lots_proches(LotsProchesEntree(lot_id=LOT_ORPHELIN))
    assert r.donnees.zones == [] and C.lot_orphelin in codes(r)


def test_proches_reference_sans_coordonnees():
    r = lots_proches(LotsProchesEntree(lot_id=LOT_COORD_INVALIDES))
    assert r.donnees.zones == [] and C.coordonnees_manquantes in codes(r)


def test_proches_type_non_distance_refuse():
    with pytest.raises(ValueError):
        LotsProchesEntree(type=TypeCommodite.electricite)


# ---------- Performance (objectif < 1 s par outil, caches chauds) ----------

def test_performance():
    lots_proches(LotsProchesEntree(type=TypeCommodite.port))  # chauffe les caches
    appels = [
        lambda: chercher_lots(ChercherLotsEntree(surface_min_m2=1000, budget_max_dt=500_000)),
        lambda: details_lot(DetailsLotEntree(lot_id=LOT_RAS_EL_MORJ_37)),
        lambda: comparer_lots(ComparerLotsEntree(lot_ids=[LOT_RAS_EL_MORJ_37, LOT_ENCHERES_ARIANA])),
        lambda: lots_proches(LotsProchesEntree(type=TypeCommodite.gare)),
    ]
    for f in appels:
        t = time.perf_counter()
        f()
        assert time.perf_counter() - t < 1.0
