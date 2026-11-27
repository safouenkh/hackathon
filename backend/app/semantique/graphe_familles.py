"""Graphe complet des 9 familles du cahier (§IV.5) et requêtes SPARQL de test (une par famille).

Familles construites ici depuis PostgreSQL et les données de référence sourcées (reference.py) :
- Lieu : gouvernorats (24, codes zones.gouv_id) et rattachement des zones (zones.gouv_id) ;
- Lot : identifiant et zone seulement (lots.lot_id, lots.zone_id) ; un lot orphelin n'a pas de zone ;
- Commodité : 11 types com_id ; une zone est reliée à un type quand afi.zone_commodites donne une distance en km ;
- Incitation : pages des organismes et fiches SICAD dont le TITRE annonce une aide (vocabulaire de l'ontologie) ;
- Organisme -> Secteur : règles sourcées de assistant.regles_orientation (rôle octroi_avantages).
Les autres familles viennent de graphe_zones (zones, cahiers), graphe_demarches (démarches SICAD) et du
fichier d'ontologie (services, secteurs, organismes, schéma Projet). Champs interdits jamais lus.
"""
from __future__ import annotations

from functools import lru_cache

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, RDF, RDFS, SKOS, XSD
from sqlalchemy import Connection, text

from app.db import get_engine
from app.processing.reference import COMMODITES, GOUVERNORATS, GOUVERNORATS_DEDUITS
from app.semantique.graphe_zones import uri_zone
from app.semantique.ontologie import AFI, RESSOURCE, ontologie

LIMITE = 20_000


def uri_gouvernorat(gid: int) -> URIRef:
    return RESSOURCE[f"gouvernorat-{gid}"]


def uri_lot(lot_id: int) -> URIRef:
    return RESSOURCE[f"lot-{lot_id}"]


def uri_commodite(com_id: int) -> URIRef:
    return RESSOURCE[f"commodite-{com_id}"]


def uri_incitation(document_id: int) -> URIRef:
    return RESSOURCE[f"incitation-{document_id}"]


def lire_lignes(conn: Connection) -> dict[str, list]:
    """Lecture seule, LIMIT ; jamais de champ interdit (seulement lot_id et zone_id des lots)."""
    q = lambda sql, **p: conn.execute(text(sql), {"n": LIMITE, **p}).mappings().all()  # noqa: E731
    return {
        "zones": q("SELECT code_zone, gouv_id FROM afi.zones ORDER BY code_zone LIMIT :n"),
        "lots": q("SELECT l.lot_id, l.zone_id, (z.code_zone IS NOT NULL) AS zone_connue FROM afi.lots l "
                  "LEFT JOIN afi.zones z ON z.code_zone::text = l.zone_id ORDER BY l.lot_id LIMIT :n"),
        "proximites": q("SELECT DISTINCT code_zone, com_id FROM afi.zone_commodites "
                        "WHERE zc_unite = 'km' AND code_zone <> 0 ORDER BY 1, 2 LIMIT :n"),
        "documents": q("""
            SELECT d.id, d.title, d.type, so.organisation, so.url, de.organismes
            FROM assistant.documents d JOIN assistant.sources so ON so.id = d.source_id
            LEFT JOIN LATERAL (SELECT v.id FROM assistant.document_versions v WHERE v.document_id = d.id
                               ORDER BY v.retrieved_at DESC NULLS LAST, v.id DESC LIMIT 1) dv ON true
            LEFT JOIN assistant.demarches_externes de ON de.version_id = dv.id
            WHERE d.type IN ('page_organisme', 'fiche_sicad') ORDER BY d.id LIMIT :n"""),
        "regles": q("SELECT organisation, secteur FROM assistant.regles_orientation "
                    "WHERE actif AND role = 'octroi_avantages' AND secteur IS NOT NULL ORDER BY id LIMIT :n"),
    }


