"""Outil regles_zone : règles du cahier des charges d'une zone, avec leurs sources (BF16, BF17).

Enchaînement : zone (par lot, identifiant ou nom) -> cahier(s) de la zone par SPARQL (graphe RDF)
-> passages les plus proches de la question par Qdrant, FILTRÉS sur ce cahier -> texte exact relu
dans PostgreSQL. Une zone sans cahier reçoit `cahier_absent` : jamais les règles d'une autre zone.
L'outil rend des extraits, pas de réponse rédigée : c'est le LLM qui rédige, en citant l'article.
"""
from __future__ import annotations

from sqlalchemy import Connection

from app.config import get_settings
from app.processing.lots import (
    _PRIX_EXCLUS, _connexion, _zones_par_code, balise_zone, resoudre_zones_par_nom, zone_resume,
)
from app.processing.schemas import (
    Avertissement, Balise, CahierRegles, CodeAvertissement as C, PassageRegle, Provenance, ReglesZoneDonnees,
    ReglesZoneEntree, SortieOutil,
)
from app.repositories import afi as repo_afi
from app.repositories import documents as repo_docs
from app.semantique import graphe_zones, passages


def _sortie(donnees: ReglesZoneDonnees, avert: list[Avertissement], prov: list[Provenance] | None = None,
            balises: list[Balise] | None = None) -> SortieOutil[ReglesZoneDonnees]:
    return SortieOutil[ReglesZoneDonnees](outil="regles_zone", donnees=donnees, provenance=prov or [],
                                          avertissements=avert, balises=balises or [])


def regles_zone(entree: ReglesZoneEntree, conn: Connection | None = None, *, client=None, enc=None,
                graphe=None, collection: str | None = None) -> SortieOutil[ReglesZoneDonnees]:
    avert: list[Avertissement] = []
    vide = ReglesZoneDonnees(zone=None, cahier=None)
    zones_idx = _zones_par_code()

    # 1. La zone
    code: int | None = entree.zone_id
    if entree.lot_id is not None:
        with _connexion(conn) as c:
            lignes = repo_afi.lots_par_ids(c, [entree.lot_id], _PRIX_EXCLUS)
        if not lignes:
            return _sortie(vide, [Avertissement(code=C.lot_introuvable, lot_id=entree.lot_id)])
        if lignes[0].code_zone is None:
            return _sortie(vide, [Avertissement(code=C.lot_orphelin, lot_id=entree.lot_id)])
        code = lignes[0].code_zone
    elif entree.zone_nom is not None:
        trouvees = resoudre_zones_par_nom(entree.zone_nom)
        if not trouvees:
            return _sortie(vide, [Avertissement(code=C.zone_introuvable, detail=entree.zone_nom)])
        if len(trouvees) > 1:
            noms = {z: (zones_idx[z]["zone_libelle_francais"] or "").strip() or str(z) for z in trouvees}
            return _sortie(vide, [Avertissement(code=C.zone_ambigue, detail=",".join(map(str, trouvees)))],
                           balises=[Balise(type="CHOIX", libelle=noms[z]) for z in trouvees[:8]])
        code = trouvees[0]
    if code not in zones_idx:
        return _sortie(vide, [Avertissement(code=C.zone_introuvable, zone_id=code)])
    zone = zone_resume(zones_idx[code])
    balises = [balise_zone(code, zone.nom)]
    prov = [Provenance(type="sql", table="afi.zone_documents", ids=[str(code)])]

    # 2. Le cahier de la zone (graphe RDF, lien venu de afi.zone_documents)
    cahiers = graphe_zones.cahiers_de_zone(code, graphe)
    if not cahiers:
        return _sortie(ReglesZoneDonnees(zone=zone, cahier=None),
                       [Avertissement(code=C.cahier_absent, zone_id=code)], prov, balises)
    categories = sorted({c for ch in cahiers for c in ch.categories})
    categorie = entree.categorie.strip().upper() if entree.categorie else None
    if categorie and categorie not in categories:
        avert.append(Avertissement(code=C.categorie_inconnue, zone_id=code, detail=entree.categorie))
        categorie = None
    if categorie is None and categories:
        avert.append(Avertissement(code=C.categorie_a_preciser, zone_id=code, detail="|".join(categories)))
        balises += [Balise(type="CHOIX", libelle=f"Catégorie {c}") for c in categories]

    # 3. Les passages les plus proches, dans CE cahier seulement
    s = get_settings()
    try:
        trouves = passages.rechercher(
            client if client is not None else passages.client_qdrant(),
            enc if enc is not None else passages.encodeur(), entree.question,
            collection=collection or s.qdrant_collection_passages, document_ids=[ch.document_id for ch in cahiers],
            categorie=categorie, limite=entree.limite)
    except Exception as exc:   # index ou modèle indisponible : jamais de réponse inventée
        avert.append(Avertissement(code=C.source_indisponible, detail=f"index des passages : {type(exc).__name__}"))
        return _sortie(ReglesZoneDonnees(zone=zone, cahier=_cahier(cahiers[0], None)), avert, prov, balises)

    # 4. Le texte exact, relu dans PostgreSQL
    with _connexion(conn) as c:
        lignes = repo_docs.passages_par_ids(c, [t.passage_id for t in trouves]) if trouves else {}
        docs_zone = repo_afi.documents_zone(c, code)
    manquants = [t.passage_id for t in trouves if t.passage_id not in lignes]
    if manquants:
        avert.append(Avertissement(code=C.donnee_incoherente, detail=f"index à reconstruire : {len(manquants)} passage(s)"))
    resultats = []
    for rang, t in enumerate((t for t in trouves if t.passage_id in lignes), 1):
        p = lignes[t.passage_id]
        pages = list(range(p["page_from"], p["page_to"] + 1)) if p["page_from"] else []
        resultats.append(PassageRegle(passage_id=p["passage_id"], texte=p["texte"], article=p["article"],
                                      section=list(p["section"] or []), pages=pages, categorie_sol=p["categorie_sol"],
                                      a_verifier=p["a_verifier"], rang=rang))
        if p["a_verifier"]:
            avert.append(Avertissement(code=C.passage_a_verifier, zone_id=code, detail=p["passage_id"]))
    date_collecte = next(iter(lignes.values()))["retrieved_at"] if lignes else None
    if resultats:
        avert += [Avertissement(code=C.texte_non_relu), Avertissement(code=C.pertinence_non_garantie)]
        prov.append(Provenance(type="document", table="assistant.document_chunks",
                               ids=[r.passage_id for r in resultats], date_donnees=date_collecte))
    else:
        avert.append(Avertissement(code=C.aucun_resultat))

    base = s.afi_documents_base_url.rstrip("/")
    for d in docs_zone:
        if d["type"] == "cahier_charges" and base and d["fichier"]:
            balises.append(Balise(type="PDF", id=f"{base}/{d['fichier']}", libelle=d["nom_original"] or "Cahier des charges"))
    return _sortie(ReglesZoneDonnees(zone=zone, cahier=_cahier(cahiers[0], date_collecte), passages=resultats),
                   avert, prov, balises)


def _cahier(ch: graphe_zones.CahierZone, date_collecte) -> CahierRegles:
    return CahierRegles(document_id=ch.document_id, titre=ch.titre, categories=list(ch.categories),
                        date_collecte=date_collecte)
