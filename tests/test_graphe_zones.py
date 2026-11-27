"""Graphe RDF des zones et cahiers (BF16) : construction depuis des lignes, puis sur la vraie base."""
from collections import namedtuple

import pytest
from rdflib import Graph
from rdflib.namespace import RDF

from app.semantique import graphe_zones as gz
from app.semantique.ontologie import AFI, CHEMIN_PAR_DEFAUT

Zone = namedtuple("Zone", "code_zone zone_libelle_francais zone_libelle_arabe")
Cahier = namedtuple("Cahier", "id title zone_id version_id")
Passage = namedtuple("Passage", "id version_id ordinal article categorie_sol")


def _graphe():
    zones = [Zone(931803, "EL KRIB", "الكريب"), Zone(932112, "KORBA", None), Zone(931300, "KASSERINE 2", "")]
    cahiers = [Cahier(1, "Cahier des charges : El Krib (2020)", 931803, 10),
               Cahier(2, "Cahier des charges : Korba (2017)", 932112, 20),
               Cahier(3, "Cahier sans zone", None, 30)]
    passages = [Passage("u1", 10, 0, "1", None), Passage("u2", 10, 1, "2", "A"), Passage("u3", 10, 2, "3", "B"),
                Passage("u4", 20, 0, "1", "UIB"), Passage("u5", 30, 0, None, None)]
    schema = Graph().parse(CHEMIN_PAR_DEFAUT, format="turtle")
    return gz.construire(zones, cahiers, passages, schema)


def test_cahiers_de_zone_avec_categories():
    g = _graphe()
    assert gz.cahiers_de_zone(931803, g) == [gz.CahierZone(1, 10, "Cahier des charges : El Krib (2020)", ("A", "B"))]
    assert gz.cahiers_de_zone(932112, g)[0].categories == ("UIB",)


def test_zone_sans_cahier_et_cahier_sans_zone():
    g = _graphe()
    assert gz.cahiers_de_zone(931300, g) == []              # jamais le cahier d'une autre zone
    assert gz.cahiers_de_zone(999999, g) == []
    assert (None, AFI.aPourCahier, gz.uri_cahier(3)) not in g


def test_categorie_propre_a_chaque_cahier_et_chaine_des_passages():
    g = _graphe()
    assert gz.uri_categorie(1, "A") != gz.uri_categorie(2, "A")
    assert (gz.uri_passage("u1"), AFI.passageSuivant, gz.uri_passage("u2")) in g
    assert (gz.uri_passage("u3"), AFI.passageSuivant, gz.uri_passage("u4")) not in g   # pas d'un cahier à l'autre
    assert (gz.uri_passage("u2"), AFI.concerneCategorie, gz.uri_categorie(1, "A")) in g


def test_le_graphe_ne_contient_ni_texte_ni_prix():
    g = _graphe()
    classes = (AFI.ZoneIndustrielle, AFI.CahierDesCharges, AFI.Passage, AFI.CategorieUsageSol)
    instances = {s for c in classes for s in g.subjects(RDF.type, c)}
    predicats = {p for s, p, _ in g if s in instances}
    assert predicats and not {p for p in predicats
                              if any(m in str(p).lower() for m in ("prix", "texte", "surface", "statut"))}
    assert set(g.subjects(RDF.type, AFI.Passage)) == {gz.uri_passage(i) for i in ("u1", "u2", "u3", "u4", "u5")}


@pytest.mark.usefixtures("base_disponible")
def test_graphe_reel_23_cahiers_relies():
    g = gz.graphe()
    cahiers = set(g.subjects(RDF.type, AFI.CahierDesCharges))
    assert len(cahiers) == 23 and all(any(g.subjects(AFI.aPourCahier, c)) for c in cahiers)
    assert len(set(g.subjects(RDF.type, AFI.Passage))) == 2548
    krib = gz.cahiers_de_zone(931803)
    assert len(krib) == 1 and "El Krib" in krib[0].titre and krib[0].categories == ("A", "B", "C", "D")
