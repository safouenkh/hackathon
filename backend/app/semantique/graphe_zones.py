"""Graphe RDF des zones et de leurs cahiers des charges (cahier BF16), construit depuis PostgreSQL.

- Schéma : ontology/afi_ontology.ttl (classes ZoneIndustrielle, CahierDesCharges, Passage,
  CategorieUsageSol). Instances : lues dans `afi.zones`, `assistant.documents` et
  `assistant.document_chunks`. Rien n'est écrit à la main dans ce module.
- Le graphe ne garde que des identifiants et des relations stables : le texte des passages reste
  dans PostgreSQL (et dans Qdrant), les prix et statuts restent en SQL.
- Les requêtes SPARQL sont fixes et paramétrées (`initBindings`) : jamais de SPARQL venu du LLM.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD
from sqlalchemy import Connection, text

from app.db import get_engine
from app.semantique.ontologie import AFI, CHEMIN_PAR_DEFAUT, RESSOURCE
from app.config import get_settings

LIMITE = 20_000


def uri_zone(code_zone: int) -> URIRef:
    return RESSOURCE[f"zone-{code_zone}"]


def uri_cahier(document_id: int) -> URIRef:
    return RESSOURCE[f"cahier-{document_id}"]


def uri_passage(chunk_id: str) -> URIRef:
    return RESSOURCE[f"passage-{chunk_id}"]


def uri_categorie(document_id: int, code: str) -> URIRef:
    return RESSOURCE[f"categorie-{document_id}-{code}"]


def lire_lignes(conn: Connection) -> tuple[list, list, list]:
    """(zones, cahiers à leur dernière version, passages de ces versions) : lecture seule, LIMIT."""
    zones = conn.execute(text(
        "SELECT code_zone, zone_libelle_francais, zone_libelle_arabe FROM afi.zones ORDER BY code_zone LIMIT :n"
    ), {"n": LIMITE}).all()
    cahiers = conn.execute(text("""
        SELECT DISTINCT ON (d.id) d.id, d.title, d.zone_id, v.id AS version_id
        FROM assistant.documents d JOIN assistant.document_versions v ON v.document_id = d.id
        WHERE d.type = 'cahier_charges'
        ORDER BY d.id, v.id DESC
        LIMIT :n"""), {"n": LIMITE}).all()
    passages = conn.execute(text("""
        SELECT c.id::text AS id, c.version_id, c.ordinal, c.article, c.categorie_sol
        FROM assistant.document_chunks c
        WHERE c.version_id = ANY(CAST(:versions AS bigint[]))
        ORDER BY c.version_id, c.ordinal
        LIMIT :n"""), {"versions": [c.version_id for c in cahiers], "n": LIMITE}).all()
    return zones, cahiers, passages


def construire(zones, cahiers, passages, schema: Graph | None = None) -> Graph:
    """Graphe = schéma de l'ontologie + instances lues en base."""
    g = Graph()
    if schema is not None:
        g += schema
    g.bind("afi", AFI)
    g.bind("id", RESSOURCE)
    for z in zones:
        u = uri_zone(z.code_zone)
        g.add((u, RDF.type, AFI.ZoneIndustrielle))
        g.add((u, AFI.codeZone, Literal(int(z.code_zone), datatype=XSD.integer)))
        for nom, langue in ((z.zone_libelle_francais, "fr"), (z.zone_libelle_arabe, "ar")):
            if nom and nom.strip():
                g.add((u, RDFS.label, Literal(nom.strip(), lang=langue)))
    par_version = {}
    for c in cahiers:
        u = uri_cahier(c.id)
        par_version[c.version_id] = c.id
        g.add((u, RDF.type, AFI.CahierDesCharges))
        g.add((u, RDFS.label, Literal(c.title, lang="fr")))
        g.add((u, AFI.identifiantDocument, Literal(int(c.id), datatype=XSD.integer)))
        g.add((u, AFI.identifiantVersion, Literal(int(c.version_id), datatype=XSD.integer)))
        if c.zone_id is not None:
            g.add((uri_zone(c.zone_id), AFI.aPourCahier, u))
    precedent: dict[int, URIRef] = {}
    for p in passages:
        doc = par_version[p.version_id]
        u = uri_passage(p.id)
        g.add((u, RDF.type, AFI.Passage))
        g.add((u, AFI.identifiantPassage, Literal(p.id)))
        g.add((uri_cahier(doc), AFI.aPourPassage, u))
        if p.article:
            g.add((u, AFI.numeroArticle, Literal(p.article)))
        if p.categorie_sol:
            cat = uri_categorie(doc, p.categorie_sol)
            g.add((cat, RDF.type, AFI.CategorieUsageSol))
            g.add((cat, AFI.codeCategorie, Literal(p.categorie_sol)))
            g.add((uri_cahier(doc), AFI.definitCategorie, cat))
            g.add((u, AFI.concerneCategorie, cat))
        if p.version_id in precedent:
            g.add((precedent[p.version_id], AFI.passageSuivant, u))
        precedent[p.version_id] = u
    return g


def _schema() -> Graph:
    s = Graph()
    s.parse(get_settings().ontologie_path or str(CHEMIN_PAR_DEFAUT), format="turtle")
    return s


@lru_cache
def graphe() -> Graph:
    """Graphe construit une fois par processus (≈ 185 zones, 23 cahiers, 2 548 passages)."""
    with get_engine().connect() as c:
        zones, cahiers, passages = lire_lignes(c)
    return construire(zones, cahiers, passages, _schema())


# ---------------------------------------------------------------------
# Requêtes SPARQL fixes
# ---------------------------------------------------------------------

_CAHIERS_DE_ZONE = """
PREFIX afi: <https://example.org/afi/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?doc ?version ?titre ?code
WHERE {
  ?zone afi:codeZone ?code_zone ; afi:aPourCahier ?cahier .
  ?cahier afi:identifiantDocument ?doc ; afi:identifiantVersion ?version ; rdfs:label ?titre .
  OPTIONAL { ?cahier afi:definitCategorie ?cat . ?cat afi:codeCategorie ?code }
}
"""
# (GROUP_CONCAT sur une variable OPTIONAL non liée échoue avec RDFLib 7.6 : regroupement en Python.)


@dataclass(frozen=True)
class CahierZone:
    document_id: int
    version_id: int
    titre: str
    categories: tuple[str, ...]          # codes d'usage du sol définis par ce cahier


def cahiers_de_zone(code_zone: int, g: Graph | None = None) -> list[CahierZone]:
    """Cahiers des charges reliés à la zone (SPARQL), avec les catégories qu'ils définissent."""
    g = g if g is not None else graphe()
    res = g.query(_CAHIERS_DE_ZONE, initBindings={"code_zone": Literal(int(code_zone), datatype=XSD.integer)})
    par_doc: dict[tuple[int, int, str], set[str]] = {}
    for r in res:
        codes = par_doc.setdefault((int(r.doc), int(r.version), str(r.titre)), set())
        if r.code is not None:
            codes.add(str(r.code))
    return [CahierZone(d, v, t, tuple(sorted(c))) for (d, v, t), c in sorted(par_doc.items())]
