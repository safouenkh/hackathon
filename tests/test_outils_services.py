"""Outils services AFI (BF22, BF23, BF24, BF11) et guidage pas à pas, sur la base `dalila`.

Les services et parcours sont lus dans le schéma `assistant` (versions publiées). Les valeurs
attendues viennent des fiches sources (afi-services-markdown) et de la page « Nos services »
lue le 2026-11-27, pas du code.
"""
from pathlib import Path

import pytest

from app.processing.avantages import avantages, brancher_source, SourceIncitationsIndisponible
from app.processing.demande import preparer_demande
from app.processing.schemas import (
    AvantagesEntree, CodeAvertissement as C, DemarcheEntree, GuiderServiceEntree, Incitation,
    PreparerDemandeEntree, Projet, ServicesAfiEntree, StatutLot,
)
from app.processing.services import demarche, guider_service, services_afi
from tests.conftest import LOT_ENCHERES_ARIANA, LOT_ORPHELIN, LOT_RAS_EL_MORJ_37

pytestmark = pytest.mark.usefixtures("base_disponible")

CORPUS = Path(__file__).resolve().parents[1] / "afi-services-markdown" / "data" / "documents" / "services"
URL_NOS_SERVICES = "https://www.afi.nat.tn/fr/nos-services/"
SERVICES = ["acquisition", "encheres", "situation_fonciere", "insertion_hypotheque", "mainlevee",
            "acte_precision", "autorisation_vente_leasing", "copie_conforme"]     # cahier §IV.6


def codes(sortie):
    return {a.code for a in sortie.avertissements}


def tous(elements):
    for e in elements:
        yield e
        yield from tous(e.enfants)


def lignes(p):
    return [e for liste in (p.description, p.pour_qui, p.conditions, p.etapes, p.pieces, p.frais, p.liens,
                            p.remarques) for e in tous(liste)]


# ---------- services_afi ----------

def test_les_8_services_viennent_de_la_base():
    r = services_afi(ServicesAfiEntree())
    assert [s.id for s in r.donnees.services] == SERVICES
    assert len([b for b in r.balises if b.type == "CHOIX"]) == 8
    assert r.donnees.services[3].fiches == [19]                       # lien de l'ontologie


@pytest.mark.parametrize("besoin, attendu", [
    ("La banque me demande un papier pour mon prêt", "insertion_hypotheque"),
    ("I need a document for my bank loan", "insertion_hypotheque"),
    ("البنك طلب مني وثيقة للقرض", "insertion_hypotheque"),
    ("n7eb nechri terrain f Sfax", "acquisition"),
    ("je veux participer à une enchère", "encheres"),
    ("il me faut une copie conforme de mon contrat", "copie_conforme"),
    ("ma société de leasing veut vendre le lot", "autorisation_vente_leasing"),
    ("comment obtenir la mainlevée", "mainlevee"),
    # Essai en conditions réelles du 27/11/2026 : arabizi tunisien et fautes de frappe
    ("nheb na3mel raf3 yed 3la lot mta3i, chnouwa lazemni?", "mainlevee"),
    ("7adhrelli talab mta3 raf3 yed lel lot 7079", "mainlevee"),
    ("rafg yed", "mainlevee"),                                           # faute de frappe du LLM
    ("el banka t7eb wara9a bech t3tini el 9ardh", "insertion_hypotheque"),
    ("wa9tech el mazad el jeya", "encheres"),
    ("kteb tawdhihi", "acte_precision"),
    ("ijar maleya", "autorisation_vente_leasing"),
])
def test_orientation_bf22(besoin, attendu):
    r = services_afi(ServicesAfiEntree(besoin=besoin))
    assert r.donnees.candidats and r.donnees.candidats[0].service.id == attendu


