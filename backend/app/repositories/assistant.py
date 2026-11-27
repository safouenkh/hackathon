"""Lecture du schéma `assistant` (services, parcours publiés, formulaires) : SQL paramétré, LIMIT partout.

Seules les versions PUBLIÉES sont lues : un brouillon n'est jamais montré à un investisseur.
"""
from __future__ import annotations

from sqlalchemy import Connection, text


def services(conn: Connection) -> list[dict]:
    rows = conn.execute(text(
        "SELECT code, nom, besoin, ordre FROM assistant.services WHERE actif ORDER BY ordre, code LIMIT 50"
    )).mappings().all()
    return [dict(r) for r in rows]


def parcours_publies(conn: Connection, service: str | None = None, parcours: str | None = None) -> list[dict]:
    """Parcours actifs ayant une version publiée, avec la source de cette version."""
    rows = conn.execute(text("""
        SELECT p.id, p.code, p.titre, p.critere_choix, p.ordre, s.code AS service,
               v.id AS version_id, v.numero, v.publie_le,
               so.url AS url_source, dv.retrieved_at AS date_collecte, dv.sha256
        FROM assistant.parcours p
        JOIN assistant.services s ON s.id = p.service_id AND s.actif
        JOIN assistant.parcours_versions v ON v.parcours_id = p.id AND v.statut = 'publie'
        LEFT JOIN assistant.document_versions dv ON dv.id = v.document_version_id
        LEFT JOIN assistant.documents d ON d.id = dv.document_id
        LEFT JOIN assistant.sources so ON so.id = d.source_id
        WHERE p.actif
          AND (CAST(:service AS text) IS NULL OR s.code = :service)
          AND (CAST(:parcours AS text) IS NULL OR p.code = :parcours)
        ORDER BY s.ordre, p.ordre, p.code
        LIMIT 20"""), {"service": service, "parcours": parcours}).mappings().all()
    return [dict(r) for r in rows]


def elements(conn: Connection, version_ids: list[int]) -> list[dict]:
    """Éléments des versions, dans l'ordre du document source (ordre d'insertion à l'import)."""
    rows = conn.execute(text("""
        SELECT id, version_id, parent_id, type, groupe, ordre, titre, texte, montant_dt, unite_montant,
               url, a_verifier, note_verification, modifie_par_admin
        FROM assistant.parcours_elements
        WHERE version_id = ANY(CAST(:ids AS bigint[]))
        ORDER BY version_id, id
        LIMIT 2000"""), {"ids": version_ids}).mappings().all()
    return [dict(r) for r in rows]


def formulaires(conn: Connection, parcours_ids: list[int]) -> list[dict]:
    rows = conn.execute(text("""
        SELECT pf.parcours_id, f.id AS formulaire_id, f.code, f.titre, pf.valeurs_imposees, pf.a_verifier,
               pf.note_verification,
               fv.langue, fv.titre_officiel, fv.url_page, fv.url_fichier
        FROM assistant.parcours_formulaires pf
        JOIN assistant.formulaires f ON f.id = pf.formulaire_id AND f.actif
        LEFT JOIN assistant.formulaire_variantes fv ON fv.formulaire_id = f.id
        WHERE pf.parcours_id = ANY(CAST(:ids AS bigint[]))
        ORDER BY pf.parcours_id, f.code, fv.langue
        LIMIT 200"""), {"ids": parcours_ids}).mappings().all()
    return [dict(r) for r in rows]


def sections_formulaire(conn: Connection, formulaire_id: int) -> list[dict]:
    rows = conn.execute(text("""
        SELECT s.code, s.ordre, l.langue, l.libelle, l.source_texte
        FROM assistant.formulaire_sections s
        LEFT JOIN assistant.formulaire_section_libelles l ON l.section_id = s.id
        WHERE s.formulaire_id = :f
        ORDER BY s.ordre, s.code, l.langue
        LIMIT 500"""), {"f": formulaire_id}).mappings().all()
    return [dict(r) for r in rows]


def champs_formulaire(conn: Connection, formulaire_id: int) -> list[dict]:
    """Champs avec leurs libellés (une ligne par champ et par langue)."""
    rows = conn.execute(text("""
        SELECT c.code, c.section, c.ordre, c.type, c.categorie_donnee, c.choix, c.unite, c.obligatoire,
               c.prerempli_depuis, l.langue, l.libelle, l.officiel, l.aide
        FROM assistant.formulaire_champs c
        LEFT JOIN assistant.formulaire_champ_libelles l ON l.champ_id = c.id
        WHERE c.formulaire_id = :f
        ORDER BY c.ordre, c.code, l.langue
        LIMIT 2000"""), {"f": formulaire_id}).mappings().all()
    return [dict(r) for r in rows]


def mentions_formulaire(conn: Connection, formulaire_id: int, langue: str) -> list[dict]:
    rows = conn.execute(text("""
        SELECT section, ordre, texte, si_champ, si_valeur
        FROM assistant.formulaire_mentions
        WHERE formulaire_id = :f AND langue = :l
        ORDER BY section, ordre
        LIMIT 200"""), {"f": formulaire_id, "l": langue}).mappings().all()
    return [dict(r) for r in rows]
