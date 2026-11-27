import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from app.config import get_settings
from scripts import migrer


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


class ConninfoMasque(str):
    """Chaîne de connexion dont la représentation cache le mot de passe (pytest l'affiche en cas d'échec)."""

    def __repr__(self) -> str:
        return "<conninfo " + " ".join(p for p in self.split() if not p.startswith("password=")) + ">"


def vider_assistant(conninfo) -> None:
    """Vide toutes les tables du schéma `assistant` d'une base jetable (sauf le suivi des migrations).
    TRUNCATE ne déclenche pas les protections des versions publiées."""
    with psycopg.connect(conninfo) as c:
        tables = [r[0] for r in c.execute(
            "SELECT format('assistant.%I', tablename) FROM pg_tables "
            "WHERE schemaname = 'assistant' AND tablename <> 'schema_migrations'")]
        c.execute(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY")


@pytest.fixture(scope="module")
def base_jetable():
    """Base temporaire du même serveur, supprimée à la fin du module : `dalila` n'est jamais touchée."""
    s = get_settings()
    admin = s.conninfo(admin=True)
    nom = f"dalila_test_migr_{uuid.uuid4().hex[:10]}"
    try:
        serveur = psycopg.connect(admin, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL indisponible : {exc}")
    with serveur:
        # Les rôles sont communs à tout le serveur : on supprime à la fin celui créé par le test.
        roles_avant = {r[0] for r in serveur.execute(
            "SELECT rolname FROM pg_roles WHERE rolname IN (%s, %s)", (migrer.ROLE_LECTURE, migrer.ROLE_ECRITURE))}
        serveur.execute(f'CREATE DATABASE "{nom}"')
        try:
            yield ConninfoMasque(make_conninfo(admin, dbname=nom))
        finally:
            serveur.execute(f'DROP DATABASE IF EXISTS "{nom}" WITH (FORCE)')
            for role in {migrer.ROLE_LECTURE, migrer.ROLE_ECRITURE} - roles_avant:
                serveur.execute(f'DROP ROLE IF EXISTS "{role}"')