def construire(lignes: dict[str, list], schema: Graph) -> Graph:
    g = Graph()
    g += schema
    g.bind("afi", AFI)
    g.bind("id", RESSOURCE)
    onto = ontologie()
    zones_connues = {int(z["code_zone"]) for z in lignes["zones"]}

    for gid, nom in GOUVERNORATS.items():                       # Lieu : gouvernorats
        u = uri_gouvernorat(gid)
        g.add((u, RDF.type, AFI.Gouvernorat))
        g.add((u, AFI.codeGouvernorat, Literal(gid, datatype=XSD.integer)))
        g.add((u, SKOS.prefLabel, Literal(nom, lang="fr")))
        if gid in GOUVERNORATS_DEDUITS:
            g.add((u, AFI.gouvernoratDeduit, Literal(True)))
    for z in lignes["zones"]:
        if z["gouv_id"] in GOUVERNORATS:
            g.add((uri_zone(z["code_zone"]), AFI.dansGouvernorat, uri_gouvernorat(int(z["gouv_id"]))))

    for l in lignes["lots"]:                                    # Lot
        u = uri_lot(l["lot_id"])
        g.add((u, RDF.type, AFI.Lot))
        g.add((u, AFI.identifiantLot, Literal(int(l["lot_id"]), datatype=XSD.integer)))
        if l["zone_connue"]:
            g.add((u, AFI.dansZone, uri_zone(int(l["zone_id"]))))
        else:
            g.add((u, AFI.lotOrphelin, Literal(True)))

    for cid, (_type, libelle, _unites) in COMMODITES.items():   # Commodité
        u = uri_commodite(cid)
        g.add((u, RDF.type, AFI.TypeCommodite))
        g.add((u, AFI.codeCommodite, Literal(cid, datatype=XSD.integer)))
        g.add((u, SKOS.prefLabel, Literal(libelle, lang="fr")))
    for p in lignes["proximites"]:
        if int(p["code_zone"]) in zones_connues and p["com_id"] in COMMODITES:
            g.add((uri_zone(int(p["code_zone"])), AFI.aProximiteDe, uri_commodite(int(p["com_id"]))))

    par_code = {str(c): o for o, c in g.subject_objects(AFI.codeOrganisation)}
    par_nom = {str(n): o for o in g.subjects(RDF.type, AFI.Organisme) for n in g.objects(o, SKOS.prefLabel)}
    for d in lignes["documents"]:                               # Incitation
        if not onto.titre_d_incitation(d["title"]):
            continue
        u = uri_incitation(d["id"])
        g.add((u, RDF.type, AFI.Incitation))
        g.add((u, RDFS.label, Literal(d["title"], lang="fr")))
        g.add((u, AFI.identifiantDocument, Literal(int(d["id"]), datatype=XSD.integer)))
        if d["url"]:
            g.add((u, DCTERMS.source, URIRef(d["url"])))
        organismes = [par_code.get(d["organisation"])] if d["type"] == "page_organisme" else \
            [par_nom.get(n) for n in (d["organismes"] or [])]
        for o in organismes:
            if o is not None:
                g.add((u, AFI.accordeePar, o))

    secteurs = {str(c): s for s, c in g.subject_objects(AFI.codeSecteur)}
    for r in lignes["regles"]:                                  # Organisme -> Secteur
        o, s = par_code.get(r["organisation"]), secteurs.get(r["secteur"])
        if o is not None and s is not None:
            g.add((o, AFI.octroieAvantagesPour, s))
    return g


@lru_cache
def graphe_complet() -> Graph:
    """Ontologie + zones, cahiers, démarches SICAD et familles ci-dessus (construit une fois par processus)."""
    from app.semantique import graphe_demarches, graphe_zones

    g = Graph()
    g += graphe_zones.graphe()
    g += graphe_demarches.graphe()          # contient les organismes SICAD : à lire avant les incitations
    with get_engine().connect() as c:
        lignes = lire_lignes(c)
    return construire(lignes, g)


# ---------------------------------------------------------------------
# Requêtes SPARQL de test : une par famille (cahier : « SPARQL de test répond pour chaque famille »)
# ---------------------------------------------------------------------

_P = """PREFIX afi: <https://example.org/afi/ontology#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
"""
REQUETES_FAMILLES: dict[str, str] = {
    "Lieu": _P + "SELECT ?gouvernorat (COUNT(?zone) AS ?zones) WHERE { ?zone afi:dansGouvernorat ?g . "
                 "?g skos:prefLabel ?gouvernorat } GROUP BY ?gouvernorat",
    "Lot": _P + "SELECT ?lot ?code_zone WHERE { ?l afi:identifiantLot ?lot ; afi:dansZone ?z . "
                "?z afi:codeZone ?code_zone } LIMIT 5",
    "Secteur d'activité": _P + "SELECT ?code ?organisme WHERE { ?s a afi:Secteur ; afi:codeSecteur ?code . "
                               "OPTIONAL { ?o afi:octroieAvantagesPour ?s ; afi:codeOrganisation ?organisme } }",
    "Commodité et proximité": _P + "SELECT ?commodite (COUNT(?zone) AS ?zones) WHERE { ?zone afi:aProximiteDe ?c . "
                                   "?c skos:prefLabel ?commodite } GROUP BY ?commodite",
    "Démarche": _P + "SELECT ?demarche ?domaine WHERE { ?d a afi:DemarcheAdministrative ; rdfs:label ?demarche ; "
                     "afi:dansDomaine ?dom . ?dom afi:libelleSicad ?domaine } LIMIT 5",
    "Incitation": _P + "SELECT ?incitation ?organisme WHERE { ?i a afi:Incitation ; rdfs:label ?incitation ; "
                       "afi:accordeePar ?o . ?o skos:prefLabel ?organisme }",
    "Organisme": _P + "SELECT ?organisme WHERE { ?o a afi:Organisme ; skos:prefLabel ?organisme }",
    "Projet": _P + "SELECT ?propriete WHERE { ?propriete rdfs:domain afi:Projet }",
    "Service de l'AFI": _P + "SELECT ?code WHERE { ?s a afi:ServiceAFI ; afi:code ?code }",
}


def tester_familles(g: Graph | None = None) -> dict[str, int]:
    """Nombre de réponses de la requête de test de chaque famille."""
    g = g if g is not None else graphe_complet()
    return {famille: len(list(g.query(q))) for famille, q in REQUETES_FAMILLES.items()}
