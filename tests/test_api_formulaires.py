"""Pages formulaire et envoi des demandes (API /api).

- Lecture : sur la base `dalila` (lecture seule).
- Refus d'envoi : sur `dalila`, chaque refus a lieu AVANT toute écriture.
- Envoi accepté et besoins (BF24) : sur une base jetable, avec les vrais comptes `dalila_ro` et
  `dalila_rw` (rôles communs au serveur) : la base `dalila` ne reçoit aucune demande de test.
"""
import re
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import URL, create_engine

from app.config import get_settings
from app.db import EcritureIndisponible
from app.main import app
from app.processing import formulaire, lots
from app.processing.schemas import NoterBesoinEntree
from app.sources.formulaires import importer as importer_formulaires
from app.sources.import_services import importer as importer_services
from app.sources.publication import publier
from conftest import LOT_ENCHERES_ARIANA, LOT_RAS_EL_MORJ_37
from scripts import migrer

CORPUS = Path(__file__).resolve().parents[1] / "afi-services-markdown"
client = TestClient(app)
VERSION = formulaire.consentement().version


def _champs(page):
    return {ch["code"]: ch for s in page["sections"] for ch in s["champs"]}


# ---------- Lecture (base dalila) ----------

@pytest.mark.usefixtures("base_disponible")
def test_mainlevee_ligne_3_imposee_et_lot_prerempli():
    r = client.get("/api/formulaires/main-levee", params={"aide": "fr", "lots": [LOT_RAS_EL_MORJ_37]})
    assert r.status_code == 200
    p = r.json()
    assert (p["langue"], p["langues"], p["langue_aide"]) == ("ar", ["ar"], "fr")
    ch = _champs(p)
    assert (ch["document_demande"]["valeur"], ch["document_demande"]["impose"]) == ("3", True)
    assert (ch["numero_lot"]["valeur"], ch["numero_lot"]["origine_valeur"]) == ("37", "lot.numero")
    assert ch["zone_industrielle"]["origine_valeur"] == "lot.zone_nom"
    assert ch["telephone"]["traduction"] == "Téléphone fixe / mobile" and ch["telephone"]["traduction_officielle"] is False
    # Rien n'est jamais prérempli hors « projet » ; la CIN reste une ligne vide à remplir à la main.
    assert all(c["valeur"] is None for c in ch.values() if c["categorie"] != "projet")
    assert ch["cin_numero"]["categorie"] == "non_enregistre"
    mentions = next(s for s in p["sections"] if s["code"] == "document")["mentions"]
    assert [m["si_valeur"] for m in mentions] == [None, "1", "2", "3", "4", "5", "6"]
    assert any(a["code"] == "point_a_verifier" for a in p["avertissements"])
    assert p["avertissements"][0]["code"] == "confirmation_requise"
    assert p["consentement"]["version"] == VERSION and "AFI" in p["consentement"]["texte"]


@pytest.mark.usefixtures("base_disponible")
def test_acquisition_variante_francaise_n_affiche_que_ses_champs():
    fr = _champs(client.get("/api/formulaires/acquisition-developpement-regional", params={"langue": "fr"}).json())
    ar = _champs(client.get("/api/formulaires/acquisition-developpement-regional", params={"langue": "ar"}).json())
    assert len(fr) == 41 and len(ar) == 43
    assert set(ar) - set(fr) == {"code_postal", "declaration_date"}      # seulement sur le formulaire arabe
    assert fr["raison_sociale"]["libelle"] == "Raison Social (société)"   # texte officiel, tel quel


@pytest.mark.usefixtures("base_disponible")
def test_acquisition_preremplie_depuis_le_projet_et_deux_lots():
    p = client.get("/api/formulaires/acquisition-littoral-grand-tunis", params={
        "langue": "fr", "lots": [LOT_RAS_EL_MORJ_37, LOT_ENCHERES_ARIANA], "activite": "Textile",
        "nombre_emplois": 40, "investissement_dt": 1200000, "gouvernorat": "monastir"}).json()
    ch = _champs(p)
    assert ch["superficie_demandee"]["valeur"] == "37857 m²"              # 3 122 + 34 735, calculé par l'outil
    assert ch["activite"]["valeur"] == "Textile" and ch["investissement"]["valeur"] == "1200000"
    # Deux zones différentes : pas de lieu deviné à partir des lots, le gouvernorat du projet est pris.
    assert (ch["lieu_implantation"]["valeur"], ch["lieu_implantation"]["origine_valeur"]) == (
        "Monastir", "projet.gouvernorat")
    codes = [(a["code"], a.get("lot_id")) for a in p["avertissements"]]
    assert ("lot_non_disponible", LOT_ENCHERES_ARIANA) in codes


