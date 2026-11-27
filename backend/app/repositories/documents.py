"""Lecture des passages de documents (assistant.document_chunks) : SQL paramétré, lecture seule, LIMIT.

Le texte de référence d'un passage est toujours relu ici : Qdrant ne sert qu'à le retrouver.
"""
from __future__ import annotations

from sqlalchemy import Connection, text

_COLONNES = """
    c.id::text AS passage_id, c.version_id, c.ordinal, c.text AS texte, c.page_from, c.page_to, c.article,
    c.section, c.heading, c.partie, c.categorie_sol, c.a_verifier, d.id AS document_id, d.title AS titre,
    d.zone_id, d.type AS type_document, dv.retrieved_at, so.organisation, so.url AS source_url
"""
_JOINTURES = """
    FROM assistant.document_chunks c
    JOIN assistant.document_versions dv ON dv.id = c.version_id
    JOIN assistant.documents d ON d.id = dv.document_id
    JOIN assistant.sources so ON so.id = d.source_id
"""
TYPES_INDEXES = ("cahier_charges", "page_organisme", "fiche_sicad", "fiche_afi")


def passages_a_indexer(conn: Connection, types: tuple[str, ...] = TYPES_INDEXES, limite: int = 20_000) -> list[dict]:
    """Passages de la version la plus RÉCENTE (date de collecte, puis id) de chaque document des types demandés."""
    rows = conn.execute(text(
        f"SELECT {_COLONNES} {_JOINTURES} "
        "WHERE d.type = ANY(CAST(:types AS text[])) "
        "  AND dv.id = (SELECT v2.id FROM assistant.document_versions v2 WHERE v2.document_id = d.id "
        "               ORDER BY v2.retrieved_at DESC NULLS LAST, v2.id DESC LIMIT 1) "
        "ORDER BY d.id, c.ordinal LIMIT :n"), {"types": list(types), "n": limite}).mappings().all()
    return [dict(r) for r in rows]


def passages_par_ids(conn: Connection, ids: list[str]) -> dict[str, dict]:
    """Passages relus en base ; `debut_version` = début du texte de la page (ex. annonce du régime juridique)."""
    rows = conn.execute(text(
        f"SELECT {_COLONNES}, left(dv.full_text, 300) AS debut_version {_JOINTURES} "
        "WHERE c.id = ANY(CAST(:ids AS uuid[])) LIMIT 50"
    ), {"ids": ids}).mappings().all()
    return {r["passage_id"]: dict(r) for r in rows}
