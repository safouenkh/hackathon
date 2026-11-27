"""Applique les migrations SQL du dossier migrations/ au schéma `assistant`.

Usage (depuis la racine du projet, .env rempli) :
    .venv\\Scripts\\python.exe -m scripts.migrer               # état seulement, ne modifie rien
    .venv\\Scripts\\python.exe -m scripts.migrer --appliquer   # applique les migrations en attente

Règles :
- fichiers `NNNN_nom.sql`, appliqués dans l'ordre, chacun dans sa propre transaction ;
- chaque migration appliquée est enregistrée avec son empreinte SHA-256 dans
  `assistant.schema_migrations` ; une migration déjà appliquée puis modifiée bloque tout
  (on écrit une nouvelle migration au lieu de modifier l'ancienne) ;
- connexion avec le compte administrateur (POSTGRES_ADMIN_USER) ; le rôle du backend
  (POSTGRES_RO_USER) reçoit seulement le rôle de lecture `assistant_lecture` ;
- si POSTGRES_RW_USER et POSTGRES_RW_PASSWORD sont remplis, ce compte est créé (ou son mot de
  passe mis à jour) et reçoit seulement le rôle `assistant_ecriture` (ajout de demandes).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import get_settings  # noqa: E402

DOSSIER = Path(__file__).resolve().parents[1] / "migrations"
_NOM_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
ROLE_LECTURE = "assistant_lecture"
ROLE_ECRITURE = "assistant_ecriture"

_TABLE_SUIVI = """
CREATE SCHEMA IF NOT EXISTS assistant;
CREATE TABLE IF NOT EXISTS assistant.schema_migrations (
    version     text PRIMARY KEY,
    nom         text NOT NULL,
    sha256      text NOT NULL,
    applique_le timestamptz NOT NULL DEFAULT now()
)
"""


@dataclass(frozen=True)
class Migration:
    version: str
    nom: str
    chemin: Path

    @property
    def contenu(self) -> str:
        return self.chemin.read_text(encoding="utf-8")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.chemin.read_bytes()).hexdigest()


class MigrationModifiee(RuntimeError):
    pass


def lister(dossier: Path = DOSSIER) -> list[Migration]:
    migrations = []
    for f in sorted(dossier.glob("*.sql")):
        m = _NOM_RE.match(f.name)
        if not m:
            raise ValueError(f"nom de migration invalide : {f.name} (attendu NNNN_nom.sql)")
        migrations.append(Migration(m.group(1), m.group(2), f))
    versions = [m.version for m in migrations]
    if len(set(versions)) != len(versions):
        raise ValueError("deux migrations ont le même numéro")
    return migrations


def appliquees(conn: psycopg.Connection) -> dict[str, str]:
    existe = conn.execute("SELECT to_regclass('assistant.schema_migrations') IS NOT NULL").fetchone()[0]
    if not existe:
        return {}
    return dict(conn.execute("SELECT version, sha256 FROM assistant.schema_migrations").fetchall())


def en_attente(conn: psycopg.Connection, migrations: list[Migration]) -> list[Migration]:
    faites = appliquees(conn)
    for m in migrations:
        if m.version in faites and faites[m.version] != m.sha256:
            raise MigrationModifiee(
                f"la migration {m.chemin.name} a été modifiée après son application : "
                "écrire une nouvelle migration au lieu de la modifier")
    return [m for m in migrations if m.version not in faites]


def _compte_ecriture(conn: psycopg.Connection, utilisateur: str, mot_de_passe: str) -> None:
    """Crée (ou met à jour) le compte de connexion d'écriture, membre du seul rôle assistant_ecriture."""
    if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE_ECRITURE,)).fetchone():
        return  # migration 0002 pas encore appliquée
    verbe = "ALTER" if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (utilisateur,)).fetchone() else "CREATE"
    conn.execute(sql.SQL(verbe + " ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}").format(
        sql.Identifier(utilisateur), sql.Literal(mot_de_passe)))
    conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(ROLE_ECRITURE), sql.Identifier(utilisateur)))


def appliquer(conninfo: str, role_backend: str | None, dossier: Path = DOSSIER,
              compte_ecriture: tuple[str, str] | None = None) -> list[str]:
    """Applique les migrations en attente ; renvoie les noms des fichiers appliqués."""
    migrations = lister(dossier)
    faits: list[str] = []
    with psycopg.connect(conninfo) as conn:
        a_faire = en_attente(conn, migrations)
        for m in a_faire:
            with conn.transaction():
                conn.execute(_TABLE_SUIVI)
                conn.execute(m.contenu)
                conn.execute("INSERT INTO assistant.schema_migrations (version, nom, sha256) VALUES (%s, %s, %s)",
                             (m.version, m.nom, m.sha256))
            faits.append(m.chemin.name)
        if role_backend:
            role_existe = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ROLE_LECTURE,)).fetchone()
            backend_existe = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role_backend,)).fetchone()
            if role_existe and backend_existe:
                conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(ROLE_LECTURE),
                                                             sql.Identifier(role_backend)))
        if compte_ecriture:
            _compte_ecriture(conn, *compte_ecriture)
        conn.commit()
    return faits


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--appliquer", action="store_true", help="appliquer les migrations en attente")
    a = p.parse_args()
    s = get_settings()
    conninfo = s.conninfo(admin=True)
    migrations = lister()
    with psycopg.connect(conninfo) as conn:
        faites = appliquees(conn)
        attente = en_attente(conn, migrations)
    for m in migrations:
        etat = "appliquée" if m.version in faites else "EN ATTENTE"
        print(f"{m.chemin.name:<40} {etat}  sha256={m.sha256[:12]}")
    if not a.appliquer:
        print(f"\n{len(attente)} migration(s) en attente. Rien n'a été modifié (ajouter --appliquer).")
        return 0
    rw_mdp = s.postgres_rw_password.get_secret_value()
    compte = (s.postgres_rw_user, rw_mdp) if s.postgres_rw_user and rw_mdp else None
    faits = appliquer(conninfo, s.postgres_ro_user, compte_ecriture=compte)
    print(f"\nAppliquée(s) : {', '.join(faits) or 'aucune'} ; rôle {ROLE_LECTURE} accordé à {s.postgres_ro_user}.")
    if compte:
        print(f"Rôle {ROLE_ECRITURE} accordé à {s.postgres_rw_user}.")
    else:
        print("POSTGRES_RW_USER / POSTGRES_RW_PASSWORD vides : aucun compte d'écriture (l'envoi des demandes "
              "sera indisponible).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except MigrationModifiee as exc:
        print(f"ARRÊT : {exc}", file=sys.stderr)
        raise SystemExit(1)
