"""Voix (BF7, BF8, BNF4) : client du service « langues et voix » et routes /voix, avec un faux service."""
import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.langue import client
from app.main import app


class _Rep:
    def __init__(self, code, donnees):
        self.status_code, self._d = code, donnees

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code != 200:
            raise httpx.HTTPStatusError("x", request=None, response=None)


@pytest.fixture
def service(monkeypatch):
    """Faux service : note les appels ; /understand dit « aeb » pour l'arabizi, « fr » sinon."""
    appels = []

    def post(url, timeout=None, **kw):
        appels.append((url.rsplit("/", 1)[1], kw))
        if url.endswith("/understand"):
            return _Rep(200, {"language": "aeb" if "n7eb" in kw["json"]["text"] else "fr", "script": "latin"})
        if url.endswith("/transcribe"):
            return _Rep(200, {"text": " n7eb terrain f Sfax ", "model": "tn-small", "language_hint": "aeb",
                              "total_s": 1.2})
        if url.endswith("/speak"):
            return _Rep(200, {"audio_base64": base64.b64encode(b"RIFF").decode(), "engine": "piper",
                              "voice": "ar_JO-kareem", "dialect_authentic": False, "generation_s": 0.4})
        return _Rep(404, {})

    monkeypatch.setattr(client.httpx, "post", post)
    monkeypatch.setattr(get_settings(), "langue_url", "http://service-test")
    return appels


def test_texte_a_lire_remplace_les_balises_et_retire_les_liens():
    t = client.texte_a_lire("Voir [[LOT:4799:Lot 12]] dans [[ZONE:931803:El Krib]] : https://afi.nat.tn/x **ok**")
    assert t == "Voir Lot 12 dans El Krib: ok"


def test_texte_a_lire_exemple_reel_en_arabe():
    # Réponse réelle signalée le 27/11 : liens, code interne et citations en français lus à voix haute
    r = ("المنظمة المختصة: [APIA](https://www.apia.com.tn/incitations-financieres-2.html) (« Incitations "
         "financières au profit des investissements »). بالنسبة لإنتاج أسماك البحر (Poisson bleu): « Prime 20% "
         "Plafonnée à 150000DT » ([Subvention financière](https://www.apia.com.tn/subvention-financiere.html)). "
         "(ملاحظة: أحكام سابقة (régime_ancien))")
    t = client.texte_a_lire(r, "ar")
    for absent in ("http", "www", "régime_ancien", "Incitations", "Poisson", "Plafonnée", "[", "»", ":.", "( )"):
        assert absent not in t, absent
    assert "APIA" in t and "(ملاحظة: أحكام سابقة)" in t        # la remarque en arabe reste


@pytest.mark.parametrize("langue,texte,attendu", [
    ("fr", "153 m² à 50 Dt/m², soit 7650 DT ; 15 % ; 1,5 MDT ; 35 km",
     "153 mètres carrés à 50 dinars le mètre carré, soit 7650 dinars; 15 pour cent; 1,5 millions de dinars; 35 kilomètres"),
    ("tr", "Prim %20, 150000 DT", "Prim yüzde 20, 150000 dinar"),
    ("fr", "plafond de 500 mille DT et de 1 million de DT", "plafond de 500 mille dinars et de 1 million de dinars"),
    ("ar", "منحة 20% في حدود 150000 DT", "منحة 20 بالمائة في حدود 150000 دينار"),
])
def test_unites_prononcees(langue, texte, attendu):
    assert client.texte_a_lire(texte, langue) == attendu