@pytest.mark.parametrize("besoin", ["nheb nabni dar fi tounes", "nechra", "mon voisin fait du bruit"])
def test_mot_proche_mais_different_n_est_pas_reconnu(besoin):
    """La tolérance aux fautes ne s'applique qu'aux mots-clés d'au moins 7 caractères."""
    assert services_afi(ServicesAfiEntree(besoin=besoin)).donnees.candidats == []


def test_besoin_non_reconnu_donne_les_choix_et_le_contact():
    r = services_afi(ServicesAfiEntree(besoin="mon voisin fait du bruit"))
    assert r.donnees.candidats == [] and C.besoin_non_reconnu in codes(r)
    assert len(r.balises) == 8
    assert r.donnees.contact_afi.telephone == "+216 71 124 260"          # fiche 26


# ---------- demarche ----------

@pytest.mark.parametrize("service", SERVICES)
def test_chaque_service_a_un_parcours_publie_et_source(service):
    r = demarche(DemarcheEntree(service=service))
    assert r.donnees.service.id == service and r.donnees.parcours
    for p in r.donnees.parcours:
        assert p.url_source == URL_NOS_SERVICES and p.version >= 1
        assert p.conditions or p.etapes or p.pieces
    assert any(x.type == "url" and x.url == URL_NOS_SERVICES for x in r.provenance)


@pytest.mark.skipif(not CORPUS.is_dir(), reason="corpus afi-services-markdown absent")
@pytest.mark.parametrize("service", SERVICES)
def test_rien_n_est_reecrit(service):
    """Chaque ligne non corrigée figure telle quelle dans la fiche source ; chaque correction a sa note."""
    for p in demarche(DemarcheEntree(service=service)).donnees.parcours:
        source = (CORPUS / p.code / "fr.md").read_text(encoding="utf-8")
        for e in lignes(p):
            if e.corrige:
                assert e.a_verifier and "Preuve : https://www.afi.nat.tn/" in e.note_verification
            else:
                assert e.texte in source, e.texte


@pytest.mark.parametrize("service, montants", [            # page « Nos services », 2026-11-27
    ("situation_fonciere", [(50.0, None)]),
    ("insertion_hypotheque", [(50.0, None)]),
    ("mainlevee", [(50.0, None)]),
    ("acte_precision", [(150.0, None)]),
    ("copie_conforme", [(15.0, "par copie")]),
    ("autorisation_vente_leasing", []),
    ("encheres", []),                                     # seulement des pourcentages
])
def test_frais_exacts_de_la_source(service, montants):
    r = demarche(DemarcheEntree(service=service))
    assert [(f.montant_dt, f.unite_montant) for p in r.donnees.parcours for f in p.frais] == montants


def test_acquisition_deux_parcours_a_choisir():
    r = demarche(DemarcheEntree(service="acquisition"))
    assert [p.code for p in r.donnees.parcours] == ["acquisition-developpement-regional",
                                                    "acquisition-littoral-grand-tunis"]
    assert C.parcours_a_choisir in codes(r)
    assert {b.texte for b in r.balises if b.type == "CHOIX"} == {
        "[[CHOIX:zones de développement régional]]", "[[CHOIX:zones littorales et le grand Tunis]]"}
    assert {f for p in r.donnees.parcours for f in (x.fiche for x in r.donnees.fiches_afi)} == {13, 14, 15, 16, 17}


def test_acquisition_lieu_de_depot_et_frais_non_chiffres():
    r = demarche(DemarcheEntree(service="acquisition", parcours="acquisition-developpement-regional"))
    (p,) = r.donnees.parcours
    assert C.parcours_a_choisir not in codes(r)
    assert any("bureau d’ordre central" in l for l in p.lieu_depot)
    assert any("déposée au gouvernorat" in l for l in p.lieu_depot)
    assert C.lieu_depot_non_precise not in codes(r)
    assert set(p.frais_sans_montant) >= {"Prix du lot industriel.", "Frais de rédaction du contrat de vente."}
    assert C.frais_non_chiffres in codes(r)
    assert [f.code for f in p.formulaires] == ["demande_acquisition"]
    assert {b.id for b in r.balises if b.type == "PDF"} == {
        "https://www.afi.nat.tn/wp-content/uploads/2024/04/DEMANDE-dacquisition-FR.pdf",
        "https://www.afi.nat.tn/wp-content/uploads/2024/05/%D9%85%D8%B7%D9%84%D8%A8-%D8%A5%D9%82%D8%AA%D9%86%D8%A7%D8%A1-%D8%A8%D8%A7%D9%84%D8%B9%D8%B1%D8%A8%D9%8A%D8%A9.pdf"}


