import pytest

from app.processing.avantages import avantages, brancher_source, SourceIncitationsIndisponible
from app.processing.demande import preparer_demande
from app.processing.schemas import (
    AvantagesEntree, CodeAvertissement as C, DemarcheEntree, Incitation, PreparerDemandeEntree, Projet,
    ServiceAfiId, ServicesAfiEntree, StatutLot, VarianteAcquisition,
)
from app.processing.services import SERVICES, analyser_fiche, demarche, services_afi
from tests.conftest import LOT_ENCHERES_ARIANA, LOT_ORPHELIN, LOT_RAS_EL_MORJ_37

pytestmark = pytest.mark.usefixtures("base_disponible")


def codes(sortie):
    return {a.code for a in sortie.avertissements}


# ---------- services_afi ----------

def test_les_8_services():
    r = services_afi(ServicesAfiEntree())
    assert len(r.donnees.services) == 8 == len(SERVICES)
    assert len([b for b in r.balises if b.type == "CHOIX"]) == 8


@pytest.mark.parametrize("besoin, attendu", [
    ("La banque me demande un papier pour mon prêt", ServiceAfiId.insertion_hypotheque),
    ("I need a document for my bank loan", ServiceAfiId.insertion_hypotheque),
    ("البنك طلب مني وثيقة للقرض", ServiceAfiId.insertion_hypotheque),
    ("n7eb nechri terrain f Sfax", ServiceAfiId.acquisition),
    ("je veux participer à une enchère", ServiceAfiId.encheres),
    ("il me faut une copie conforme de mon contrat", ServiceAfiId.copie_conforme),
    ("ma société de leasing veut vendre le lot", ServiceAfiId.autorisation_vente_leasing),
    ("comment obtenir la mainlevée", ServiceAfiId.mainlevee),
])
def test_orientation_bf22(besoin, attendu):
    r = services_afi(ServicesAfiEntree(besoin=besoin))
    assert r.donnees.candidats and r.donnees.candidats[0].service.id is attendu


def test_besoin_non_reconnu_donne_les_choix_et_le_contact():
    r = services_afi(ServicesAfiEntree(besoin="mon voisin fait du bruit"))
    assert r.donnees.candidats == [] and C.besoin_non_reconnu in codes(r)
    assert len(r.balises) == 8
    assert r.donnees.contact_afi.telephone == "+216 71 124 260"


# ---------- demarche ----------

FRAIS_SOURCES = {                        # montants lus dans les fiches 18 à 23
    ServiceAfiId.situation_fonciere: 50,
    ServiceAfiId.insertion_hypotheque: 50,
    ServiceAfiId.mainlevee: 50,
    ServiceAfiId.acte_precision: 150,
    ServiceAfiId.copie_conforme: 15,
}


@pytest.mark.parametrize("service", list(ServiceAfiId))
def test_chaque_service_a_une_fiche_sourcee(service):
    r = demarche(DemarcheEntree(service=service.value))
    assert r.donnees.service.id is service and r.donnees.fiches
    for f in r.donnees.fiches:
        assert f.url_source == "https://www.afi.nat.tn/fr/nos-services/"
        assert f.pieces or f.etapes or f.conditions
        # Rien n'est réécrit : chaque élément extrait figure dans le texte de la fiche.
        for x in f.conditions + f.etapes + [p for g in f.pieces for p in g.pieces] + f.lieu_depot:
            assert x in f.texte_source.replace("\n", " ") or x in f.texte_source
        for frais in f.frais:
            assert frais.texte_source in f.texte_source


@pytest.mark.parametrize("service, montant", FRAIS_SOURCES.items())
def test_frais_exacts_de_la_source(service, montant):
    r = demarche(DemarcheEntree(service=service.value))
    montants = [x.montant_dt for f in r.donnees.fiches for x in f.frais if x.montant_dt is not None]
    assert montants == [montant]


def test_acquisition_deux_variantes_et_lieu_de_depot():
    r = demarche(DemarcheEntree(service="acquisition"))
    assert {f.variante for f in r.donnees.fiches} == set(VarianteAcquisition)
    assert {b.texte for b in r.balises} == {"[[CHOIX:Zone de développement régional]]",
                                            "[[CHOIX:Zone littorale ou Grand Tunis]]"}
    lieux = [l for f in r.donnees.fiches for l in f.lieu_depot]
    assert any("bureau d'ordre central" in l for l in lieux)
    assert any("gouvernorat compétent" in l for l in lieux)
    assert C.frais_non_chiffres in codes(r)         # frais de rédaction / délimitation sans montant


