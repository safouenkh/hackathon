"""Jeu de test métier du rôle 3 (BNF1 exactitude, BNF13 cohérence).

Chaque valeur attendue vient d'une source indépendante de l'outil testé : ligne de la liste
publique https://afi.e-industrie.gov.tn/liste.php (lue le 26/11/2026), texte d'une fiche de
chatbot_connaissances, ou requête SQL écrite à part. Détail et preuves : docs/jeu_test_metier.md.
"""
import pytest

from app.processing.registre import executer
from app.processing.schemas import CodeAvertissement as C, ServiceAfiId, StatutLot

pytestmark = pytest.mark.usefixtures("base_disponible")


def test_m01_lot_public_ariana_aeroport_117():
    # liste.php : « Ariana | ARIANA AEROPORT | 117 | 34735 | 100 »
    lot = executer("details_lot", {"lot_id": 4138}).donnees.lot
    assert (lot.zone_nom, lot.numero, lot.surface_m2, lot.prix_indicatif_dt_m2) == ("ARIANA AEROPORT", "117", 34735, 100)
    assert lot.gouvernorat == "Ariana"
    assert lot.statut is StatutLot.aux_encheres          # LOT_ETAPE = 4 (carte publique : « Mis aux enchères »)


def test_m02_prix_dump_different_du_site_signale():
    # liste.php : « Monastir | Ras El Morj Monastir | 37 | 3122 | 90 » ; dump : prixunitaire = 70
    lot = executer("details_lot", {"lot_id": 7079}).donnees.lot
    assert lot.surface_m2 == 3122 and lot.prix_indicatif_dt_m2 == 70
    assert {C.prix_indicatif, C.prix_ecart_site_public} <= set(lot.avertissements)


def test_m03_bf10_3000m2_pres_d_un_port_le_moins_cher():
    # « Lot de 3000 m² près d'un port, moins cher possible » : zones à ≤ 40 km d'un port, puis lots.
    # Attendu par SQL indépendant : lot 7079 (Ras El Morj, lot 37), 3122 × 70 = 218 540 DT.
    zones = executer("lots_proches", {"type": "port", "distance_max_km": 40, "limite": 50}).donnees.zones
    lots = executer("chercher_lots", {"zone_ids": [z.zone.zone_id for z in zones],
                                      "surface_min_m2": 3000, "limite": 3}).donnees.lots
    assert [(l.lot_id, l.prix_total_indicatif_dt) for l in lots] == [(7079, 218540), (7094, 247450), (7095, 255570)]


def test_m03b_bf10_en_un_seul_appel():
    # Même attendu (SQL indépendant), avec le filtre de proximité intégré à chercher_lots.
    lots = executer("chercher_lots", {"pres_de": "port", "distance_max_km": 40,
                                      "surface_min_m2": 3000, "limite": 3}).donnees.lots
    assert [(l.lot_id, l.prix_total_indicatif_dt, l.distance_equipement_km, l.equipement_nom) for l in lots] == [
        (7079, 218540, 35.0, "Sousse"), (7094, 247450, 35.0, "Sousse"), (7095, 255570, 35.0, "Sousse")]


def test_m04_comptage_disponibles_sfax():
    # SQL indépendant : 2 lots LOT_ETAPE = 1 dans les zones gouv_id = 20 (Sfax)
    assert executer("chercher_lots", {"gouvernorat": "Sfax"}).donnees.total_correspondants == 2


def test_m05_tejra_rattachee_a_medenine():
    # liste.php range Tejra sous « Mednine » ; SQL : 25 lots LOT_ETAPE = 1 dans la zone 931103
    r = executer("chercher_lots", {"zone_ids": [931103], "limite": 50})
    assert r.donnees.total_correspondants == 25
    assert {l.gouvernorat for l in r.donnees.lots} == {"Médenine"}


@pytest.mark.parametrize("ecriture", ["Sfax", "sfax", "SFAX", "صفاقس", "gouvernorat de Sfax"])
def test_m06_bnf13_meme_resultat_quelle_que_soit_l_ecriture(ecriture):
    reference = executer("chercher_lots", {"gouvernorat": "Sfax", "limite": 50}).donnees.lots
    assert executer("chercher_lots", {"gouvernorat": ecriture, "limite": 50}).donnees.lots == reference


@pytest.mark.parametrize("service, texte_source, montant", [
    ("situation_fonciere", "frais : 50 DT", 50),          # fiche 18
    ("insertion_hypotheque", "frais : 50 DT", 50),        # fiche 19
    ("acte_precision", "frais : 150 DT", 150),            # fiche 20
    ("copie_conforme", "frais : 15 DT par copie", 15),    # fiche 22
    ("mainlevee", "frais : 50 DT", 50),                   # fiche 23
])
def test_m07_bf23_frais_de_la_source(service, texte_source, montant):
    frais = [x for f in executer("demarche", {"service": service}).donnees.fiches for x in f.frais
             if x.montant_dt is not None]
    assert [(x.texte_source, x.montant_dt) for x in frais] == [(texte_source, montant)]


def test_m08_bf22_papier_pour_le_pret():
    # Exemple du cahier des charges, BF22
    r = executer("services_afi", {"besoin": "La banque me demande un papier pour mon prêt"})
    assert r.donnees.candidats[0].service.id is ServiceAfiId.insertion_hypotheque


def test_m09_bf24_service_hors_liste():
    # Fiche 26 : « téléphone +216 71 124 260 »
    r = executer("demarche", {"service": "permis de construire"})
    assert r.donnees.fiches == [] and r.donnees.contact_afi.telephone == "+216 71 124 260"
    assert C.service_non_couvert in {a.code for a in r.avertissements}


def test_m10_lot_orphelin_jamais_rattache():
    # Lot 5422 : lots.zone_id = '932107X', absent de zones
    lot = executer("details_lot", {"lot_id": 5422}).donnees.lot
    assert lot.zone_id is None and lot.gouvernorat is None and C.lot_orphelin in lot.avertissements


def test_m11_bf11_rien_n_est_depose():
    d = executer("preparer_demande", {"lot_ids": [7079]}).donnees
    assert d.depot_effectue is False and d.confirmation_requise is True
