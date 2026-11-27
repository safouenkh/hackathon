"""Outil connaissances_afi : fiches validées de l'AFI (afi.chatbot_connaissances) les plus proches de la question.

Recherche hybride Qdrant dans les documents `fiche_afi` (une fiche = un document, clé `connaissance:<id>`),
puis texte intégral relu dans afi.chatbot_connaissances (la référence validée par l'AFI). Les fiches
écartées par l'ontologie (afi:ficheEcartee) ne sont jamais rendues. Sans index : `source_indisponible`.
"""
from __future__ import annotations

from sqlalchemy import Connection

from app.config import get_settings
from app.processing.lots import _connexion
from app.processing.schemas import (
    DATE_INSTANTANE_AFI, Avertissement, CodeAvertissement as C, ConnaissancesAfiDonnees, ConnaissancesAfiEntree,
    FicheAfi, Provenance, SortieOutil,
)
from app.repositories import afi as repo
from app.repositories import documents as repo_docs
from app.semantique.ontologie import ontologie
from app.sources.connaissances import PREFIXE_CLE, TYPE_DOCUMENT

TABLE = "afi.chatbot_connaissances"


class SourceFichesAfi:
    """Qdrant (type fiche_afi) -> identifiants de fiches, par pertinence, sans doublon."""

    disponible = True

    def __init__(self, client=None, enc=None, collection: str | None = None) -> None:
        self._client, self._enc, self._collection = client, enc, collection

    def rechercher(self, question: str, limite: int) -> list[int]:
        from sqlalchemy import text

        from app.semantique import passages

        trouves = passages.rechercher(
            self._client or passages.client_qdrant(), self._enc or passages.encodeur(), question,
            collection=self._collection or get_settings().qdrant_collection_passages,
            types_document=[TYPE_DOCUMENT], parties=["contenu"], limite=limite * 3)
        if not trouves:
            return []
        with _connexion(None) as c:
            lignes = repo_docs.passages_par_ids(c, [t.passage_id for t in trouves])
            cles = dict(c.execute(text("SELECT id, cle FROM assistant.documents WHERE id = ANY(CAST(:ids AS bigint[])) "
                                       "LIMIT 50"), {"ids": [l["document_id"] for l in lignes.values()]}).all())
        ids: list[int] = []
        for t in trouves:
            p = lignes.get(t.passage_id)
            cle = cles.get(p["document_id"]) if p else None
            if cle and cle.startswith(PREFIXE_CLE) and int(cle[len(PREFIXE_CLE):]) not in ids:
                ids.append(int(cle[len(PREFIXE_CLE):]))
        return ids[:limite]


_source = SourceFichesAfi()


def brancher_source(source) -> None:
    """Point d'injection (tests, autre implémentation)."""
    global _source
    _source = source


def connaissances_afi(entree: ConnaissancesAfiEntree, conn: Connection | None = None) -> SortieOutil[ConnaissancesAfiDonnees]:
    avert: list[Avertissement] = []
    ecartees = set(ontologie().fiches_ecartees)
    try:
        ids = [i for i in _source.rechercher(entree.question, entree.limite + len(ecartees)) if i not in ecartees]
    except Exception as exc:             # index ou modèle indisponible : rien d'inventé
        avert.append(Avertissement(code=C.source_indisponible, detail=f"index des fiches AFI : {type(exc).__name__}"))
        ids = []
    ids = ids[:entree.limite]
    with _connexion(conn) as c:
        lignes = repo.connaissances(c, ids) if ids else {}
    fiches = [FicheAfi(fiche=i, question=" ".join(lignes[i]["question"].split()), reponse=lignes[i]["reponse"])
              for i in ids if i in lignes and lignes[i]["actif"]]
    avert.append(Avertissement(code=C.pertinence_non_garantie) if fiches else Avertissement(code=C.aucun_resultat))
    return SortieOutil[ConnaissancesAfiDonnees](
        outil="connaissances_afi", donnees=ConnaissancesAfiDonnees(fiches=fiches),
        provenance=[Provenance(type="sql", table=TABLE, ids=[str(f.fiche) for f in fiches],
                               date_donnees=DATE_INSTANTANE_AFI)] if fiches else [],
        avertissements=avert)
