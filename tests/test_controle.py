"""Contrôle après rédaction (prototype BNF1) : cas réels observés avec Gemini le 26/11/2026."""
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.banc import router as banc_router
from app.banc.controle import controler, nombres_du_texte

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
