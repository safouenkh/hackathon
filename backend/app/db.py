"""Connexions PostgreSQL du backend : lecture seule (outils), et un compte d'écriture séparé qui peut
seulement ajouter une demande, un contact consenti ou un besoin non couvert. Petits pools, délai
maximal par requête."""
from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine

from app.config import get_settings

STATEMENT_TIMEOUT_MS = 2000


@lru_cache
def get_engine() -> Engine:
    s = get_settings()
    url = URL.create(
        "postgresql+psycopg",
        username=s.postgres_ro_user,
        password=s.postgres_ro_password.get_secret_value(),
        host=s.postgres_host,
        port=s.postgres_port,
        database=s.postgres_db,
    )
    return create_engine(
        url,
        connect_args={
            "options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS} -c default_transaction_read_only=on",
            "connect_timeout": 3,
        },
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
    )


class EcritureIndisponible(RuntimeError):
    """POSTGRES_RW_PASSWORD absent : l'envoi des demandes est désactivé (la lecture reste possible)."""


@lru_cache
def get_engine_ecriture() -> Engine:
    s = get_settings()
    if not s.postgres_rw_user or not s.postgres_rw_password.get_secret_value():
        raise EcritureIndisponible("compte d'écriture non configuré (POSTGRES_RW_USER / POSTGRES_RW_PASSWORD)")
    url = URL.create(
        "postgresql+psycopg",
        username=s.postgres_rw_user,
        password=s.postgres_rw_password.get_secret_value(),
        host=s.postgres_host,
        port=s.postgres_port,
        database=s.postgres_db,
    )
    return create_engine(
        url,
        connect_args={"options": f"-c statement_timeout={STATEMENT_TIMEOUT_MS}", "connect_timeout": 3},
        pool_size=2,
        max_overflow=2,
        pool_pre_ping=True,
    )
