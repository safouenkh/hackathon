import psycopg
import pytest

from app.config import get_settings


@pytest.fixture(scope="session")
def base_disponible():
    """Saute les tests d'intégration si PostgreSQL n'est pas joignable."""
    try:
        psycopg.connect(get_settings().conninfo(admin=False), connect_timeout=3).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL indisponible : {exc}")


# Identifiants réels du dump du 13/11/2026 utilisés comme cas limites (relevés par requête SQL).
LOT_ORPHELIN = 5422            # zone_id '932107X' absente de zones
LOT_GRIS = 18                  # LOT_ETAPE = 5 -> inconnu
LOT_SURFACE_NEGATIVE = 5241    # LOT_SUP_LOTIS < 0
LOT_PRIX_ABERRANT = 6924       # zone 9302051, prixunitaire = 2022
LOT_COORD_INVALIDES = 5470     # zone 932116 Sidi Salem, coordonnées 0 / 0
LOT_ENCHERES_ARIANA = 4138     # zone 930301, lot 117, LOT_ETAPE = 4, 34 735 m², 100 Dt/m² (liste.php)
LOT_RAS_EL_MORJ_37 = 7079      # zone 932119, lot 37, 3 122 m², LOT_ETAPE = 1

CHAMPS_INTERDITS = ("promoteur", "contrat", "dossier", "inv_id", "lot_projet", "main_levee")


def assert_aucun_champ_interdit(sortie) -> None:
    texte = sortie.model_dump_json().lower()
    for champ in CHAMPS_INTERDITS:
        assert f'"{champ}' not in texte and f"lot_{champ}" not in texte, champ