@pytest.mark.usefixtures("base_disponible")
def test_lots_de_zones_differentes_sans_autre_source():
    p = client.get("/api/formulaires/acquisition-developpement-regional",
                   params={"langue": "fr", "lots": [LOT_RAS_EL_MORJ_37, LOT_ENCHERES_ARIANA]}).json()
    assert _champs(p)["lieu_implantation"]["valeur"] is None
    assert {"code": "valeur_non_preremplie", "detail": "lieu_implantation"}.items() <= next(
        a for a in p["avertissements"] if a["code"] == "valeur_non_preremplie").items()


@pytest.mark.usefixtures("base_disponible")
@pytest.mark.parametrize("url, params, statut, code", [
    ("/api/formulaires/vente-encheres-publiques", {}, 404, "formulaire_indisponible"),
    ("/api/formulaires/main-levee", {"langue": "fr"}, 404, "langue_indisponible"),
    ("/api/formulaires/inconnu", {}, 404, "parcours_inconnu"),
])
def test_formulaire_introuvable(url, params, statut, code):
    r = client.get(url, params=params)
    assert r.status_code == statut and r.json()["detail"]["code"] == code


@pytest.mark.parametrize("params", [{"lots": list(range(11))}, {"langue": "fr;drop"}, {"nombre_emplois": -1}])
def test_parametres_invalides_refuses(params):
    assert client.get("/api/formulaires/main-levee", params=params).status_code == 422


# ---------- Refus d'envoi (aucune écriture) ----------

def _envoi(**kw):
    corps = {"parcours": "main-levee", "langue": "ar", "lot_ids": [], "valeurs": {"zone_industrielle": "Ras El Morj"},
             "contact": {"telephone": "71 000 000"}, "consentement": True, "consentement_version": VERSION}
    return corps | kw


@pytest.fixture
def sans_ecriture(monkeypatch):
    """Toute tentative d'écriture fait échouer le test : les refus doivent arriver avant."""
    def interdit():
        raise AssertionError("écriture tentée")
    monkeypatch.setattr(formulaire, "get_engine_ecriture", interdit)


@pytest.mark.usefixtures("base_disponible", "sans_ecriture")
@pytest.mark.parametrize("corps, code, champ", [
    (_envoi(contact={"cin_numero": "01234567"}), "champ_refuse", "cin_numero"),
    (_envoi(valeurs={"signature_demandeur": "x"}), "champ_refuse", "signature_demandeur"),
    (_envoi(valeurs={"telephone": "71 000 000"}), "champ_refuse", "telephone"),        # contact rangé en projet
    (_envoi(contact={"zone_industrielle": "x"}), "champ_refuse", "zone_industrielle"),  # projet rangé en contact
    (_envoi(valeurs={"recu_date_cachet": "x"}), "champ_refuse", "recu_date_cachet"),
    (_envoi(contact={}), "contact_requis", None),
    (_envoi(contact={"telephone": "   "}), "contact_requis", None),
    (_envoi(consentement=False), "consentement_requis", None),
    (_envoi(consentement_version="2000-01-01"), "consentement_requis", None),
    (_envoi(valeurs={"document_demande": "2"}), "valeur_imposee", "document_demande"),
    (_envoi(valeurs={"date_demande": "27/11/2026"}), "date_attendue", "date_demande"),
    (_envoi(valeurs={"numero_lot": "x" * 201}), "valeur_trop_longue", "numero_lot"),
    (_envoi(valeurs={"numero_lot": "37\n38"}), "valeur_invalide", "numero_lot"),
    (_envoi(lot_ids=[999999999]), "lot_introuvable", "999999999"),
    (_envoi(langue="fr"), "langue_indisponible", None),
    (_envoi(parcours="vente-encheres-publiques"), "formulaire_indisponible", None),
    (_envoi(parcours="acquisition-developpement-regional", langue="fr", valeurs={}, contact={"code_postal": "1002"}),
     "champ_refuse", "code_postal"),                                                    # absent de la variante FR
    (_envoi(parcours="acquisition-developpement-regional", langue="fr", valeurs={"nature": "achat"}),
     "choix_inconnu", "nature"),
    (_envoi(parcours="acquisition-developpement-regional", langue="fr", valeurs={"nombre_emplois": "quarante"}),
     "nombre_attendu", "nombre_emplois"),
])
def test_envoi_refuse_avant_toute_ecriture(corps, code, champ):
    r = client.post("/api/demandes", json=corps)
    assert r.status_code == 422 and r.json()["detail"] == {"code": code, "champ": champ}


