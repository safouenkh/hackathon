"""Fiches validées de l'AFI (afi.chatbot_connaissances) rendues cherchables.

Le cahier (annexe, « II. Base de données ») présente cette table comme la « base de connaissances validée
par l'AFI ». Chaque fiche active (sauf celles que l'ontologie écarte, afi:ficheEcartee) devient un document
`fiche_afi` (clé `connaissance:<id>`), découpé en passages et indexé dans Qdrant. Le texte rendu par
l'outil connaissances_afi est toujours relu dans afi.chatbot_connaissances : l'index sert à la retrouver.
"""
from __future__ import annotations

from app.processing.schemas import DATE_INSTANTANE_AFI
from app.sources import organismes as org

TYPE_DOCUMENT = "fiche_afi"
ORGANISATION = "AFI"
TITRE_SOURCE = "Base de connaissances validée par l'AFI (afi.chatbot_connaissances)"
PREFIXE_CLE = "connaissance:"


def cle(fiche_id: int) -> str:
    return f"{PREFIXE_CLE}{fiche_id}"


def ecrire(conn, r: "org.Rapport", ecartees: tuple[int, ...]) -> int:
    """Fiches actives -> documents `fiche_afi` ; renvoie le nombre de fiches écrites."""
    sid = org._un(conn, "SELECT id FROM assistant.sources WHERE url IS NULL AND organisation = %s AND title = %s",
                  (ORGANISATION, TITRE_SOURCE))
    if sid is None:
        sid = org._un(conn, "INSERT INTO assistant.sources (organisation, title, url, ingestion_mode, last_status) "
                            "VALUES (%s, %s, NULL, 'manuel', 'dump_afi') RETURNING id", (ORGANISATION, TITRE_SOURCE))
    n = 0
    for fid, question, reponse, lang, maj in conn.execute(
            "SELECT id, question, reponse, lang, updated_at::date FROM afi.chatbot_connaissances "
            "WHERE actif = 1 AND coalesce(reponse, '') <> '' ORDER BY id LIMIT 1000").fetchall():
        if fid in ecartees:
            continue
        titre = " ".join(question.split())
        doc = org._un(conn, "SELECT id FROM assistant.documents WHERE cle = %s", (cle(fid),))
        if doc is None:
            org._un(conn, "INSERT INTO assistant.documents (source_id, cle, title, type, language) "
                          "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (sid, cle(fid), titre[:500], TYPE_DOCUMENT, lang if lang in ("fr", "ar") else None))
        org._version(
            conn, r, source_id=sid, url=None, titre=titre, chemin=None, cle_doc=cle(fid),
            type_document=TYPE_DOCUMENT, texte=f"# {titre}\n\n{reponse.strip()}\n",
            provenance=f"afi.chatbot_connaissances id={fid} (fiche validée par l'AFI, mise à jour le {maj}), "
                       f"dump AFI du {DATE_INSTANTANE_AFI}.",
            recupere_le=DATE_INSTANTANE_AFI, etiquette=cle(fid))
        n += 1
    return n
