"""Checks on the real PostgreSQL copy, run with the backend's read-only role.

Skipped when the database is not reachable (e.g. CI without Docker).
"""
import psycopg
import pytest

from app.config import get_settings


@pytest.fixture(scope="module")
def ro_conn():
    try:
        conn = psycopg.connect(get_settings().conninfo(admin=False), connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL indisponible : {exc}")
    yield conn
    conn.close()


def _fails(conn, query: str) -> type[Exception]:
    with pytest.raises(psycopg.Error) as info:
        conn.execute(query)
    conn.rollback()
    return type(info.value)


def test_volumes_match_inspection_report(ro_conn):
    counts = {
        t: ro_conn.execute(f"SELECT count(*) FROM afi.{t}").fetchone()[0]
        for t in ("zones", "lots", "zone_services", "zone_commodites", "zone_documents",
                  "chatbot_connaissances", "chatbot_sources")
    }
    assert counts == {
        "zones": 185, "lots": 6579, "zone_services": 1628, "zone_commodites": 1501,
        "zone_documents": 106, "chatbot_connaissances": 85, "chatbot_sources": 150,
    }


def test_orphan_lots(ro_conn):
    n = ro_conn.execute(
        "SELECT count(*) FROM afi.lots l LEFT JOIN afi.zones z ON z.code_zone::text = l.zone_id "
        "WHERE z.code_zone IS NULL"
    ).fetchone()[0]
    assert n == 24


@pytest.mark.parametrize("column", [
    "lot_promoteur", "lot_contrat_date", "lot_contrat_ref", "lot_dossier",
    "lot_inv_id", "lot_projet", "main_levee", "main_levee_date",
])
def test_forbidden_lot_columns_are_not_readable(ro_conn, column):
    assert _fails(ro_conn, f"SELECT {column} FROM afi.lots LIMIT 1") is psycopg.errors.InsufficientPrivilege


def test_select_star_on_lots_is_refused(ro_conn):
    assert _fails(ro_conn, "SELECT * FROM afi.lots LIMIT 1") is psycopg.errors.InsufficientPrivilege


@pytest.mark.parametrize("table", ["chatbot_logs", "chatbot_besoins", "chatbot_rapports"])
def test_conversation_tables_are_not_readable(ro_conn, table):
    assert _fails(ro_conn, f"SELECT 1 FROM afi.{table} LIMIT 1") is psycopg.errors.InsufficientPrivilege


def test_writes_are_refused(ro_conn):
    assert _fails(ro_conn, "UPDATE afi.zones SET prixunitaire = 0 WHERE false") in (
        psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege)
    assert _fails(ro_conn, "CREATE TABLE afi.x (i int)") in (
        psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege)
