import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import LOT_RAS_EL_MORJ_37

client = TestClient(app)


def test_catalogue_des_outils():
    r = client.get("/outils")
    assert r.status_code == 200
    noms = [o["nom"] for o in r.json()]
    assert noms == ["chercher_lots", "details_lot", "comparer_lots", "lots_proches", "avantages",
                    "services_afi", "demarche", "preparer_demande"]
    assert all("properties" in o["entree"] for o in r.json())


def test_argument_inconnu_refuse():
    r = client.post("/outils/chercher_lots", json={"gouvernorat": "Sfax", "sql": "DROP TABLE afi.lots"})
    assert r.status_code == 422


def test_limite_bornee():
    assert client.post("/outils/chercher_lots", json={"limite": 1000}).status_code == 422


@pytest.mark.usefixtures("base_disponible")
def test_appel_outil():
    r = client.post("/outils/details_lot", json={"lot_id": LOT_RAS_EL_MORJ_37})
    assert r.status_code == 200
    corps = r.json()
    assert corps["outil"] == "details_lot" and corps["donnees"]["lot"]["surface_m2"] == 3122
    assert "[[LOT:7079:Lot 37 - Ras El Morj Monastir]]" in [b["texte"] for b in corps["balises"]]
