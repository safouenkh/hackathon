"""Lecture des règles d'orientation (assistant.regles_orientation, migrations 0004-0005) : lecture seule, LIMIT."""
from __future__ import annotations

from sqlalchemy import Connection, text


def regles_actives(conn: Connection) -> list[dict]:
    rows = conn.execute(text("""
        SELECT r.id, r.organisation, r.role, r.secteur, r.secteurs_exclus, r.investissement_min_dt,
               r.investissement_max_dt, r.investisseur_etranger, r.citation, so.url, dv.retrieved_at
        FROM assistant.regles_orientation r
        JOIN assistant.document_versions dv ON dv.id = r.version_id
        JOIN assistant.documents d ON d.id = dv.document_id
        JOIN assistant.sources so ON so.id = d.source_id
        WHERE r.actif
        ORDER BY r.organisation, r.id
        LIMIT 100""")).mappings().all()
    return [dict(r) for r in rows]