def test_situation_fonciere_lieu_non_precise_et_formulaire_administratif():
    r = demarche(DemarcheEntree(service="situation_fonciere"))
    (p,) = r.donnees.parcours
    assert p.lieu_depot == [] and C.lieu_depot_non_precise in codes(r)
    (f,) = p.formulaires
    assert f.code == "demande_service_administratif" and f.valeurs_imposees == {"document_demande": "1"}
    assert f.a_verifier and C.point_a_verifier in codes(r)


def test_mainlevee_corrigee_d_apres_la_page_arabe():
    (p,) = demarche(DemarcheEntree(service="mainlevee")).donnees.parcours
    assert not [e for e in p.etapes if "livres explicatifs" in e.texte]
    assert len(p.pieces) == 10 and p.pieces[-1].texte.startswith("Reçu de paiement des frais du certificat")
    assert sum(e.corrige for e in lignes(p)) == 5
    assert any("GMG" in l for l in p.frais_sans_montant)


def test_acte_de_precision_etapes_d_achat_signalees_et_fiche_20():
    r = demarche(DemarcheEntree(service="acte_precision"))
    (p,) = r.donnees.parcours
    assert [e.a_verifier for e in p.etapes] == [True, True, True, True, False]
    assert p.lieu_depot == []                    # la seule mention (étape 1) est à vérifier : écartée
    assert [f.fiche for f in r.donnees.fiches_afi] == [20]


def test_service_hors_liste_bf24():
    r = demarche(DemarcheEntree(service="permis de construire"))
    assert r.donnees.service is None and r.donnees.parcours == []
    assert C.service_non_couvert in codes(r) and len(r.balises) == 8
    c = r.donnees.contact_afi
    assert c.telephone == "+216 71 124 260" and c.site == "www.afi.nat.tn"
    assert c.adresse == "9 et 13 rue Chott Mariem, Montplaisir, 1002 Tunis Belvédère"


def test_parcours_inconnu():
    r = demarche(DemarcheEntree(service="mainlevee", parcours="n-existe-pas"))
    assert r.donnees.parcours == [] and C.parcours_inconnu in codes(r)


# ---------- guider_service ----------

def _guide_complet(parcours):
    points, position = [], 0
    while position is not None:
        r = guider_service(GuiderServiceEntree(parcours=parcours, position=position))
        points.append(r)
        position = r.donnees.suivant
    return points


def test_guide_mainlevee_point_par_point():
    pts = _guide_complet("main-levee")
    d0 = pts[0].donnees
    assert d0.total == len(pts) and d0.precedent is None and d0.url_source == URL_NOS_SERVICES
    assert sum(e.nombre for e in d0.plan) == d0.total
    assert [e.rubrique for e in d0.plan] == ["piece", "formulaire", "etape", "frais", "lieu_depot"]
    # chaque ligne racine de la fiche est montrée une fois, sauf les liens (repris par le formulaire)
    (p,) = demarche(DemarcheEntree(service="mainlevee")).donnees.parcours
    attendus = [e.id for e in p.pieces + p.etapes + p.frais]
    vus = [r.donnees.point.element.id for r in pts if r.donnees.point.element]
    assert sorted(vus) == sorted(attendus)
    dernier = pts[-1]
    assert dernier.donnees.point.rubrique == "lieu_depot" and dernier.donnees.point.lieu_depot == []
    assert dernier.donnees.point.contact_afi.telephone == "+216 71 124 260"
    assert C.lieu_depot_non_precise in codes(dernier)
    formulaire = next(r for r in pts if r.donnees.point.rubrique == "formulaire")
    assert formulaire.donnees.point.formulaire.valeurs_imposees == {"document_demande": "3"}
    assert [b.type for b in formulaire.balises] == ["PDF"]
    recu = next(r for r in pts if r.donnees.point.element and r.donnees.point.element.texte.startswith("Reçu"))
    assert C.point_a_verifier in codes(recu)


