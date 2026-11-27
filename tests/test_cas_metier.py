"""Jeu de test métier du rôle 3 (BNF1 exactitude, BNF13 cohérence).

Chaque valeur attendue vient d'une source indépendante de l'outil testé : ligne de la liste
publique https://afi.e-industrie.gov.tn/liste.php (lue le 26/11/2026), texte d'une fiche de
chatbot_connaissances, page « Nos services » de l'AFI, ou requête SQL écrite à part. Détail et preuves : docs/jeu_test_metier.md.
"""
import pytest

from app.processing.registre import executer
from app.processing.schemas import CodeAvertissement as C, StatutLot

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
    # Attendu par SQL indépendant (27/11/2026, avec assistant.zone_complements) : Gabès 88888 n'a pas de prix
    # dans la base AFI ; le complément du JSON de l'équipe donne 50 Dt/m² -> lot 4799 (11:9), 3085 × 50 = 154 250 DT.
    # Sans complément, l'attendu était le lot 7079 (Ras El Morj), 218 540 DT.
    zones = executer("lots_proches", {"type": "port", "distance_max_km": 40, "limite": 50}).donnees.zones
    r = executer("chercher_lots", {"zone_ids": [z.zone.zone_id for z in zones], "surface_min_m2": 3000, "limite": 3})
    assert [(l.lot_id, l.prix_total_indicatif_dt) for l in r.donnees.lots] == [(4799, 154250), (4858, 154400),
                                                                                (4859, 154450)]
    assert all(C.valeur_complementaire in l.avertissements for l in r.donnees.lots)
    assert any(p.table == "assistant.zone_complements" and p.ids == ["88888"] for p in r.provenance)


def test_m03b_bf10_en_un_seul_appel():
    # Même attendu (SQL indépendant), avec le filtre de proximité intégré à chercher_lots.
    lots = executer("chercher_lots", {"pres_de": "port", "distance_max_km": 40,
                                      "surface_min_m2": 3000, "limite": 3}).donnees.lots
    assert [(l.lot_id, l.prix_total_indicatif_dt, l.distance_equipement_km, l.equipement_nom) for l in lots] == [
        (4799, 154250, 0.0, "Gabes"), (4858, 154400, 0.0, "Gabes"), (4859, 154450, 0.0, "Gabes")]


def test_m03c_valeur_afi_jamais_remplacee_par_le_complement():
    # Ras El Morj 932119 : base AFI 70 Dt/m², JSON de l'équipe 90 -> la base AFI est gardée, sans complément.
    lot = executer("details_lot", {"lot_id": 7079}).donnees.lot
    assert lot.prix_indicatif_dt_m2 == 70 and C.valeur_complementaire not in lot.avertissements


def test_m03d_commodites_completees_marquees_et_sourcees():
    # Zone 931300 (Kasserine extension) : aucune distance dans afi.zone_commodites ; JSON de l'équipe :
    # port 204 km, aéroport 200 km (docs/revue_paquet_graphrag.md).
    r = executer("details_lot", {"lot_id": 46})
    port = [x for x in r.donnees.commodites_zone if x.type.value == "port"]
    assert [(x.distance_km, x.valeur_texte) for x in port] == [(204.0, "204 km")]
    assert any(a.code is C.valeur_complementaire and a.detail.startswith("com_2 (ZONE_PORT_DIST)")
               for a in r.avertissements)
    assert any(p.table == "assistant.zone_complements" for p in r.provenance)


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


@pytest.mark.parametrize("service, extrait, montant", [   # page « Nos services », lue le 27/11/2026
    ("situation_fonciere", "s’élevant à **50 dinars tunisiens (DT)**", 50),
    ("insertion_hypotheque", "d’un montant de 50 Dinar.", 50),
    ("acte_precision", "d’un montant de 150 Dinar", 150),
    ("copie_conforme", "(15 dinars par copie)", 15),
    ("mainlevee", "s’élevant à 50 dinars.", 50),            # étape 5 corrigée d'après la page arabe (50د)
])
def test_m07_bf23_frais_de_la_source(service, extrait, montant):
    frais = [x for p in executer("demarche", {"service": service}).donnees.parcours for x in p.frais]
    assert [(extrait in x.texte, x.montant_dt) for x in frais] == [(True, montant)]


def test_m08_bf22_papier_pour_le_pret():
    # Exemple du cahier des charges, BF22
    r = executer("services_afi", {"besoin": "La banque me demande un papier pour mon prêt"})
    assert r.donnees.candidats[0].service.id == "insertion_hypotheque"


def test_m09_bf24_service_hors_liste():
    # Fiche 26 : « téléphone +216 71 124 260 »
    r = executer("demarche", {"service": "permis de construire"})
    assert r.donnees.parcours == [] and r.donnees.contact_afi.telephone == "+216 71 124 260"
    assert C.service_non_couvert in {a.code for a in r.avertissements}


def test_m10_lot_orphelin_jamais_rattache():
    # Lot 5422 : lots.zone_id = '932107X', absent de zones
    lot = executer("details_lot", {"lot_id": 5422}).donnees.lot
    assert lot.zone_id is None and lot.gouvernorat is None and C.lot_orphelin in lot.avertissements


def test_m11_bf11_rien_n_est_depose():
    d = executer("preparer_demande", {"service": "acquisition", "lot_ids": [7079]}).donnees
    assert d.depot_effectue is False and d.confirmation_requise is True
