"""Outil avantages : organisme compétent et incitations applicables, toujours avec leurs sources.

1. Secteur : code donné, ou reconnu dans l'activité / la question par les synonymes de l'ontologie.
2. Orientation : règles sourcées de assistant.regles_orientation (secteur, coût du projet, investisseur
   étranger). Une condition inconnue (montant, nationalité) n'est jamais supposée : la règle n'est pas
   appliquée et l'avertissement demande l'information. Plusieurs règles qui s'appliquent sont toutes
   rendues : l'outil ne tranche pas ce que la source ne tranche pas.
3. Extraits : passages des pages des organismes retenus (Qdrant, filtré par organisme), texte exact
   relu en base, avec lien et date. Sans index : `source_indisponible`, jamais d'incitation inventée.
"""
from __future__ import annotations

import re
from typing import Protocol

from sqlalchemy import Connection

from app.config import get_settings
from app.processing.lots import _connexion, _zones_par_code
from app.processing.reference import GOUVERNORATS, gouv_id_depuis_nom
from app.processing.schemas import (
    DATE_INSTANTANE_AFI, AvantagesDonnees, AvantagesEntree, Avertissement, CodeAvertissement as C,
    Incitation, OrientationOrganisme, Provenance, SortieOutil,
)
from app.repositories import documents as repo_docs
from app.repositories import orientation as repo_orientation
from app.semantique.ontologie import ontologie


# L'ancien code d'incitation aux investissements (loi n° 93-120) a été remplacé par la loi n° 2016-71 ; les
# pages de l'APIA le citent encore (tableaux « Selon les exigences de la loi n°93-120 », avantages « demeurant
# en vigueur » pour d'anciens projets). Un tel extrait est signalé, jamais présenté comme l'avantage actuel.
_ANCIEN_REGIME = re.compile(r"93\s*-\s*120|code\s+d.incitations?\s+aux\s+investissements", re.I)


def regime_ancien(*textes: str | None) -> bool:
    return any(t and _ANCIEN_REGIME.search(t) for t in textes)


class SourceIncitations(Protocol):
    """Recherche d'extraits dans les pages des organismes (implémentation : Qdrant + PostgreSQL)."""

    def rechercher(self, question: str, organisations: list[str] | None, limite: int = 5) -> list[Incitation]:
        ...


class SourcePassagesOrganismes:
    """Passages des pages des organismes : Qdrant (filtré par organisme) puis texte relu en base."""

    disponible = True

    def __init__(self, client=None, enc=None, collection: str | None = None) -> None:
        self._client, self._enc, self._collection = client, enc, collection

    def rechercher(self, question, organisations, limite=5):
        from app.semantique import passages

        trouves = passages.rechercher(
            self._client or passages.client_qdrant(), self._enc or passages.encodeur(), question,
            collection=self._collection or get_settings().qdrant_collection_passages,
            organisations=organisations, types_document=[repo_docs.TYPES_INDEXES[1]], parties=["contenu"],
            limite=limite)
        with _connexion(None) as c:
            lignes = repo_docs.passages_par_ids(c, [t.passage_id for t in trouves]) if trouves else {}
        res = []
        for t in trouves:
            p = lignes.get(t.passage_id)
            if p is None:
                continue
            res.append(Incitation(intitule=(p["section"] or [p["titre"]])[-1], extrait=p["texte"],
                                  organisme=p["organisation"], url=p["source_url"], document=p["titre"],
                                  page=p["page_from"], date_source=p["retrieved_at"],
                                  # passage, titres, ou page entière annoncée en tête comme relevant de l'ancien code
                                  regime_ancien=regime_ancien(p["texte"], p.get("debut_version"),
                                                              *(p["section"] or []))))
        return res


class SourceIncitationsIndisponible:
    """Source vide (tests, ou index non construit) : ne renvoie jamais de contenu."""

    disponible = False

    def rechercher(self, question, organisations, limite=5) -> list[Incitation]:
        return []


_source: SourceIncitations = SourcePassagesOrganismes()


def brancher_source(source: SourceIncitations) -> None:
    """Point d'injection (tests, autre implémentation)."""
    global _source
    _source = source


def _regles_applicables(regles: list[dict], secteurs: list[str], montant: int | None, etranger: bool | None,
                        avert: list[Avertissement]) -> list[dict]:
    retenues = []
    for r in regles:
        if r["investisseur_etranger"] is not None:
            if etranger is None:
                avert.append(Avertissement(code=C.nationalite_a_preciser, detail=r["organisation"]))
                continue
            if etranger != r["investisseur_etranger"]:
                continue
        if r["secteur"] is not None and r["secteur"] not in secteurs:
            continue
        # « les autres secteurs » : jamais supposé sans secteur connu
        if r["secteurs_exclus"] and (not secteurs or set(r["secteurs_exclus"]) & set(secteurs)):
            continue
        bornes = (r["investissement_min_dt"], r["investissement_max_dt"])
        if any(b is not None for b in bornes):
            if montant is None:
                seuil = next(int(b) for b in bornes if b is not None)
                avert.append(Avertissement(code=C.montant_a_preciser, detail=f"{r['organisation']} : seuil {seuil} DT"))
                continue
            if bornes[0] is not None and montant < bornes[0]:
                continue
            if bornes[1] is not None and montant >= bornes[1]:
                continue
        retenues.append(r)
    return retenues