def test_guide_acte_de_precision_commence_par_la_fiche_20():
    r = guider_service(GuiderServiceEntree(parcours="acte-precision-contrats-finaux"))
    assert r.donnees.point.rubrique == "presentation"
    assert [f.fiche for f in r.donnees.point.fiches_afi] == [20]
    assert r.donnees.suivant == 1


def test_guide_acquisition_lieu_de_depot_donne():
    dernier = _guide_complet("acquisition-littoral-grand-tunis")[-1]
    assert dernier.donnees.point.lieu_depot and dernier.donnees.point.contact_afi is None
    assert C.lieu_depot_non_precise not in codes(dernier)


def test_guide_hors_limites_et_parcours_inconnu():
    r = guider_service(GuiderServiceEntree(parcours="copie-conforme", position=400))
    assert r.donnees.point is None and C.position_hors_parcours in codes(r)
    assert r.donnees.precedent == r.donnees.total - 1
    r = guider_service(GuiderServiceEntree(parcours="inconnu"))
    assert r.donnees.point is None and C.parcours_inconnu in codes(r) and r.donnees.total == 0


# ---------- avantages ----------

class _SourceTest:
    """Fausse source d'extraits : note les organismes demandés, renvoie une incitation avec et une sans source."""
    def __init__(self):
        self.organisations = "non appelé"

    def rechercher(self, question, organisations, limite=5):
        self.organisations = organisations
        return [Incitation(intitule="A", extrait="x", organisme="APIA", url="https://example.org/a",
                           document=None, page=None, date_source=None),
                Incitation(intitule="B", extrait="y", organisme=None, url=None, document=None,
                           page=None, date_source=None)]


@pytest.fixture
def source_test():
    s = _SourceTest()
    brancher_source(s)
    yield s
    from app.processing.avantages import SourcePassagesOrganismes
    brancher_source(SourcePassagesOrganismes())


def _orgs(r):
    return sorted({o.organisation for o in r.donnees.orientation})


def test_avantages_agricole_vers_apia_avec_citation(source_test):
    # Règles sourcées (migration 0004) : APIA pour le secteur agricole ; TIA dépend du montant ; FIPA de la nationalité
    r = avantages(AvantagesEntree(activite="nheb na3mel projet fla7a", question="idées de projet et primes"))
    assert r.donnees.secteurs == ["agriculture"] and _orgs(r) == ["APIA"]
    apia = r.donnees.orientation[0]
    assert "secteur agricole" in apia.citation and apia.url.startswith("https://tia.gov.tn/")
    assert {C.montant_a_preciser, C.nationalite_a_preciser} <= codes(r)
    assert source_test.organisations == ["APIA"]
    assert [i.intitule for i in r.donnees.incitations] == ["A"]          # l'incitation sans source est écartée
    assert r.donnees.zone_developpement_regional is None


@pytest.mark.parametrize("montant,attendu", [(20_000_000, ["TIA"]), (2_000_000, ["APII"]), (15_000_000, ["TIA"])])
def test_avantages_seuil_de_15_mdt(source_test, montant, attendu):
    r = avantages(AvantagesEntree(activite="usine textile", investissement_dt=montant, investisseur_etranger=False))
    assert _orgs(r) == attendu and C.montant_a_preciser not in codes(r)


