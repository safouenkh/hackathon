"""Fiches de démarches administratives hors AFI (SICAD) : SQL paramétré, lecture seule, LIMIT.

Une fiche = un document `fiche_sicad` ; on lit toujours sa version la plus récente.
"""
from __future__ import annotations

from sqlalchemy import Connection, text

TYPE_DOCUMENT = "fiche_sicad"
_DERNIERE_VERSION = """
    dv.id = (SELECT v2.id FROM assistant.document_versions v2 WHERE v2.document_id = d.id
             ORDER BY v2.retrieved_at DESC NULLS LAST, v2.id DESC LIMIT 1)
"""
_COLONNES = """
    d.id AS document_id, dv.id AS version_id, de.titre, de.type_fiche, de.organismes, de.secteur, de.domaines,
    de.documents_joints, de.id_source, so.url, dv.retrieved_at
"""
_JOINTURES = """
    FROM assistant.documents d
    JOIN assistant.document_versions dv ON dv.document_id = d.id
    JOIN assistant.demarches_externes de ON de.version_id = dv.id
    JOIN assistant.sources so ON so.id = d.source_id
"""


def demarches(conn: Connection, limite: int = 5000) -> list[dict]:
    """Métadonnées de toutes les fiches (dernière version) : pour le graphe RDF."""
    rows = conn.execute(text(
        f"SELECT {_COLONNES} {_JOINTURES} WHERE d.type = :t AND {_DERNIERE_VERSION} ORDER BY d.id LIMIT :n"
    ), {"t": TYPE_DOCUMENT, "n": limite}).mappings().all()
    return [dict(r) for r in rows]


def fiches(conn: Connection, document_ids: list[int]) -> dict[int, dict]:
    """Fiches complètes (texte de la dernière version compris) des documents demandés."""
    if not document_ids:
        return {}
    rows = conn.execute(text(
        f"SELECT {_COLONNES}, dv.full_text {_JOINTURES} "
        f"WHERE d.type = :t AND d.id = ANY(CAST(:ids AS bigint[])) AND {_DERNIERE_VERSION} LIMIT 50"
    ), {"t": TYPE_DOCUMENT, "ids": [int(i) for i in document_ids]}).mappings().all()
    return {r["document_id"]: dict(r) for r in rows}
