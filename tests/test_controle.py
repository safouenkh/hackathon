"""Contrôle après rédaction (prototype BNF1) : cas réels observés avec Gemini le 26/11/2026."""
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.banc import router as banc_router
from app.banc.controle import controler, message_correction, nombres_du_texte, reparer_balises

SORTIE = {"donnees": {"lots": [{"lot_id": 7079, "surface_m2": 3122, "prix_indicatif_dt_m2": 70,
                                "prix_total_indicatif_dt": 218540, "distance_equipement_km": 35.0}],
                      "total_correspondants": 159},
          "balises": [{"texte": "[[LOT:7079:Lot 37 - Ras El Morj Monastir]]"}]}
BALISES = {"[[LOT:7079:Lot 37 - Ras El Morj Monastir]]"}


def test_reponse_fidele_ok():
    r = controler("[[LOT:7079:Lot 37 - Ras El Morj Monastir]] : 3 122 m², 70 Dt/m², total 218 540 DT, port à 35 km. "
                  "159 lots correspondent.", [SORTIE], BALISES)
    assert r["ok"], r


def test_chiffre_modifie_plus_de_159():
    r = controler("لقيت برشا أراضي متوفرة (أكثر من 159 لوط)", [SORTIE], BALISES)
    assert not r["ok"] and r["chiffres_modifies"] == ["أكثر من 159"]


def test_nombre_invente():
    r = controler("Le total est de 220 000 DT.", [SORTIE], BALISES)
    assert r["nombres_non_trouves"] == ["220 000"]


def test_balise_inventee():
    r = controler("Voir [[LOT:7079]]", [SORTIE], BALISES)
    assert r["balises_inventees"] == ["[[LOT:7079]]"]


def test_decimales_et_chiffres_arabes():
    sortie = {"valeur_texte": "3,5 km", "surface_m2": 3185}
    assert controler("المسافة 3,5 كم والمساحة ٣١٨٥ م²", [sortie], set())["ok"]


def test_numerotation_dates_et_question_ignorees():
    r = controler("1. Premier lot\n2. Deuxième lot\nDonnées du 13/11/2026, pour vos 3000 m².",
                  [SORTIE], BALISES, textes_autorises=["un lot de 3000 m²"])
    assert r["ok"], r


def test_nombres_du_texte():
    assert nombres_du_texte("218 540 DT et 3,5 km et 1800") == ["218 540", "3,5", "1800"]


def test_page_du_banc_servie():
    app = FastAPI()
    app.include_router(banc_router)
    r = TestClient(app).get("/banc")
    assert r.status_code == 200 and "Banc de test Dalila" in r.text
    assert not re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML|document\.write", r.text)


def test_banc_desactive_par_defaut():
    from app.config import Settings
    assert Settings(_env_file=None).banc_llm_actif is False


# ---------- Balises abîmées et correction (essai du 27/11/2026) ----------

PDF = "[[PDF:https://www.afi.nat.tn/wp-content/uploads/2023/04/%D9%85%D8%B7%D9%84%D8%A8-%D8%AE%D8%AF%D9%85%D8%A9-%D8%A5%D8%AF%D8%A7%D8%B1%D9%8A%D8%A9.pdf:مطلب خدمة إدارية (ar)]]"
VALIDES = {PDF, "[[LOT:7079:Lot 37 - Ras El Morj Monastir]]", "[[CHOIX:Attestation de mainlevée]]"}


def test_url_pdf_abimee_retablie():
    abimee = PDF.replace("%D8%A5%D8%AF", "%D8%A5=%AD")         # corruption observée avec Gemini
    assert abimee not in VALIDES and controler(abimee, [], VALIDES)["balises_inventees"] == [abimee]
    texte, remplacees = reparer_balises(f"Voir {abimee}", VALIDES)
    assert texte == f"Voir {PDF}" and remplacees == [(abimee, PDF)]
    assert controler(texte, [], VALIDES)["ok"]


def test_libelle_de_lot_change_retabli_par_l_identifiant():
    texte, _ = reparer_balises("[[LOT:7079:Lot 37]]", VALIDES)
    assert texte == "[[LOT:7079:Lot 37 - Ras El Morj Monastir]]"


def test_lot_voisin_jamais_confondu():
    """Un chiffre de différence = un autre lot : la balise reste, et le contrôle la signale."""
    texte, remplacees = reparer_balises("[[LOT:7080:Lot 37 - Ras El Morj Monastir]]", VALIDES)
    assert remplacees == [] and texte == "[[LOT:7080:Lot 37 - Ras El Morj Monastir]]"


def test_choix_proche_retabli_choix_different_laisse():
    assert reparer_balises("[[CHOIX:Attestation de mainlevee]]", VALIDES)[0] == "[[CHOIX:Attestation de mainlevée]]"
    assert reparer_balises("[[CHOIX:Copie conforme]]", VALIDES)[1] == []


def test_contact_invente_signale_puis_accepte_s_il_vient_d_un_outil():
    inventee = "Adresse : 18, Rue 8011, Z.I. Nord-Est, Charguia I, 2035 Tunis. Tél : +216 71 785 233"
    assert not controler(inventee, [SORTIE], BALISES)["ok"]          # cas réel : adresse inventée
    contact = {"donnees": {"contact_afi": {"adresse": "9 et 13 rue Chott Mariem, 1002 Tunis", "telephone": "+216 71 124 260"}}}
    assert controler("Adresse : 9 et 13 rue Chott Mariem, 1002 Tunis. Tél : +216 71 124 260", [contact], set())["ok"]


def test_message_de_correction_cite_les_defauts_sans_recopier_une_url_entiere():
    m = message_correction({"nombres_non_trouves": ["18", "2035"], "chiffres_modifies": ["plus de 70"],
                           "balises_inventees": [PDF]})
    assert "18, 2035" in m and "plus de 70" in m and "services_afi" in m and len(m) < 700
