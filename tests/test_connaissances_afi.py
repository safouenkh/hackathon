"""Base de connaissances validée par l'AFI (afi.chatbot_connaissances) : import, recherche, outil."""
import pytest

from app.processing.connaissances_afi import SourceFichesAfi, brancher_source
from app.processing.registre import executer
from app.processing.schemas import CodeAvertissement as C
from app.semantique.ontologie import ontologie

pytestmark = pytest.mark.usefixtures("base_disponible")


class _Source:
    disponible = True

    def __init__(self, ids):
        self.ids = ids

    def rechercher(self, question, limite):
        return self.ids[:limite]


@pytest.fixture
def source():
    def brancher(ids):
        brancher_source(_Source(ids))
    yield brancher
    brancher_source(SourceFichesAfi())


def test_fiches_ecartees_lues_dans_l_ontologie():
    assert ontologie().fiches_ecartees == (3, 12)


def test_toutes_les_fiches_actives_sont_cherchables_sauf_les_ecartees():
    from sqlalchemy import text
    from app.db import get_engine
    with get_engine().connect() as c:
        actives = {i for (i,) in c.execute(text("SELECT id FROM afi.chatbot_connaissances WHERE actif = 1 LIMIT 1000"))}
        indexees = {int(k.split(":")[1]) for (k,) in c.execute(text(
            "SELECT cle FROM assistant.documents WHERE type = 'fiche_afi' LIMIT 1000"))}
    assert indexees == actives - {3, 12}


def test_texte_integral_relu_dans_la_table_afi(source):
    source([88])
    r = executer("connaissances_afi", {"question": "délai pour construire après l'achat"})
    f = r.donnees.fiches[0]
    assert f.fiche == 88 and "dans les 18 mois" in f.reponse
    assert r.provenance[0].table == "afi.chatbot_connaissances" and r.provenance[0].ids == ["88"]
    assert [a.code for a in r.avertissements] == [C.pertinence_non_garantie]


def test_fiche_ecartee_jamais_rendue(source):
    source([3, 26])
    r = executer("connaissances_afi", {"question": "contact"})
    assert [f.fiche for f in r.donnees.fiches] == [26]


def test_aucun_resultat(source):
    source([])
    r = executer("connaissances_afi", {"question": "météo de demain"})
    assert r.donnees.fiches == [] and [a.code for a in r.avertissements] == [C.aucun_resultat]


def test_index_indisponible_rien_d_invente():
    class Panne:
        def rechercher(self, *a):
            raise ConnectionError("qdrant")
    brancher_source(Panne())
    try:
        r = executer("connaissances_afi", {"question": "missions de l'AFI"})
    finally:
        brancher_source(SourceFichesAfi())
    assert r.donnees.fiches == [] and C.source_indisponible in [a.code for a in r.avertissements]
