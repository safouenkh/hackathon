"""Démarches administratives hors AFI (fiches SICAD, famille « Démarche » du cahier §IV.5)."""
import pytest

from app.processing import demarches_admin
from app.processing.demarches_admin import SourceFichesIndisponible, SourceFichesSicad, brancher_source, sections
from app.processing.registre import executer
from app.processing.schemas import CodeAvertissement as C
from app.semantique.ontologie import ontologie
from app.sources.sicad import analyser
from tests.conftest import assert_aucun_champ_interdit

# Extrait réel (afi.chatbot_sources id 94, sicad.gov.tn, collecté le 2026-10-23), raccourci.
FICHE_94 = """Attestation constatant l'acceptation des travaux d'assainissement
Conditions d'obtention de la prestation :
L'immeuble doit être situé dans une zone d'intervention de l'office national de l'assainissement
Pièces à fournir :
Plan de récolement du réseau exécuté
Etapes Intervenants Délais
Vérification des plansLe service projets ou l'arrondissement régionalUne semaine
Lieu de dépôt du dossier :
Service :
L'arrondissement régional ou la direction régionale de l'office national de l'assainissement
Lieu d'obtention de la prestation:
Délai d'octroi de la prestation:
4 semaines à partir de la date de réception du dossier complet
Références législatives et / ou réglementaires :
Décret n°2001-1407 du 7 Juin 2001
Ministères & Organismes
Secteurs & Domaines
Ministère des Affaires Locales et de l’Environnement
Adresse
Centre Urbain Nord Boulevard de la Terre -1080 -Tunis
Téléphone
70.728.644 / 70.728.455 / 70.728.674
Site web
http://www.environnement.gov.tn
Office National de l'Assainissement
32, Rue Hédi Nouira 1023 Tunis
http://www.onas.nat.tn
Environnement
Assainissement"""

URL_94 = "http://www.sicad.gov.tn/Fr/Prestations_57_3_D1380"


def test_fiche_prestation_rangee_par_section_sans_reecrire():
    f = analyser(94, URL_94, "Attestation constatant l'acceptation des travaux d'assainissement", FICHE_94)
    assert f.type_fiche == "prestation"
    assert f.sections["pieces"] == ["Plan de récolement du réseau exécuté"]
    # cellules collées par le dump séparées, mots inchangés
    assert f.sections["etapes"] == ["Vérification des plans — Le service projets ou l'arrondissement régional — Une semaine"]
    assert f.sections["lieu_depot"] == ["L'arrondissement régional ou la direction régionale de l'office national de l'assainissement"]
    assert f.sections["delai"] == ["4 semaines à partir de la date de réception du dossier complet"]
    assert f.organismes == ["Ministère des Affaires Locales et de l’Environnement", "Office National de l'Assainissement"]
    assert (f.secteur, f.domaines) == ("Environnement", ["Assainissement"])
    s = sections(f.markdown())                       # aller-retour : ce que l'outil relit en base
    assert s["delai"] == f.sections["delai"] and s["etapes"] == f.sections["etapes"]
    assert "Téléphone : 70.728.644 / 70.728.455 / 70.728.674" in s["contacts"]


def test_organisme_jamais_deduit_d_une_adresse():
    # fiche 29 : la page donne une adresse et un site sans le nom de l'organisme
    t = ("Délivrance d'attestation d'exposant\nMinistères & Organismes\nSecteurs & Domaines\n"
         "Ministère de l'Industrie et du Commerce\nAdresse\n37 Avenue Kheireddine Pacha, 1002 Tunis\nSite web\n"
         "http://www.commerce.gov.tn\nCentre urbain nord 1080 tunis\nhttp://www.cepex.nat.tn\nEn savoir plus\n"
         "Industrie et Commerce\nCommerce extérieur et manifestions internationales")
    f = analyser(30, "http://www.sicad.gov.tn/Fr/Prestations_57_3_D1", "Délivrance d'attestation d'exposant", t)
    assert f.organismes == ["Ministère de l'Industrie et du Commerce"]
    assert f.domaines == ["Commerce extérieur et manifestions internationales"] and f.documents == []


def test_fiche_cahier_des_charges_et_domaines_multiples():
    t = ("Exercice des activités\nMinistères & Organismes\nSecteurs & Domaines\nMinistère X\nAdresse\n"
         "6, rue Al Amine 1002 Tunis\nhttp://www.x.tn\nEnvironnement\n"
         "Protection de l'environnement / Prestations soumises au régime des cahiers des charges\nDocument\n"
         "Exercice des activités de recyclage (AR)")
    f = analyser(1, "http://www.sicad.gov.tn/Fr/Cahiers-des-charges_63_4_D1", "Exercice des activités", t)
    assert f.type_fiche == "cahier_des_charges"
    assert f.domaines == ["Protection de l'environnement", "Prestations soumises au régime des cahiers des charges"]
    assert f.documents == ["Exercice des activités de recyclage (AR)"]


@pytest.mark.parametrize("texte,domaine", [
    ("raccordement au réseau d'assainissement", "Assainissement"),
    ("étude d'impact sur l'environnement", "Protection de l'environnement"),
    ("importer des machines", "Opérations d'importation"),
    ("n7eb nsadder zitoun", "Commerce extérieur et manifestions internationales"),
    ("أريد تصدير زيت الزيتون", "Commerce extérieur et manifestions internationales"),
    ("Stromanschluss Strom für die Fabrik", "Energie"),
])
def test_domaine_reconnu_en_plusieurs_langues(texte, domaine):
    assert domaine in ontologie().domaines_du_texte(texte)


