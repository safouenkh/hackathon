"""Écritures du backend (compte POSTGRES_RW_USER, rôle `assistant_ecriture`) : ajout seulement.

Le rôle ne peut ni relire ni modifier ce qu'il ajoute ; la base refuse toute valeur hors
catégorie (déclencheur de la migration 0002). SQL paramétré.
"""
from __future__ import annotations

from datetime import datetime

from psycopg.types.json import Jsonb
from sqlalchemy import Connection, text


def inserer_demande(conn: Connection, *, reference: str, parcours_id: int, version_id: int, formulaire_id: int,
                    langue: str, lot_ids: list[int], valeurs: dict[str, str]) -> tuple[int, datetime]:
    ligne = conn.execute(text("""
        INSERT INTO assistant.demandes (reference, parcours_id, parcours_version_id, formulaire_id, langue,
                                        lot_ids, valeurs)
        VALUES (:reference, :parcours_id, :version_id, :formulaire_id, :langue, :lot_ids, :valeurs)
        RETURNING id"""), {"reference": reference, "parcours_id": parcours_id, "version_id": version_id,
                           "formulaire_id": formulaire_id, "langue": langue, "lot_ids": lot_ids,
                           "valeurs": Jsonb(valeurs)}).one()
    # envoyee_le n'est pas lisible par ce rôle : l'heure du serveur de base est relue sans la table.
    return ligne[0], conn.execute(text("SELECT now()")).scalar_one()


def inserer_contact(conn: Connection, *, demande_id: int, valeurs: dict[str, str], consentement_texte: str) -> None:
    conn.execute(text("""
        INSERT INTO assistant.demande_contacts (demande_id, valeurs, consentement_texte)
        VALUES (:d, :v, :c)"""), {"d": demande_id, "v": Jsonb(valeurs), "c": consentement_texte})


def inserer_besoin(conn: Connection, *, question: str, langue: str | None) -> None:
    conn.execute(text("INSERT INTO assistant.besoins_non_couverts (question, langue) VALUES (:q, :l)"),
                 {"q": question, "l": langue})