def test_longue_reponse_lue_en_plusieurs_morceaux(monkeypatch):
    # Le service refuse plus de 1200 caractères (erreur 422 vue le 27/11 sur une réponse en français)
    import io, wave
    def wav():
        b = io.BytesIO()
        with wave.open(b, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\x00\x00" * 100)
        return base64.b64encode(b.getvalue()).decode()
    tailles = []
    def post(url, timeout=None, **kw):
        tailles.append(len(kw["json"]["text"]))
        assert len(kw["json"]["text"]) <= 1200
        return _Rep(200, {"audio_base64": wav(), "engine": "piper", "voice": "fr", "generation_s": 0.1})
    monkeypatch.setattr(client.httpx, "post", post)
    monkeypatch.setattr(get_settings(), "langue_url", "http://service-test")
    r = client.lire("Une phrase de la réponse. " * 120, "fr")
    assert len(tailles) >= 3
    with wave.open(io.BytesIO(base64.b64decode(r["audio_base64"])), "rb") as w:
        assert w.getnframes() == 100 * len(tailles)                 # un seul fichier, tous les morceaux


def test_sources_construites_par_le_code():
    from app.banc.sources import sources_du_tour
    appels = [{"outil": "avantages", "resultat": {"donnees": {
        "orientation": [{"organisation": "APIA", "role": "octroi_avantages", "citation": "phrase exacte",
                         "url": "https://www.apia.com.tn/x", "date_source": "2026-11-27"}],
        "incitations": [{"organisme": "APIA", "intitule": "Prime", "extrait": "20 %", "url": "https://a/b",
                         "date_source": "2026-11-27", "regime_ancien": True}]}}},
              {"outil": "chercher_lots", "resultat": {"provenance": [{"type": "sql", "table": "afi.lots",
                                                                     "date_donnees": "2026-11-13"}]}}]
    s = sources_du_tour(appels)
    assert [x["titre"] for x in s] == ["APIA (avantages)", "APIA — Prime", "Base de données de l'AFI (instantané)"]
    assert s[1]["a_verifier"].startswith("ancien code") and s[0]["extrait"] == "phrase exacte"


def test_transcrire_renvoie_le_texte_reconnu(service):
    r = client.transcrire(b"\x1aE\xdf\xa3audio", "audio/webm")
    assert r == {"texte": "n7eb terrain f Sfax", "langue": "aeb", "modele": "tn-small", "duree_s": 1.2,
                 "modele_de_secours": False}


def test_dialecte_lu_avec_voix_arabe_generique_signale(service):
    r = client.lire("n7eb terrain f Sfax ?")
    assert r["langue"] == "aeb" and r["voix_arabe_generique"] is True       # BF8 : signalé
    assert [nom for nom, _ in service] == ["understand", "speak"]
    assert service[1][1]["json"]["language"] == "aeb"


def test_lettres_arabes_jamais_lues_en_francais(service):
    # le faux service répond « fr » (erreur mesurée sur le vrai service) : le client corrige en « ar »
    assert client.detecter("أرغب في شراء قطعة أرض صناعية في ولاية سوسة").code == "ar"
    assert client.detecter("Je cherche un lot à Sousse").code == "fr"


@pytest.mark.parametrize("texte,code,mot", [
    ("Quelle est la hauteur maximale à El Krib ?", "fr", "en français"),
    ("Je cherche un lot de 3000 m2 à Sousse", "fr", "en français"),          # « m2 » n'est pas de l'arabizi
    ("n7eb terrain f Sfax", "aeb", "arabizi"),
    ("3andi projet sardine, chkoun ynajem y3awenni ?", "aeb", "arabizi"),
    ("البنكة طلبتلي ورقة باش ناخو قرض", "ar", "lettres arabes"),
])
def test_consigne_langue_sans_service(texte, code, mot):
    c, consigne = client.consigne_langue(texte, service=False)
    assert c == code and mot in consigne


def test_consigne_langue_suit_le_service_et_garde_l_ecriture(service):
    assert client.consigne_langue("n7eb terrain f Sfax")[0] == "aeb"
    c, consigne = client.consigne_langue("أرغب في شراء قطعة أرض")      # service : « fr » -> corrigé
    assert c == "ar" and "jamais en arabizi" in consigne


def test_banc_garde_la_langue_apres_un_clic_choix():
    from app.banc.gemini import Banc

    b = Banc.__new__(Banc)
    b.langue_de = lambda t: client.consigne_langue(t, service=False)
    b.journal = lambda _l: None
    b.consigne_langue, b.code_langue = "", None
    b.balises_outils = {"[[CHOIX:Attestation d'insertion d'hypothèque]]"}
    b._langue("n7eb war9a lel banka")
    assert b.code_langue == "aeb"
    b._langue("Attestation d'insertion d'hypothèque")            # libellé du bouton, en français
    assert b.code_langue == "aeb"
    b._langue("Merci, et pour la mainlevée ?")                   # nouveau message écrit : nouvelle langue
    assert b.code_langue == "fr"


def test_francais_pas_de_signalement(service):
    assert client.lire("Bonjour, voici les lots.")["voix_arabe_generique"] is False


def test_service_non_configure(monkeypatch):
    monkeypatch.setattr(get_settings(), "langue_url", "")
    with pytest.raises(client.ServiceLangueIndisponible):
        client.lire("Bonjour")
    assert client.etat()["disponible"] is False


def test_api_service_en_panne_message_court(monkeypatch):
    def panne(*a, **k):
        raise httpx.ConnectError("refusé")
    monkeypatch.setattr(client.httpx, "post", panne)
    monkeypatch.setattr(get_settings(), "langue_url", "http://service-test")
    r = TestClient(app).post("/voix/lire", json={"texte": "Bonjour"})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "voix_indisponible"
    assert "Traceback" not in r.text


def test_api_transcrire_et_audio_trop_long(service):
    c = TestClient(app)
    r = c.post("/voix/transcrire", content=b"audio", headers={"Content-Type": "audio/webm"})
    assert r.status_code == 200 and r.json()["texte"] == "n7eb terrain f Sfax"
    r = c.post("/voix/transcrire", content=b"", headers={"Content-Type": "audio/webm"})
    assert r.status_code == 422
    r = c.post("/voix/transcrire", content=b"x" * 10, headers={"Content-Length": str(client.TAILLE_AUDIO_MAX + 1)})
    assert r.status_code == 413
