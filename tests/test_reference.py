import pytest

from app.processing.lots import distance_depuis_texte, haversine_km
from app.processing.reference import coordonnees_valides, gouv_id_depuis_nom
from app.processing.schemas import Balise


@pytest.mark.parametrize("nom, attendu", [
    ("Sfax", 20), ("sfax", 20), ("SFAX", 20), ("صفاقس", 20), ("Gabès", 7), ("gabes", 7),
    ("Béja", 5), ("Le Kef", 13), ("el kef", 13), ("Médenine", 15), ("Mednine", 15),
    ("gouvernorat de Sousse", 21), ("La Manouba", 4), ("أريانة", 2), ("Kairouen", 10),
])
def test_gouvernorat_reconnu(nom, attendu):
    assert gouv_id_depuis_nom(nom) == attendu


@pytest.mark.parametrize("nom", ["", None, "Paris", "Sfaxx", "Tunisie"])
def test_gouvernorat_non_reconnu(nom):
    assert gouv_id_depuis_nom(nom) is None


@pytest.mark.parametrize("lat, lon, ok", [
    ("36.85", "10.21", True), ("", "10.2", False), (None, None, False), ("0", "0", False),
    ("37.146805", "37.146805", False),  # zone 930904 : latitude = longitude
    ("10.2", "36.8", False),            # inversées
    ("abc", "10", False),
])
def test_coordonnees(lat, lon, ok):
    assert (coordonnees_valides(lat, lon) is not None) is ok


@pytest.mark.parametrize("valeur, attendu", [
    ("3,5 km", 3.5), ("17 km", 17.0), ("0 km", 0.0), (" 1.5 km ", 1.5),
    ("127 - 115 km", None), ("10 _ 1 km", None), ("15, 1 km", None), ("", None), (None, None),
])
def test_distance_depuis_texte(valeur, attendu):
    assert distance_depuis_texte(valeur) == attendu


def test_haversine_un_degre_equateur():
    assert haversine_km((0.0, 0.0), (0.0, 1.0)) == pytest.approx(111.195, abs=0.01)


def test_balise_echappe_le_libelle():
    b = Balise(type="LOT", id="7", libelle="Lot 3: [A]")
    assert b.texte == "[[LOT:7:Lot 3 - (A)]]"
    assert Balise(type="CHOIX", libelle="Copie conforme").texte == "[[CHOIX:Copie conforme]]"
