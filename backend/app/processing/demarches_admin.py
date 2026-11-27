"""Outil demarches_administratives : démarches hors AFI (fiches SICAD) utiles au projet de l'investisseur.

1. Domaines : reconnus dans le besoin et l'activité par les synonymes de l'ontologie
   (famille « Démarche » : domaines SICAD comme Assainissement, Opérations d'importation…).
2. Fiches : graphe RDF (SPARQL fixe) -> documents des domaines reconnus ; recherche hybride Qdrant
   dans ces fiches (toutes les fiches SICAD si aucun domaine n'est reconnu ou si rien n'est trouvé).
3. Texte : relu dans PostgreSQL (dernière version), rendu section par section tel que la fiche le dit.
   Les fiches datent de la collecte du dump AFI : toujours `donnee_non_fraiche`, jamais présentées comme
   à jour. Sans index : `source_indisponible`, jamais de démarche inventée.
"""
from __future__ import annotations

import re

from sqlalchemy import Connection

from app.config import get_settings
from app.processing.avantages import regime_ancien
from app.processing.lots import _connexion
from app.processing.schemas import (
    Avertissement, CodeAvertissement as C, DemarchesAdministrativesDonnees, DemarchesAdministrativesEntree,
    FicheDemarche, Provenance, SortieOutil,
)
from app.repositories import demarches as repo
from app.repositories import documents as repo_docs
from app.semantique.ontologie import ontologie
from app.sources.sicad import TITRES_SECTIONS

TABLE = "assistant.demarches_externes"
_CODE_DU_TITRE = {titre: code for code, titre in TITRES_SECTIONS.items()} | {"Ministères et organismes": "contacts"}
_TITRE = re.compile(r"^##\s+(.*)$")


def sections(markdown: str) -> dict[str, list[str]]:
    """Texte d'une fiche (format de app.sources.sicad) -> lignes par section."""
    res: dict[str, list[str]] = {}
    courant: str | None = None
    for ligne in markdown.splitlines():
        m = _TITRE.match(ligne)
        if m:
            courant = _CODE_DU_TITRE.get(m.group(1).strip())
            continue
        if courant and ligne.strip():
            res.setdefault(courant, []).append(ligne.strip())
    return res


class SourceFichesSicad:
    """Passages des fiches SICAD : Qdrant (type fiche_sicad), puis document et section relus en base."""

    disponible = True

    def __init__(self, client=None, enc=None, collection: str | None = None) -> None:
        self._client, self._enc, self._collection = client, enc, collection

    def rechercher(self, question: str, document_ids: list[int] | None, limite: int) -> list[tuple[int, str | None]]:
        """(document_id, titre de la section la plus proche), par pertinence, sans doublon."""
        from app.semantique import passages

        trouves = passages.rechercher(
            self._client or passages.client_qdrant(), self._enc or passages.encodeur(), question,
            collection=self._collection or get_settings().qdrant_collection_passages,
            document_ids=document_ids, types_document=[repo.TYPE_DOCUMENT], parties=["contenu"],
            limite=limite * 4)
        with _connexion(None) as c:
            lignes = repo_docs.passages_par_ids(c, [t.passage_id for t in trouves]) if trouves else {}
        docs: dict[int, str | None] = {}
        for t in trouves:
            p = lignes.get(t.passage_id)
            if p is not None and p["document_id"] not in docs:
                docs[p["document_id"]] = (p["section"] or [None])[-1]
        return list(docs.items())[:limite]


class SourceFichesIndisponible:
    disponible = False

    def rechercher(self, question, document_ids, limite):
        return []


_source = SourceFichesSicad()


def brancher_source(source) -> None:
    """Point d'injection (tests, autre implémentation)."""
    global _source
    _source = source


def _documents_des_domaines(domaines: list[str]) -> list[int]:
    from app.semantique.graphe_demarches import documents_des_domaines

    return documents_des_domaines(domaines)


def demarches_administratives(entree: DemarchesAdministrativesEntree,
                              conn: Connection | None = None) -> SortieOutil[DemarchesAdministrativesDonnees]:
    avert: list[Avertissement] = []
    texte = " ".join(x for x in (entree.besoin, entree.activite) if x)
    domaines = ontologie().domaines_du_texte(texte)
    trouves: list[tuple[int, str | None]] = []
    try:
        docs = _documents_des_domaines(domaines) if domaines else None
        if docs:
            trouves = _source.rechercher(texte, docs, entree.limite)
        if not trouves:                  # aucun domaine reconnu, ou rien dans ces domaines
            trouves = _source.rechercher(texte, None, entree.limite)
    except Exception as exc:             # index, graphe ou modèle indisponible : jamais de démarche inventée
        avert.append(Avertissement(code=C.source_indisponible, detail=f"fiches SICAD : {type(exc).__name__}"))
    if getattr(_source, "disponible", True) is False:
        avert.append(Avertissement(code=C.source_indisponible, detail="aucune source de fiches branchée"))

    with _connexion(conn) as c:
        lignes = repo.fiches(c, [d for d, _ in trouves])
    fiches: list[FicheDemarche] = []
    for doc, section in trouves:
        l = lignes.get(doc)
        if l is None:
            continue
        s = sections(l["full_text"] or "")
        fiches.append(FicheDemarche(
            titre=l["titre"], type_fiche=l["type_fiche"], organismes=list(l["organismes"] or []),
            secteur=l["secteur"], domaines=list(l["domaines"] or []),
            conditions=s.get("conditions", []), pieces=s.get("pieces", []), etapes=s.get("etapes", []),
            lieu_depot=s.get("lieu_depot", []), lieu_obtention=s.get("lieu_obtention", []),
            delai=s.get("delai", []), references=s.get("references", []), contacts=s.get("contacts", []),
            documents_joints=list(l["documents_joints"] or []), url=l["url"], date_source=l["retrieved_at"],
            section_pertinente=section, regime_ancien=bool(regime_ancien(l["full_text"]))))

    if fiches:
        dates = sorted({str(f.date_source) for f in fiches if f.date_source})
        avert.append(Avertissement(code=C.donnee_non_fraiche, detail=f"fiches SICAD collectées le {', '.join(dates)}"))
        avert += [Avertissement(code=C.texte_non_relu), Avertissement(code=C.pertinence_non_garantie)]
        avert += [Avertissement(code=C.regime_ancien, detail=f.url) for f in fiches if f.regime_ancien]
    else:
        avert.append(Avertissement(code=C.aucun_resultat))
    prov = [Provenance(type="url", url=l["url"], table=TABLE, ids=[str(l["version_id"])],
                       date_donnees=l["retrieved_at"]) for d, _ in trouves if (l := lignes.get(d))]
    prov += [Provenance(type="sql", table="afi.chatbot_sources", ids=[str(l["id_source"])],
                        date_donnees=l["retrieved_at"]) for d, _ in trouves if (l := lignes.get(d)) and l["id_source"]]
    return SortieOutil[DemarchesAdministrativesDonnees](
        outil="demarches_administratives",
        donnees=DemarchesAdministrativesDonnees(domaines_reconnus=domaines, fiches=fiches),
        provenance=prov, avertissements=avert)
