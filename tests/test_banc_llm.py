"""Tests hors ligne du banc LLM : aucun appel réseau, un faux client renvoie de vrais objets google.genai."""
import json

import pytest

genai_types = pytest.importorskip("google.genai.types")

from scripts.banc_llm_gemini import Banc, declarations, executer_outil  # noqa: E402


def test_declarations_valides_et_autonomes():
    decl = declarations()
    assert [d.name for d in decl] == ["chercher_lots", "details_lot", "comparer_lots", "lots_proches",
                                      "avantages", "services_afi", "demarche", "guider_service",
                                      "preparer_demande", "noter_besoin", "regles_zone",
                                      "demarches_administratives", "connaissances_afi"]
    for d in decl:
        assert "$ref" not in json.dumps(d.parameters_json_schema)


def test_argument_invalide_renvoye_au_modele_sans_exception():
    r = executer_outil("chercher_lots", {"limite": 1000, "sql": "DROP TABLE afi.lots"})
    assert r["erreur"] == "arguments_invalides"
    assert executer_outil("supprimer_tout", {})["erreur"] == "outil_inconnu"


def test_erreur_de_validation_serialisable_en_json():
    # Cas réel du 26/11 : « près du port » sans rayon -> erreur de validateur (ValueError dans le contexte)
    r = executer_outil("chercher_lots", {"pres_de": "port"})
    assert r["erreur"] == "arguments_invalides"
    assert "distance_max_km" in json.dumps(r, ensure_ascii=False)


class _FauxModeles:
    def __init__(self, reponses, en_panne=()):
        self.reponses = list(reponses)
        self.appels = []
        self.en_panne = set(en_panne)
        self.modeles_appeles = []

    def generate_content(self, model, contents, config):
        self.modeles_appeles.append(model)
        if model in self.en_panne:
            raise RuntimeError("503 UNAVAILABLE")
        self.appels.append(list(contents))
        return self.reponses.pop(0)


class _FauxClient:
    def __init__(self, reponses, en_panne=()):
        self.models = _FauxModeles(reponses, en_panne)


def test_repli_sur_le_modele_suivant():
    client = _FauxClient([_reponse(genai_types.Part.from_text(text="ok"))], en_panne={"principal"})
    banc = Banc(client, "principal", journal=lambda _l: None, modeles_repli=["secours"])
    assert banc.poser("bonjour") == "ok"
    assert client.models.modeles_appeles == ["principal", "secours"] and banc.modele_utilise == "secours"


def test_tous_les_modeles_en_panne_message_court():
    client = _FauxClient([], en_panne={"a", "b"})
    banc = Banc(client, "a", journal=lambda _l: None, modeles_repli=["b"])
    r = banc.poser("bonjour")
    assert r.startswith("[modèle indisponible") and "Traceback" not in r
    assert banc.historique == []              # la question échouée n'encombre pas la suite


def _reponse(*parts):
    return genai_types.GenerateContentResponse(
        candidates=[genai_types.Candidate(content=genai_types.Content(role="model", parts=list(parts)))])


@pytest.mark.usefixtures("base_disponible")
def test_boucle_appelle_l_outil_puis_repond():
    client = _FauxClient([
        _reponse(genai_types.Part.from_function_call(name="details_lot", args={"lot_id": 7079})),
        _reponse(genai_types.Part.from_text(text="Le lot 37 fait 3122 m².")),
    ])
    journal = []
    banc = Banc(client, "faux-modele", journal=journal.append)
    assert banc.poser("Fiche du lot 7079 ?") == "Le lot 37 fait 3122 m²."
    assert len(journal) == 1 and journal[0].startswith("  -> details_lot")
    # Le 2e appel au modèle contient la réponse de l'outil avec les vraies données
    dernier = client.models.appels[1][-1]
    reponse_outil = dernier.parts[0].function_response
    assert reponse_outil.name == "details_lot"
    assert reponse_outil.response["donnees"]["lot"]["surface_m2"] == 3122
    # Contrôle des balises : celle de l'outil est acceptée, une balise inventée est signalée
    assert banc.balises_inventees("[[LOT:7079:Lot 37 - Ras El Morj Monastir]]") == []
    assert banc.balises_inventees("Voir [[LOT:7079]]") == ["[[LOT:7079]]"]


def _texte(txt):
    return _reponse(genai_types.Part.from_text(text=txt))


@pytest.mark.usefixtures("base_disponible")
def test_controle_sur_toute_la_conversation_pas_seulement_le_dernier_tour():
    """Une réponse sans nouvel appel d'outil peut reprendre un résultat du tour précédent."""
    client = _FauxClient([
        _reponse(genai_types.Part.from_function_call(name="details_lot", args={"lot_id": 7079})),
        _texte("Le lot 37 fait 3122 m²."),
        _texte("Son prix total indicatif est de 218540 DT."),          # aucun outil appelé dans ce tour
    ])
    banc = Banc(client, "faux", journal=lambda _l: None)
    banc.poser("Fiche du lot 7079 ?")
    assert banc.poser("et son prix ?") == "Son prix total indicatif est de 218540 DT."
    assert banc.controler("et son prix ?", "Son prix total indicatif est de 218540 DT.")["ok"]
    assert len(client.models.appels) == 3                            # aucune correction demandée


def test_une_seule_correction_demandee_quand_le_contact_est_invente():
    client = _FauxClient([_texte("Contactez-nous : 18, Rue 8011, Charguia, +216 71 785 233"),
                          _texte("Je n'ai pas d'adresse à vous donner pour le moment.")])
    banc = Banc(client, "faux", journal=lambda _l: None)
    assert banc.poser("où est l'AFI ?") == "Je n'ai pas d'adresse à vous donner pour le moment."
    envoye = client.models.appels[1][-1].parts[0].text
    assert envoye.startswith("Contrôle automatique") and "8011" in envoye


def test_la_correction_n_est_demandee_qu_une_fois_meme_si_le_defaut_persiste():
    client = _FauxClient([_texte("Appelez le +216 71 785 233"), _texte("Appelez le +216 71 785 366")])
    banc = Banc(client, "faux", journal=lambda _l: None)
    assert banc.poser("contact ?") == "Appelez le +216 71 785 366"      # 2 appels au modèle, pas plus
    assert len(client.models.appels) == 2


def test_message_technique_du_banc_pas_controle():
    banc = Banc(_FauxClient([]), "faux", journal=lambda _l: None)
    assert banc.controler("q", "[modèle indisponible : a HTTP 429 — réessayer plus tard]")["ok"]


def test_donnees_personnelles_jamais_envoyees_au_llm():
    client = _FauxClient([_texte("D'accord, saisissez vos coordonnées sur la page du formulaire.")])
    banc = Banc(client, "faux", journal=lambda _l: None)
    banc.poser("esmi Ahmed Test, CIN 01234567, tel 99 000 000, 7adherli el talab")
    envoye = client.models.appels[0][0].parts[0].text
    assert "Ahmed" not in envoye and "01234567" not in envoye and "99 000 000" not in envoye
    assert "[nom masqué]" in envoye and "7adherli el talab" in envoye
    assert banc.donnees_masquees == ("identite", "telephone", "nom")
    assert "01234567" not in str(banc.historique)
