"""Relecture et publication des brouillons de parcours (en attendant l'espace admin).

Publier = archiver la version publiée du parcours (s'il y en a une) puis publier le dernier
brouillon, dans une seule transaction. Une version publiée ou archivée ne change plus.
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg


@dataclass(frozen=True)
class Brouillon:
    parcours: str
    version_id: int
    numero: int
    publiee_actuelle: int | None


def brouillons(conn: psycopg.Connection, codes: list[str] | None = None) -> list[Brouillon]:
    """Dernier brouillon de chaque parcours (s'il y en a un)."""
    rows = conn.execute("""
        SELECT p.code, v.id, v.numero,
               (SELECT pv.numero FROM assistant.parcours_versions pv
                 WHERE pv.parcours_id = p.id AND pv.statut = 'publie')
        FROM assistant.parcours p
        JOIN LATERAL (SELECT id, numero FROM assistant.parcours_versions
                      WHERE parcours_id = p.id AND statut = 'brouillon'
                      ORDER BY numero DESC LIMIT 1) v ON true
        WHERE %(codes)s::text[] IS NULL OR p.code = ANY(%(codes)s::text[])
        ORDER BY p.service_id, p.ordre""", {"codes": codes}).fetchall()
    return [Brouillon(*r) for r in rows]


def revue_markdown(conn: psycopg.Connection, codes: list[str] | None = None) -> str:
    """Contenu des brouillons, lisible, pour la relecture avant publication."""
    lignes = ["# Brouillons à relire avant publication", "",
              "Généré depuis la base (schéma `assistant`). Le texte est celui des fiches sources, sans reformulation, "
              "sauf les lignes marquées « ✏️ corrigé » ou « ➕ ajouté ».",
              ""]
    for b in brouillons(conn, codes):
        service, titre, critere = conn.execute(
            "SELECT s.nom, p.titre, p.critere_choix FROM assistant.parcours p "
            "JOIN assistant.services s ON s.id = p.service_id WHERE p.code = %s", (b.parcours,)).fetchone()
        src = conn.execute("""
            SELECT so.url, dv.retrieved_at, dv.sha256 FROM assistant.parcours_versions v
            LEFT JOIN assistant.document_versions dv ON dv.id = v.document_version_id
            LEFT JOIN assistant.documents d ON d.id = dv.document_id
            LEFT JOIN assistant.sources so ON so.id = d.source_id WHERE v.id = %s""", (b.version_id,)).fetchone()
        lignes += [f"## {service} — {b.parcours} (brouillon v{b.numero})", "",
                   f"- Titre d'origine : {titre}",
                   f"- Critère de choix : {critere or '—'}",
                   f"- Version publiée actuelle : {('v' + str(b.publiee_actuelle)) if b.publiee_actuelle else 'aucune'}",
                   f"- Source : {src[0]} (collecte {src[1]}, SHA-256 {src[2][:12]}…)" if src and src[0] else "- Source : —",
                   ""]
        elements = conn.execute(
            "SELECT id, parent_id, type, groupe, ordre, texte, montant_dt, unite_montant, texte_source, "
            "modifie_par_admin, a_verifier, note_verification FROM assistant.parcours_elements "
            "WHERE version_id = %s ORDER BY type, ordre, id", (b.version_id,)).fetchall()
        enfants: dict[int | None, list] = {}
        for e in elements:
            enfants.setdefault(e[1], []).append(e)
        noms = {"description": "Description", "pour_qui": "Pour qui", "condition": "Conditions", "etape": "Étapes",
                "piece": "Pièces", "frais": "Montants cités", "lien": "Liens", "remarque": "Remarques"}

        def ecrire(e, niveau):
            montant = f" — **{e[6].normalize():f} DT{(' ' + e[7]) if e[7] else ''}**" if e[6] is not None else ""
            texte_source, modifie, a_verifier, note = e[8:12]
            marque = (" **➕ ajouté**" if texte_source is None else " **✏️ corrigé**") if modifie else ""
            lignes.append(f"{'  ' * niveau}{e[4]}. {e[5]}{montant}{marque}")
            retrait = "  " * (niveau + 1)
            if modifie and texte_source is not None:
                lignes.append(f"{retrait}> Texte d'origine : {texte_source}")
            if a_verifier:
                lignes.append(f"{retrait}> À vérifier : {note}")
            for c in sorted(enfants.get(e[0], []), key=lambda x: x[4]):
                ecrire(c, niveau + 1)

        for t, nom in noms.items():
            racines = [e for e in enfants.get(None, []) if e[2] == t]
            if not racines:
                continue
            lignes.append(f"### {nom}")
            groupe = object()
            for e in racines:
                if e[3] != groupe and e[3]:
                    lignes.append(f"\n*{e[3]}*\n")
                groupe = e[3]
                ecrire(e, 0)
            lignes.append("")
        for code, valeurs, note in conn.execute(
                "SELECT f.code, pf.valeurs_imposees, pf.note_verification FROM assistant.parcours_formulaires pf "
                "JOIN assistant.formulaires f ON f.id = pf.formulaire_id JOIN assistant.parcours p ON p.id = pf.parcours_id "
                "WHERE p.code = %s", (b.parcours,)).fetchall():
            lignes.append(f"### Formulaire : `{code}` {valeurs or ''}")
            if note:
                lignes.append(f"\n> À vérifier : {note}")
            lignes.append("")
    return "\n".join(lignes) + "\n"


def publier(conn: psycopg.Connection, par: str, codes: list[str] | None = None) -> list[Brouillon]:
    if not par.strip():
        raise ValueError("indiquer qui publie (--par)")
    faits = brouillons(conn, codes)
    with conn.transaction():
        for b in faits:
            conn.execute("UPDATE assistant.parcours_versions SET statut = 'archive' "
                         "WHERE parcours_id = (SELECT parcours_id FROM assistant.parcours_versions WHERE id = %s) "
                         "AND statut = 'publie'", (b.version_id,))
            conn.execute("UPDATE assistant.parcours_versions SET statut = 'publie', publie_par = %s, publie_le = now() "
                         "WHERE id = %s", (par.strip(), b.version_id))
    return faits