def test_corps_inattendu_refuse():
    assert client.post("/api/demandes", json=_envoi(cin="0123")).status_code == 422          # extra=forbid
    assert client.post("/api/demandes", json=_envoi(valeurs={"a": 1})).status_code == 422     # texte seulement


# ---------- Envoi accepté et besoins (base jetable) ----------

@pytest.fixture(scope="module")
def base_publiee(base_jetable):
    s = get_settings()
    if not s.postgres_rw_password.get_secret_value():
        pytest.skip("POSTGRES_RW_PASSWORD absent")
    migrer.appliquer(base_jetable, role_backend=s.postgres_ro_user,
                     compte_ecriture=(s.postgres_rw_user, s.postgres_rw_password.get_secret_value()))
    assert importer_services(base_jetable, CORPUS, appliquer=True).ok
    with psycopg.connect(base_jetable) as c:
        publier(c, par="test")
    assert importer_formulaires(base_jetable, CORPUS, appliquer=True).ok
    return base_jetable


def _moteur(base, ecriture=False):
    """Moteur sur la base jetable avec le vrai compte du backend (lecture seule, ou écriture)."""
    s = get_settings()
    user, mdp = ((s.postgres_rw_user, s.postgres_rw_password) if ecriture else (s.postgres_ro_user, s.postgres_ro_password))
    url = URL.create("postgresql+psycopg", username=user, password=mdp.get_secret_value(), host=s.postgres_host,
                     port=s.postgres_port, database=conninfo_to_dict(base)["dbname"])
    return create_engine(url)


@pytest.fixture
def sur_base_jetable(base_publiee, monkeypatch):
    lecture, ecriture = _moteur(base_publiee), _moteur(base_publiee, ecriture=True)
    monkeypatch.setattr(lots, "get_engine", lambda: lecture)
    monkeypatch.setattr(formulaire, "get_engine_ecriture", lambda: ecriture)
    yield base_publiee
    lecture.dispose()
    ecriture.dispose()


def test_envoi_enregistre_projet_et_contact_consenti(sur_base_jetable):
    r = client.post("/api/demandes", json=_envoi(
        valeurs={"zone_industrielle": " Ras El Morj ", "numero_lot": "37", "objet_demande": "", "date_demande": "2026-11-27"},
        contact={"nom_ou_raison_sociale": "Société Test", "email": "", "telephone": "71 000 000"},
        langue_aide="fr"))
    assert r.status_code == 201, r.text
    d = r.json()
    assert re.fullmatch(r"[A-Z0-9]{4}-[A-Z0-9]{4}", d["reference"]) and d["depot_officiel_effectue"] is False
    with psycopg.connect(sur_base_jetable) as c:
        valeurs, version, contact, accord = c.execute(
            "SELECT d.valeurs, v.numero, k.valeurs, k.consentement_texte FROM assistant.demandes d "
            "JOIN assistant.parcours_versions v ON v.id = d.parcours_version_id "
            "JOIN assistant.demande_contacts k ON k.demande_id = d.id WHERE d.reference = %s",
            (d["reference"],)).fetchone()
    # Valeurs nettoyées, vides retirées, ligne 3 imposée ajoutée par le serveur.
    assert valeurs == {"zone_industrielle": "Ras El Morj", "numero_lot": "37", "date_demande": "2026-11-27",
                       "document_demande": "3"}
    assert contact == {"nom_ou_raison_sociale": "Société Test", "telephone": "71 000 000"}
    assert version == 1 and accord == formulaire.consentement("fr").texte


def test_besoin_non_couvert_note(sur_base_jetable):
    sortie = formulaire.noter_besoin(NoterBesoinEntree(question="Permis de construire ?", langue="fr"))
    assert sortie.donnees.note is True
    with psycopg.connect(sur_base_jetable) as c:
        assert c.execute("SELECT question, langue FROM assistant.besoins_non_couverts").fetchall() == [
            ("Permis de construire ?", "fr")]


def test_besoin_sans_compte_d_ecriture_ne_plante_pas(monkeypatch):
    def absent():
        raise EcritureIndisponible("test")
    monkeypatch.setattr(formulaire, "get_engine_ecriture", absent)
    assert formulaire.noter_besoin(NoterBesoinEntree(question="x")).donnees.note is False


def test_envoi_sans_compte_d_ecriture_503(sur_base_jetable, monkeypatch):
    def absent():
        raise EcritureIndisponible("test")
    monkeypatch.setattr(formulaire, "get_engine_ecriture", absent)
    r = client.post("/api/demandes", json=_envoi())
    assert r.status_code == 503 and r.json()["detail"] == {"code": "envoi_indisponible"}