def test_avantages_agricole_au_dessus_du_seuil_plusieurs_organismes(source_test):
    r = avantages(AvantagesEntree(secteur="agriculture", investissement_dt=20_000_000, investisseur_etranger=False))
    assert _orgs(r) == ["APIA", "TIA"] and C.plusieurs_organismes in codes(r)


def test_avantages_investisseur_etranger_premier_contact_fipa(source_test):
    r = avantages(AvantagesEntree(activite="factory", investissement_dt=1_000_000, investisseur_etranger=True))
    assert _orgs(r) == ["APII", "FIPA"] and C.plusieurs_organismes not in codes(r)
    assert {o.role for o in r.donnees.orientation if o.organisation == "FIPA"} == {"premier_contact"}


def test_avantages_secteur_inconnu_rien_suppose(source_test):
    r = avantages(AvantagesEntree(activite="xyz"))
    assert r.donnees.secteurs == [] and C.secteur_a_preciser in codes(r)
    assert "APII" not in _orgs(r)                    # « autres secteurs » : jamais supposé sans secteur


def test_avantages_index_indisponible_aucune_incitation_inventee():
    class Panne:
        def rechercher(self, *a, **k):
            raise ConnectionError("qdrant arrêté")
    brancher_source(Panne())
    try:
        r = avantages(AvantagesEntree(secteur="peche"))
        assert r.donnees.incitations == [] and C.source_indisponible in codes(r)
        assert _orgs(r) == ["APIA"]                    # l'orientation sourcée reste donnée
    finally:
        from app.processing.avantages import SourcePassagesOrganismes
        brancher_source(SourcePassagesOrganismes())


# ---------- preparer_demande ----------

def test_preparer_demande_nominal():
    r = preparer_demande(PreparerDemandeEntree(
        service="acquisition", parcours="acquisition-littoral-grand-tunis", lot_ids=[LOT_RAS_EL_MORJ_37],
        projet=Projet(activite="textile", nombre_emplois=40, gouvernorat="monastir")))
    d = r.donnees
    assert d.depot_effectue is False and d.confirmation_requise is True
    assert C.confirmation_requise in codes(r)
    assert d.surface_totale_m2 == 3122 and d.prix_total_indicatif_dt == 3122 * 70
    assert d.projet.gouvernorat == "Monastir"
    assert set(d.informations_projet_manquantes) == {"investissement_dt", "surface_souhaitee_m2"}
    assert d.parcours == ["acquisition-littoral-grand-tunis"]
    assert d.pieces_a_preparer and d.lieu_depot and [f.code for f in d.formulaires] == ["demande_acquisition"]
    assert {l.url for l in d.liens} == {URL_NOS_SERVICES, "https://afi.e-industrie.gov.tn/"}


def test_preparer_demande_lot_aux_encheres_et_orphelin():
    r = preparer_demande(PreparerDemandeEntree(service="acquisition",
                                               lot_ids=[LOT_ENCHERES_ARIANA, LOT_ORPHELIN, 99_999_999]))
    d = r.donnees
    assert [l.statut for l in d.lots][0] is StatutLot.aux_encheres
    assert any(a.code is C.lot_non_disponible and a.lot_id == LOT_ENCHERES_ARIANA for a in r.avertissements)
    assert any(a.code is C.lot_introuvable and a.lot_id == 99_999_999 for a in r.avertissements)
    assert "[[CHOIX:Vente aux enchères]]" in {b.texte for b in r.balises}
    assert d.prix_total_indicatif_dt is None          # lot orphelin : prix inconnu, donc pas de total


def test_preparer_demande_refuse_les_donnees_personnelles():
    with pytest.raises(ValueError):
        PreparerDemandeEntree.model_validate({"service": "acquisition", "projet": {"nom": "X", "cin": "01234567"}})
