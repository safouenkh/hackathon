import pytest

from app.processing.schemas import CodeAvertissement, StatutLot
from app.processing.statuts import statut_depuis_etape


@pytest.mark.parametrize("etape, attendu", [
    (1, StatutLot.disponible),
    (4, StatutLot.aux_encheres),
    (2, StatutLot.non_disponible),
    (3, StatutLot.non_disponible),
    (0, StatutLot.non_disponible),
    (5, StatutLot.inconnu),
])
def test_correspondance_confirmee(etape, attendu):
    assert statut_depuis_etape(etape).statut is attendu


@pytest.mark.parametrize("etape", [None, 6, 99, -1])
def test_code_inattendu_donne_inconnu(etape):
    r = statut_depuis_etape(etape)
    assert r.statut is StatutLot.inconnu
    assert CodeAvertissement.statut_inconnu in r.avertissements


def test_gris_signale_statut_inconnu():
    assert CodeAvertissement.statut_inconnu in statut_depuis_etape(5).avertissements


@pytest.mark.parametrize("etape", [1, 4])
def test_disponibilite_toujours_marquee_non_fraiche(etape):
    # Instantané du 13/11/2026 : un lot « disponible » doit être reconfirmé auprès de l'AFI.
    assert CodeAvertissement.donnee_non_fraiche in statut_depuis_etape(etape).avertissements
