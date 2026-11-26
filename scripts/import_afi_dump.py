"""Import the AFI MariaDB dump into PostgreSQL (schema `afi`) and set up the read-only role.

Usage (from the project root, with .env filled in):
    .venv\\Scripts\\python.exe -m scripts.import_afi_dump

What it does, in one transaction:
- recreates schema `afi` (a faithful copy of the dump; nothing else lives there);
- creates each table with lower-case column names and mapped types;
- loads the rows with COPY; empty strings in date/timestamp columns become NULL (counted);
- re-creates exactly the PRIMARY / UNIQUE keys and indexes declared in the dump;
- creates schema `assistant` (empty) if missing;
- creates/updates role POSTGRES_RO_USER: read-only, no access to personal or
  contractual columns of `lots`, no access to the chatbot logs/needs/reports tables.
It never modifies the dump file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402
from scripts.mariadb_dump import parse_dump, pg_type  # noqa: E402

SCHEMA = "afi"

# Columns of `lots` that must never leave the database (personal or contractual data).
FORBIDDEN_LOT_COLUMNS = {
    "lot_promoteur", "lot_contrat_date", "lot_contrat_ref", "lot_dossier",
    "lot_inv_id", "lot_projet", "main_levee", "main_levee_date",
}
# Tables holding visitor conversations or identifiers: not readable by the backend role.
TABLES_HIDDEN_FROM_RO = {"chatbot_logs", "chatbot_besoins", "chatbot_rapports"}


def _ident(*names: str) -> sql.Identifier:
    return sql.Identifier(*names)


def _cols(names: list[str]) -> sql.Composed:
    return sql.SQL(", ").join(_ident(n.lower()) for n in names)


def main() -> int:
    settings = get_settings()
    dump_path = Path(settings.afi_dump_path)
    tables = parse_dump(dump_path.read_text(encoding="utf-8"))
    ro_user = settings.postgres_ro_user
    ro_password = settings.postgres_ro_password.get_secret_value()
    if not ro_password:
        print("POSTGRES_RO_PASSWORD est vide dans .env", file=sys.stderr)
        return 1

    with psycopg.connect(settings.conninfo(admin=True)) as conn, conn.cursor() as cur:
        cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(_ident(SCHEMA)))
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(_ident(SCHEMA)))
        cur.execute("CREATE SCHEMA IF NOT EXISTS assistant")

        report = []
        for t in tables.values():
            col_defs = sql.SQL(", ").join(
                sql.SQL("{} {}{}").format(
                    _ident(c.name.lower()),
                    sql.SQL(pg_type(c.mysql_type)),
                    sql.SQL("") if c.nullable else sql.SQL(" NOT NULL"),
                )
                for c in t.columns
            )
            cur.execute(sql.SQL("CREATE TABLE {} ({})").format(_ident(SCHEMA, t.name), col_defs))

            date_idx = [i for i, c in enumerate(t.columns) if pg_type(c.mysql_type) in ("date", "timestamp")]
            blanked = 0
            copy_stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(
                _ident(SCHEMA, t.name), _cols([c.name for c in t.columns])
            )
            with cur.copy(copy_stmt) as copy:
                for row in t.rows:
                    for i in date_idx:
                        if row[i] == "":
                            row = list(row)
                            row[i] = None
                            blanked += 1
                    copy.write_row(row)

            if t.primary_key:
                cur.execute(sql.SQL("ALTER TABLE {} ADD PRIMARY KEY ({})").format(
                    _ident(SCHEMA, t.name), _cols(t.primary_key)))
            for uk in t.unique_keys:
                cur.execute(sql.SQL("ALTER TABLE {} ADD UNIQUE ({})").format(
                    _ident(SCHEMA, t.name), _cols(uk)))
            for ix in t.indexes:
                cur.execute(sql.SQL("CREATE INDEX ON {} ({})").format(
                    _ident(SCHEMA, t.name), _cols(ix)))

            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(_ident(SCHEMA, t.name)))
            loaded = cur.fetchone()[0]
            report.append((t.name, len(t.rows), loaded, blanked, t.primary_key, len(t.unique_keys), len(t.indexes)))

        # Read-only role for the backend
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ro_user,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(sql.SQL(verb + " ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
            _ident(ro_user), sql.Literal(ro_password)))
        cur.execute(sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(_ident(ro_user)))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(_ident(SCHEMA), _ident(ro_user)))
        for t in tables.values():
            if t.name in TABLES_HIDDEN_FROM_RO:
                continue
            if t.name == "lots":
                allowed = [c.name for c in t.columns if c.name.lower() not in FORBIDDEN_LOT_COLUMNS]
                cur.execute(sql.SQL("GRANT SELECT ({}) ON {} TO {}").format(
                    _cols(allowed), _ident(SCHEMA, t.name), _ident(ro_user)))
            else:
                cur.execute(sql.SQL("GRANT SELECT ON {} TO {}").format(_ident(SCHEMA, t.name), _ident(ro_user)))
        conn.commit()

    print(f"{'table':<24}{'dump':>7}{'chargé':>8}{'dates vides->NULL':>19}  clés")
    ok = True
    for name, expected, loaded, blanked, pk, nuk, nix in report:
        ok &= expected == loaded
        print(f"{name:<24}{expected:>7}{loaded:>8}{blanked:>19}  PK={pk or '-'} UNIQUE={nuk} INDEX={nix}")
    print("OK : tous les comptages correspondent" if ok else "ERREUR : comptages différents")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