def test_cahier_des_charges_de_zone_n_oriente_pas_vers_sicad():
    # « cahier des charges » désigne aussi le règlement d'une zone (outil regles_zone)
    assert ontologie().domaines_du_texte("le cahier des charges de la zone d'El Fahs") == []


# ---------- outil, avec une source de passages factice ----------

class _Source:
    disponible = True

    def __init__(self, docs):
        self.docs, self.appels = docs, []

    def rechercher(self, question, document_ids, limite):
        self.appels.append(document_ids)
        return [(d, "Pièces à fournir") for d in self.docs if document_ids is None or d in document_ids][:limite]


@pytest.fixture
def source(base_disponible):
    def brancher(docs):
        s = _Source(docs)
        brancher_source(s)
        return s
    yield brancher
    brancher_source(SourceFichesSicad())


def _doc(titre_contient):
    from app.db import get_engine
    from app.repositories import demarches as repo
    with get_engine().connect() as c:
        return next(l["document_id"] for l in repo.demarches(c) if titre_contient in l["titre"])


def test_outil_assainissement_domaine_puis_fiche_exacte(source):
    doc = _doc("acceptation des travaux d'assainissement")
    s = source([doc])
    r = executer("demarches_administratives", {"besoin": "raccordement au réseau d'assainissement",
                                               "activite": "conserverie de sardines"})
    assert r.donnees.domaines_reconnus == ["Assainissement"]
    assert s.appels[0] and doc in s.appels[0]          # recherche limitée aux fiches du domaine (SPARQL)
    f = r.donnees.fiches[0]
    assert f.url == URL_94 and "Office National de l'Assainissement" in f.organismes
    assert f.delai == ["4 semaines à partir de la date de réception du dossier complet"]
    assert f.section_pertinente == "Pièces à fournir"
    codes = [a.code for a in r.avertissements]
    assert C.donnee_non_fraiche in codes and C.pertinence_non_garantie in codes
    assert any(p.url == URL_94 for p in r.provenance) and any(p.table == "afi.chatbot_sources" for p in r.provenance)
    assert_aucun_champ_interdit(r)


def test_outil_fiche_ancien_code_signalee(source):
    source([_doc("fonds de dépollution")])
    r = executer("demarches_administratives", {"besoin": "aide pour la dépollution"})
    assert r.donnees.fiches[0].regime_ancien
    assert C.regime_ancien in [a.code for a in r.avertissements]


def test_outil_aucun_resultat(source):
    source([])
    r = executer("demarches_administratives", {"besoin": "ouvrir une agence de voyage"})
    assert r.donnees.fiches == [] and [a.code for a in r.avertissements] == [C.aucun_resultat]


def test_outil_index_indisponible_rien_d_invente(base_disponible):
    class Panne:
        def rechercher(self, *a):
            raise ConnectionError("qdrant")
    brancher_source(Panne())
    try:
        r = executer("demarches_administratives", {"besoin": "importer des machines"})
    finally:
        brancher_source(SourceFichesSicad())
    assert r.donnees.fiches == []
    assert C.source_indisponible in [a.code for a in r.avertissements]


def test_source_vide_signalee(base_disponible):
    brancher_source(SourceFichesIndisponible())
    try:
        r = demarches_admin.demarches_administratives(
            demarches_admin.DemarchesAdministrativesEntree(besoin="importer des machines"))
    finally:
        brancher_source(SourceFichesSicad())
    assert C.source_indisponible in [a.code for a in r.avertissements]


# ---------- base réelle : import, graphe, avantages ----------

def test_les_127_fiches_sicad_sont_importees(base_disponible):
    from app.db import get_engine
    from app.repositories import demarches as repo
    with get_engine().connect() as c:
        lignes = repo.demarches(c)
    assert len(lignes) == 127
    assert all(l["url"].startswith("http://www.sicad.gov.tn/Fr/") and l["organismes"] and l["domaines"] for l in lignes)
    assert {l["type_fiche"] for l in lignes} == {"prestation", "cahier_des_charges"}


def test_chaque_domaine_des_fiches_est_dans_l_ontologie(base_disponible):
    from app.processing.reference import normaliser
    from app.db import get_engine
    from app.repositories import demarches as repo
    connus = {normaliser(l) for l in ontologie().domaines_demarche}
    with get_engine().connect() as c:
        dans_la_base = {normaliser(d) for l in repo.demarches(c) for d in l["domaines"]}
    assert dans_la_base <= connus, dans_la_base - connus


def test_sparql_fiches_d_un_domaine(base_disponible):
    from app.semantique.graphe_demarches import documents_d_incitation, documents_des_domaines
    assert _doc("acceptation des travaux d'assainissement") in documents_des_domaines(["Assainissement"])
    assert documents_d_incitation(["Commerce extérieur et manifestions internationales"]) == \
        [_doc("fonds de promotion des exportations")]


def test_avantages_ajoute_l_aide_a_l_export_sicad(base_disponible):
    from app.processing.avantages import SourceIncitationsIndisponible, SourcePassagesOrganismes
    from app.processing.avantages import brancher_source as brancher_avantages
    brancher_avantages(SourceIncitationsIndisponible())
    try:
        r = executer("avantages", {"activite": "huile d'olive", "question": "aides pour exporter"})
        sans = executer("avantages", {"activite": "sardine", "question": "primes"})
    finally:
        brancher_avantages(SourcePassagesOrganismes())
    sicad = [i for i in r.donnees.incitations if i.url and "sicad.gov.tn" in i.url]
    assert [i.intitule for i in sicad] == [
        "Octroi de décision pour l'obtention des avantages et indemnités du fonds de promotion des exportations"]
    assert not [i for i in sans.donnees.incitations if i.url and "sicad.gov.tn" in i.url]