def _incitations_sicad(texte: str, conn: Connection | None) -> list[Incitation]:
    """Fiches SICAD dont le titre annonce une aide, dans les domaines reconnus dans la demande (ontologie)."""
    from app.processing.demarches_admin import sections
    from app.repositories import demarches as repo_demarches
    from app.semantique.graphe_demarches import documents_d_incitation

    domaines = ontologie().domaines_du_texte(texte)
    docs = documents_d_incitation(domaines) if domaines else []
    if not docs:
        return []
    with _connexion(conn) as c:
        fiches = repo_demarches.fiches(c, docs)
    res = []
    for d in docs:
        f = fiches.get(d)
        if f is None:
            continue
        s = sections(f["full_text"] or "")
        extrait = "\n".join(s.get("conditions", []) + s.get("pieces", [])) or f["titre"]
        res.append(Incitation(intitule=f["titre"], extrait=extrait,
                              organisme=(f["organismes"] or [None])[-1], url=f["url"], document=None, page=None,
                              date_source=f["retrieved_at"], regime_ancien=regime_ancien(f["full_text"])))
    return res


def avantages(entree: AvantagesEntree, conn: Connection | None = None) -> SortieOutil[AvantagesDonnees]:
    avert: list[Avertissement] = []
    if entree.gouvernorat and gouv_id_depuis_nom(entree.gouvernorat) is None:
        avert.append(Avertissement(code=C.gouvernorat_non_reconnu, detail=entree.gouvernorat))
    if entree.zone_id is not None and entree.zone_id not in _zones_par_code():
        avert.append(Avertissement(code=C.zone_introuvable, zone_id=entree.zone_id))

    # 1. Secteur (ontologie)
    onto = ontologie()
    if entree.secteur and entree.secteur in onto.secteurs:
        secteurs = [entree.secteur]
    else:
        secteurs = onto.secteurs_du_texte(" ".join(x for x in (entree.secteur, entree.activite, entree.question) if x))
    if not secteurs:
        avert.append(Avertissement(code=C.secteur_a_preciser, detail=entree.secteur or entree.activite))

    # 2. Orientation (règles sourcées)
    with _connexion(conn) as c:
        regles = repo_orientation.regles_actives(c)
    retenues = _regles_applicables(regles, secteurs, entree.investissement_dt, entree.investisseur_etranger, avert)
    if len({r["organisation"] for r in retenues if r["role"] == "octroi_avantages"}) > 1:
        avert.append(Avertissement(code=C.plusieurs_organismes,
                                   detail="|".join(sorted({r["organisation"] for r in retenues}))))
    orientation = [OrientationOrganisme(organisation=r["organisation"], role=r["role"], citation=r["citation"],
                                        url=r["url"], date_source=r["retrieved_at"]) for r in retenues]

    # 3. Extraits des pages des organismes retenus (tous les organismes si aucune règle ne s'applique)
    organisations = sorted({r["organisation"] for r in retenues}) or None
    question = " ".join(x for x in (entree.question, entree.activite, entree.secteur) if x) or "avantages incitations"
    try:
        incitations = [i for i in _source.rechercher(question, organisations, entree.limite) if i.url or i.document]
    except Exception as exc:   # index ou modèle indisponible : jamais d'incitation inventée
        avert.append(Avertissement(code=C.source_indisponible, detail=f"index des pages : {type(exc).__name__}"))
        incitations = []
    if getattr(_source, "disponible", True) is False:
        avert.append(Avertissement(code=C.source_indisponible, detail="aucune source d'extraits branchée"))
    # Fiches SICAD d'aides (export, dépollution…) quand la demande relève de leur domaine
    try:
        incitations += _incitations_sicad(question, conn)
    except Exception as exc:
        avert.append(Avertissement(code=C.source_indisponible, detail=f"fiches SICAD : {type(exc).__name__}"))
    for url in dict.fromkeys(i.url or i.document for i in incitations if i.regime_ancien):
        avert.append(Avertissement(code=C.regime_ancien, detail=url))
    if incitations:
        avert += [Avertissement(code=C.texte_non_relu), Avertissement(code=C.pertinence_non_garantie)]
    elif not orientation:
        avert.append(Avertissement(code=C.aucun_resultat))

    prov = [Provenance(type="url", url=r["url"], table="assistant.regles_orientation", ids=[str(r["id"])],
                       date_donnees=r["retrieved_at"]) for r in retenues]
    prov += [Provenance(type="url" if i.url else "document", url=i.url, ids=[i.document] if i.document else [],
                        date_donnees=i.date_source) for i in incitations]
    if entree.zone_id is not None:
        prov.append(Provenance(type="sql", table="afi.zones", ids=[str(entree.zone_id)],
                               date_donnees=DATE_INSTANTANE_AFI))
    # zones.zone_devreg (0/1) évoque « zone de développement régional », mais aucune définition
    # n'est confirmée : on ne l'expose pas comme un fait (null) tant que l'AFI ne l'a pas validé.
    return SortieOutil[AvantagesDonnees](
        outil="avantages",
        donnees=AvantagesDonnees(secteurs=secteurs, orientation=orientation, incitations=incitations,
                                 zone_developpement_regional=None),
        provenance=prov, avertissements=avert)
