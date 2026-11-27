"""Graphe RDF des démarches administratives (famille « Démarche », fiches SICAD), construit depuis PostgreSQL.

- Schéma et vocabulaire : ontology/afi_ontology.ttl (DemarcheAdministrative, DomaineDemarche,
  Organisme, relevePar, dansDomaine). Instances : assistant.demarches_externes (rien à la main ici).
- Un domaine de la fiche est relié au concept de l'ontologie qui porte le même libellé SICAD
  (sans accents ni casse) ; un libellé inconnu de l'ontologie devient un domaine sans synonyme.
- Les organismes sont ceux que la fiche cite, jamais déduits.
- Requêtes SPARQL fixes et paramétrées (initBindings) : jamais de SPARQL venu du LLM.
"""
from __future__ import annotations

import hashlib
from functools import lru_cache

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS, XSD

from app.db import get_engine
from app.processing.reference import normaliser
from app.repositories import demarches as repo
from app.semantique.ontologie import AFI, RESSOURCE
from app.semantique.graphe_zones import _schema


def uri_demarche(document_id: int) -> URIRef:
    return RESSOURCE[f"demarche-{document_id}"]


def _uri_nom(prefixe: str, nom: str) -> URIRef:
    return RESSOURCE[f"{prefixe}-{hashlib.sha1(normaliser(nom).encode('utf-8')).hexdigest()[:12]}"]


def construire(lignes: list[dict], schema: Graph | None = None) -> Graph:
    g = Graph()
    if schema is not None:
        g += schema
    g.bind("afi", AFI)
    g.bind("id", RESSOURCE)
    domaines = {normaliser(str(lib)): dom for dom, lib in g.subject_objects(AFI.libelleSicad)}
    organismes = {normaliser(str(nom)): o for o in g.subjects(RDF.type, AFI.Organisme)
                  for nom in g.objects(o, SKOS.prefLabel)}
    for l in lignes:
        u = uri_demarche(l["document_id"])
        g.add((u, RDF.type, AFI.DemarcheAdministrative))
        g.add((u, RDFS.label, Literal(l["titre"], lang="fr")))
        g.add((u, AFI.typeFiche, Literal(l["type_fiche"])))
        g.add((u, AFI.identifiantDocument, Literal(int(l["document_id"]), datatype=XSD.integer)))
        g.add((u, AFI.identifiantVersion, Literal(int(l["version_id"]), datatype=XSD.integer)))
        if l["url"]:
            g.add((u, DCTERMS.source, URIRef(l["url"])))
        if l["secteur"]:
            g.add((u, AFI.secteurSicad, Literal(l["secteur"])))
        for nom in l["organismes"] or []:
            o = organismes.get(normaliser(nom))
            if o is None:
                o = organismes[normaliser(nom)] = _uri_nom("organisme", nom)
                g.add((o, RDF.type, AFI.Organisme))
                g.add((o, SKOS.prefLabel, Literal(nom, lang="fr")))
            g.add((u, AFI.relevePar, o))
        for lib in l["domaines"] or []:
            d = domaines.get(normaliser(lib))
            if d is None:
                d = domaines[normaliser(lib)] = _uri_nom("domaine", lib)
                g.add((d, RDF.type, AFI.DomaineDemarche))
                g.add((d, AFI.libelleSicad, Literal(lib)))
            g.add((u, AFI.dansDomaine, d))
    return g


@lru_cache
def graphe() -> Graph:
    """Graphe construit une fois par processus (≈ 127 fiches SICAD)."""
    with get_engine().connect() as c:
        lignes = repo.demarches(c)
    return construire(lignes, _schema())


_DEMARCHES_DU_DOMAINE = """
PREFIX afi: <https://example.org/afi/ontology#>
SELECT DISTINCT ?doc
WHERE {
  ?dom afi:libelleSicad ?libelle .
  ?d a afi:DemarcheAdministrative ; afi:dansDomaine ?dom ; afi:identifiantDocument ?doc .
}
"""


def documents_des_domaines(libelles: list[str], g: Graph | None = None) -> list[int]:
    """Documents des fiches rangées dans ces domaines SICAD (libellés exacts de l'ontologie)."""
    g = g if g is not None else graphe()
    docs: set[int] = set()
    for lib in libelles:
        docs |= {int(r.doc) for r in g.query(_DEMARCHES_DU_DOMAINE, initBindings={"libelle": Literal(lib)})}
    return sorted(docs)


_DEMARCHES_DU_DOMAINE_TITRES = """
PREFIX afi: <https://example.org/afi/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?doc ?titre
WHERE {
  ?dom afi:libelleSicad ?libelle .
  ?d a afi:DemarcheAdministrative ; afi:dansDomaine ?dom ; afi:identifiantDocument ?doc ; rdfs:label ?titre .
}
"""


def documents_d_incitation(libelles: list[str], g: Graph | None = None) -> list[int]:
    """Fiches de ces domaines dont le titre annonce une aide (vocabulaire id:incitation-demarche)."""
    from app.semantique.ontologie import ontologie

    g = g if g is not None else graphe()
    onto = ontologie()
    docs: set[int] = set()
    for lib in libelles:
        docs |= {int(r.doc) for r in g.query(_DEMARCHES_DU_DOMAINE_TITRES, initBindings={"libelle": Literal(lib)})
                 if onto.titre_d_incitation(str(r.titre))}
    return sorted(docs)
