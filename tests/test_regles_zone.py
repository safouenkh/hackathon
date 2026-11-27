"""Outil regles_zone : graphe -> Qdrant (en mémoire) -> PostgreSQL, avec un encodeur de test déterministe.

Le vrai modèle (BGE-M3) n'est pas chargé ici : un encodeur « sac de mots » suffit à vérifier
l'enchaînement, les filtres (jamais une autre zone) et les avertissements. La qualité de recherche
du vrai modèle se mesure à part (docs/jeu_test_metier.md).
"""
import hashlib
import math
import re

import pytest

qdrant_client = pytest.importorskip("qdrant_client")

from app.db import get_engine  # noqa: E402
from app.processing.regles import regles_zone  # noqa: E402
from app.processing.schemas import CodeAvertissement as C, ReglesZoneEntree  # noqa: E402
from app.repositories.documents import passages_a_indexer  # noqa: E402
from app.semantique import passages  # noqa: E402
from app.semantique.graphe_zones import graphe  # noqa: E402

pytestmark = pytest.mark.usefixtures("base_disponible")
COLLECTION = "test_passages"
KRIB, KORBA = 931803, 932112


class EncodeurTest:
    nom, dimension = "test-sac-de-mots", 64

    @staticmethod
    def _jetons(texte):
        return [int(hashlib.md5(m.encode()).hexdigest()[:6], 16) for m in re.findall(r"\w{3,}", texte.lower())]

    def _vecteur(self, texte):
        jetons = self._jetons(texte)
        dense = [0.0] * self.dimension
        creux: dict[int, float] = {}
        for j in jetons:
            dense[j % self.dimension] += 1.0
            creux[j] = creux.get(j, 0.0) + 1.0
        norme = math.sqrt(sum(x * x for x in dense)) or 1.0
        return passages.VecteurHybride([x / norme for x in dense], creux)

    def passages(self, textes):
        return [self._vecteur(t) for t in textes]

    def requete(self, texte):
        return self._vecteur(texte)


@pytest.fixture(scope="module")
def index():
    client = qdrant_client.QdrantClient(":memory:")
    with get_engine().connect() as c:
        lignes = [p for p in passages_a_indexer(c) if p["zone_id"] in (KRIB, KORBA)]
    assert lignes, "passages d'El Krib et de Korba attendus en base (scripts.importer_cahiers)"
    passages.indexer(client, EncodeurTest(), lignes, COLLECTION)
    return client


def _appel(index, **kw):
    return regles_zone(ReglesZoneEntree(**kw), client=index, enc=EncodeurTest(), graphe=graphe(),
                       collection=COLLECTION)


def _codes(r):
    return {a.code for a in r.avertissements}


def test_passages_du_cahier_de_la_zone_seulement(index):
    r = _appel(index, zone_id=KRIB, question="hauteur maximale des constructions")
    assert r.donnees.cahier.titre.startswith("Cahier des charges : El Krib")
    assert r.donnees.passages and all(p.texte for p in r.donnees.passages)
    with get_engine().connect() as c:
        krib = {p["passage_id"] for p in passages_a_indexer(c) if p["zone_id"] == KRIB}
    assert {p.passage_id for p in r.donnees.passages} <= krib            # jamais un passage de Korba
    assert {C.texte_non_relu, C.pertinence_non_garantie, C.categorie_a_preciser} <= _codes(r)
    assert any(p.table == "assistant.document_chunks" for p in r.provenance)
    assert [p.rang for p in r.donnees.passages] == list(range(1, len(r.donnees.passages) + 1))


def test_categorie_choisie_filtre_les_passages(index):
    r = _appel(index, zone_id=KORBA, question="recul par rapport à la voie", categorie="uib")
    assert C.categorie_a_preciser not in _codes(r)
    assert r.donnees.passages and {p.categorie_sol for p in r.donnees.passages} <= {"UIB", None}


def test_categorie_inconnue_signalee(index):
    r = _appel(index, zone_id=KORBA, question="hauteur", categorie="ZZ")
    assert C.categorie_inconnue in _codes(r) and C.categorie_a_preciser in _codes(r)


def test_zone_sans_cahier_jamais_les_regles_d_une_autre(index):
    r = _appel(index, zone_id=931300, question="hauteur maximale")
    assert r.donnees.cahier is None and r.donnees.passages == []
    assert _codes(r) == {C.cahier_absent}


def test_nom_de_zone_ambigu_demande_laquelle(index):
    r = _appel(index, zone_nom="kef", question="hauteur")
    assert _codes(r) == {C.zone_ambigue} and len(r.balises) >= 2 and all(b.type == "CHOIX" for b in r.balises)


def test_par_lot_et_lot_introuvable(index):
    with get_engine().connect() as c:
        lot = c.exec_driver_sql("SELECT lot_id FROM afi.lots WHERE zone_id = '931803' ORDER BY lot_id LIMIT 1").scalar()
    assert _appel(index, lot_id=lot, question="clôture").donnees.zone.zone_id == KRIB
    assert _codes(_appel(index, lot_id=-1, question="clôture")) == {C.lot_introuvable}


def test_index_indisponible_aucune_reponse_inventee(index):
    class Panne:
        def query_points(self, *a, **k):
            raise ConnectionError("qdrant arrêté")
    r = regles_zone(ReglesZoneEntree(zone_id=KRIB, question="hauteur"), client=Panne(), enc=EncodeurTest(),
                    graphe=graphe())
    assert r.donnees.passages == [] and C.source_indisponible in _codes(r)


def test_une_seule_zone_exigee():
    with pytest.raises(ValueError):
        ReglesZoneEntree(question="hauteur")
    with pytest.raises(ValueError):
        ReglesZoneEntree(question="hauteur", zone_id=KRIB, lot_id=1)
