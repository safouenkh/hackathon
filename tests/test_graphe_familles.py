"""Les 9 familles de concepts du cahier (§IV.5) : présentes, construites depuis la base, une requête SPARQL de test chacune."""
import pytest
from rdflib import Literal
from rdflib.namespace import RDF

from app.semantique import graphe_familles
from app.semantique.graphe_familles import REQUETES_FAMILLES, graphe_complet, uri_lot
from app.semantique.ontologie import AFI
from tests.conftest import LOT_ORPHELIN, LOT_RAS_EL_MORJ_37

pytestmark = pytest.mark.usefixtures("base_disponible")

FAMILLES_DU_CAHIER = ["Lieu", "Lot", "Secteur d'activité", "Commodité et proximité", "Démarche", "Incitation",
                      "Organisme", "Projet", "Service de l'AFI"]


def test_chaque_famille_repond_a_sa_requete_sparql():
    assert list(REQUETES_FAMILLES) == FAMILLES_DU_CAHIER
    resultats = graphe_familles.tester_familles()
    assert all(n > 0 for n in resultats.values()), resultats


def test_24_gouvernorats_et_185_zones_rattachees():
    g = graphe_complet()
    lignes = list(g.query(REQUETES_FAMILLES["Lieu"]))
    assert len(lignes) == 24 and sum(int(r.zones) for r in lignes) == 185


def test_lot_relie_a_sa_zone_et_orphelin_sans_zone():
    g = graphe_complet()
    assert (uri_lot(LOT_RAS_EL_MORJ_37), AFI.dansZone, None) in g
    assert (uri_lot(LOT_ORPHELIN), AFI.dansZone, None) not in g
    assert (uri_lot(LOT_ORPHELIN), AFI.lotOrphelin, Literal(True)) in g
    assert len(set(g.subjects(RDF.type, AFI.Lot))) == 6579


def test_un_lot_ne_porte_que_son_identifiant_et_sa_zone():
    # ni prix, ni statut, ni surface, ni champ interdit : ils restent en SQL (cahier §IV.5)
    g = graphe_complet()
    lots = set(g.subjects(RDF.type, AFI.Lot))
    predicats = {p for s, p, _ in g.triples((None, None, None)) if s in lots}
    assert predicats == {RDF.type, AFI.identifiantLot, AFI.dansZone, AFI.lotOrphelin}


def test_organismes_du_cahier_presents_avec_leur_source():
    g = graphe_complet()
    codes = {str(c) for c in g.objects(None, AFI.codeOrganisation)}
    assert {"APIA", "APII", "TIA", "FIPA", "INS"} <= codes


def test_incitations_reliees_a_leur_organisme():
    g = graphe_complet()
    lignes = {(str(r.incitation), str(r.organisme)) for r in g.query(REQUETES_FAMILLES["Incitation"])}
    assert ("Subvention financière", "Agence de Promotion des Investissements Agricoles") in lignes
    assert ("Franchise douanière", "Agence de Promotion de l'Industrie et de l'Innovation") in lignes
    assert not any("Pêche et aquaculture" == i for i, _ in lignes)       # titre sans mot d'aide


def test_regle_sourcee_apia_agriculture():
    g = graphe_complet()
    lignes = {(str(r.code), str(r.organisme)) for r in g.query(REQUETES_FAMILLES["Secteur d'activité"])}
    assert ("agriculture", "APIA") in lignes


def test_projet_est_un_schema_sans_instance():
    g = graphe_complet()
    assert not list(g.subjects(RDF.type, AFI.Projet))
    proprietes = {str(r.propriete).split("#")[1] for r in g.query(REQUETES_FAMILLES["Projet"])}
    assert {"natureProjet", "nombreEmplois", "investissementDt", "surfaceSouhaiteeM2", "localiseDans"} == proprietes
