"""Ontologie (ontology/afi_ontology.ttl) : chargement, cohérence avec la base et refus des fichiers mal formés."""
from pathlib import Path

import pytest
from rdflib import Graph

from app.semantique.ontologie import CHEMIN_PAR_DEFAUT, lire


def test_le_fichier_turtle_se_charge_et_couvre_les_8_services():
    assert len(Graph().parse(CHEMIN_PAR_DEFAUT, format="turtle")) > 0      # BNF19 : export Turtle lisible
    o = lire(CHEMIN_PAR_DEFAUT)
    assert len(o.services) == 8 and o.fiche_contact == 26
    assert all(s.synonymes and s.fiches for s in o.services.values())
    assert o.service("acte_precision").fiches_presentation == (20,)
    assert o.service_du_statut("aux_encheres") == "encheres"
    assert o.service("acquisition").exige_statut_lot == "disponible"
    assert "bureau d ordre central" in o.lieu_depot and "frais" in o.frais


def test_service_absent_de_l_ontologie_reste_utilisable():
    s = lire(CHEMIN_PAR_DEFAUT).service("nouveau_service")
    assert s.synonymes == () and s.fiches == () and s.exige_statut_lot is None


@pytest.mark.parametrize("contenu, message", [
    ("afi:x a afi:ServiceAFI .", "sans afi:code"),
    ('afi:x a afi:ServiceAFI ; afi:code "a" . afi:y a afi:ServiceAFI ; afi:code "a" .', "en double"),
])
def test_fichier_incoherent_refuse(tmp_path: Path, contenu, message):
    f = tmp_path / "o.ttl"
    f.write_text("@prefix afi: <https://example.org/afi/ontology#> .\n" + contenu, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        lire(f)


@pytest.mark.usefixtures("base_disponible")
def test_chaque_service_de_la_base_est_dans_l_ontologie():
    from app.db import get_engine
    from app.repositories.assistant import services

    with get_engine().connect() as c:
        codes = {s["code"] for s in services(c)}
    assert codes == set(lire(CHEMIN_PAR_DEFAUT).services)