def test_acquisition_une_variante():
    r = demarche(DemarcheEntree(service="acquisition", variante="littoral_grand_tunis"))
    assert [f.fiche for f in r.donnees.fiches] == [15, 16, 17] and r.balises == []
    etapes = r.donnees.fiches[1].etapes
    assert len(etapes) == 6 and "30 jours" in etapes[2]


def test_lieu_non_precise_signale():
    r = demarche(DemarcheEntree(service="situation_fonciere"))
    assert C.lieu_depot_non_precise in codes(r)
    f = r.donnees.fiches[0]
    assert len(f.etapes) == 6 and len(f.pieces[0].pieces) == 4


def test_service_hors_liste_bf24():
    r = demarche(DemarcheEntree(service="permis de construire"))
    assert r.donnees.service is None and r.donnees.fiches == []
    assert C.service_non_couvert in codes(r)
    c = r.donnees.contact_afi
    assert c.telephone == "+216 71 124 260" and c.site == "www.afi.nat.tn"
    assert c.adresse == "9 et 13 rue Chott Mariem, Montplaisir, 1002 Tunis Belvédère"


def test_analyse_fiche_format_inattendu():
    fiche, cs = analyser_fiche(999, "Q ?", "Texte libre sans section.", None)
    assert C.extraction_partielle in cs and fiche.description == ["Texte libre sans section."]


# ---------- avantages ----------

def test_avantages_stub_ne_rien_inventer():
    r = avantages(AvantagesEntree(activite="textile", gouvernorat="Sfax"))
    assert r.donnees.incitations == []
    assert C.source_indisponible in codes(r) and C.aucun_resultat in codes(r)
    assert r.donnees.zone_developpement_regional is None


def test_avantages_ecarte_une_incitation_sans_source():
    class Fausse:
        def rechercher(self, activite, gouvernorat, zone_id, limite=5):
            return [
                Incitation(intitule="A", extrait="x", organisme="TIA", url="https://example.org/a",
                           document=None, page=None, date_source=None),
                Incitation(intitule="B", extrait="y", organisme=None, url=None, document=None,
                           page=None, date_source=None),
            ]
    brancher_source(Fausse())
    try:
        r = avantages(AvantagesEntree(activite="pêche"))
        assert [i.intitule for i in r.donnees.incitations] == ["A"]
        assert C.source_indisponible not in codes(r)
    finally:
        brancher_source(SourceIncitationsIndisponible())


# ---------- preparer_demande ----------

def test_preparer_demande_nominal():
    r = preparer_demande(PreparerDemandeEntree(
        lot_ids=[LOT_RAS_EL_MORJ_37], variante="littoral_grand_tunis",
        projet=Projet(activite="textile", nombre_emplois=40, gouvernorat="monastir")))
    d = r.donnees
    assert d.depot_effectue is False and d.confirmation_requise is True
    assert C.confirmation_requise in codes(r)
    assert d.surface_totale_m2 == 3122 and d.prix_total_indicatif_dt == 3122 * 70
    assert d.projet.gouvernorat == "Monastir"
    assert set(d.informations_projet_manquantes) == {"investissement_dt", "surface_souhaitee_m2"}
    assert d.pieces_a_preparer and d.lieu_depot
    assert {l.url for l in d.liens} == {"https://www.afi.nat.tn/fr/nos-services/", "https://afi.e-industrie.gov.tn/"}


def test_preparer_demande_lot_aux_encheres_et_orphelin():
    r = preparer_demande(PreparerDemandeEntree(lot_ids=[LOT_ENCHERES_ARIANA, LOT_ORPHELIN, 99_999_999]))
    d = r.donnees
    assert [l.statut for l in d.lots][0] is StatutLot.aux_encheres
    assert any(a.code is C.lot_non_disponible and a.lot_id == LOT_ENCHERES_ARIANA for a in r.avertissements)
    assert any(a.code is C.lot_introuvable and a.lot_id == 99_999_999 for a in r.avertissements)
    assert "[[CHOIX:Vente aux enchères]]" in {b.texte for b in r.balises}
    assert d.prix_total_indicatif_dt is None          # lot orphelin : prix inconnu, donc pas de total


def test_preparer_demande_refuse_les_donnees_personnelles():
    with pytest.raises(ValueError):
        PreparerDemandeEntree.model_validate({"projet": {"nom": "X", "cin": "01234567"}})
