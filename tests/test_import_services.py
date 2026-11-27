"""Lecture des fiches de services (corpus réel) et import en base (base jetable)."""
import json
import re
import shutil
from pathlib import Path

import psycopg
import pytest

from app.sources.fiche_service import SECTIONS, lire
from app.sources.import_services import importer
from app.sources.publication import brouillons, publier, revue_markdown
from scripts import migrer

CORPUS = Path(__file__).resolve().parents[1] / "afi-services-markdown"
FICHES = sorted(CORPUS.glob("data/documents/services/*/fr.md"))
pytestmark = pytest.mark.skipif(not FICHES, reason="corpus afi-services-markdown absent")


def _fiche(nom: str):
    return lire((CORPUS / f"data/documents/services/{nom}/fr.md").read_text(encoding="utf-8"))


# ---------- Lecture ----------

def test_les_neuf_fiches_sont_valides():
    assert len(FICHES) == 9
    for f in FICHES:
        fiche = lire(f.read_text(encoding="utf-8"))
        assert fiche.valide, (f, fiche.erreurs)


@pytest.mark.parametrize("chemin", FICHES, ids=lambda p: p.parent.name)
def test_chaque_ligne_de_contenu_devient_un_element(chemin):
    """Aucun texte perdu : chaque ligne de contenu se retrouve, telle quelle, dans un élément."""
    texte = chemin.read_text(encoding="utf-8")
    fiche = lire(texte)
    corps = texte.split("---", 2)[2]
    lignes = [l.strip() for l in corps.splitlines()
              if l.strip() and not l.lstrip().startswith("#") and l.strip() != "null"]
    textes = [e.texte for e in fiche.tous() if e.type != "frais"]
    assert len(lignes) == len(textes)
    for ligne, element in zip(lignes, textes):
        assert ligne.endswith(element), (ligne, element)


def test_imbrication_a_deux_niveaux():
    etape1 = next(e for e in _fiche("acquisition-littoral-grand-tunis").elements if e.type == "etape")
    assert etape1.titre == "Dépôt de la demande"
    assert [len(c.enfants) for c in etape1.enfants] == [3, 0]
    assert etape1.enfants[0].enfants[0].texte.startswith("Au bureau d’accueil")


def test_groupes_et_numerotation_conservee():
    pieces = [e for e in _fiche("acquisition-developpement-regional").elements if e.type == "piece"]
    assert [sum(p.groupe == g for p in pieces) for g in
            ("I – Phase de réservation :", "II – Phase d’attribution :", "III – Phase de paiement :")] == [5, 4, 4]
    acte = [e.texte for e in _fiche("acte-precision-contrats-finaux").elements if e.type == "piece"]
    assert acte[1].startswith("2. Remplissage du [formulaire")       # numérotation atypique gardée
    assert acte[7].startswith("7. Une déclaration")                  # « 7. » répété dans la source


def test_montants_cites():
    def frais(nom):
        return [(e.montant_dt, e.unite_montant) for e in _fiche(nom).elements if e.type == "frais"]
    assert frais("copie-conforme") == [(15.0, "par copie")]
    assert frais("situation-fonciere") == [(50.0, None)]
    assert frais("acte-precision-contrats-finaux") == [(150.0, None)]
    assert frais("vente-encheres-publiques") == []                   # seulement des pourcentages


def test_liens_et_sections_vides():
    fiche = _fiche("copie-conforme")
    lien = next(e for e in fiche.elements if e.type == "lien")
    assert lien.url.startswith("https://www.afi.nat.tn/docs/")
    assert "section vide (null) : description" in fiche.avertissements
    assert not [e for e in fiche.elements if e.type in ("description", "pour_qui", "condition")]


def test_section_inconnue_refusee():
    md = "---\nservice: X\nsource_url: https://x\nlanguage: fr\n---\n# X\n## Tarifs secrets\n1. Rien\n"
    assert "section inconnue : « Tarifs secrets »" in lire(md).erreurs


def test_metadonnees_obligatoires():
    md = "---\nservice: X\n---\n# X\n## Étapes\n1. Faire\n"
    assert set(lire(md).erreurs) == {"métadonnée obligatoire absente : source_url",
                                     "métadonnée obligatoire absente : language"}


def test_sections_reconnues():
    assert set(SECTIONS.values()) == {"description", "pour_qui", "condition", "etape", "piece", "lien"}


# ---------- Import (base jetable) ----------

@pytest.fixture(scope="module")
def base(base_jetable):
    migrer.appliquer(base_jetable, role_backend=None)
    return base_jetable


@pytest.fixture
def corpus(tmp_path):
    copie = tmp_path / "afi-services-markdown"
    shutil.copytree(CORPUS, copie)
    return copie


def _compter(conn, table, condition="true"):
    return conn.execute(f"SELECT count(*) FROM assistant.{table} WHERE {condition}").fetchone()[0]


from conftest import vider_assistant as _vider  # noqa: E402


@pytest.fixture
def vide(base):
    _vider(base)
    yield base
    _vider(base)


def test_controle_seul_n_ecrit_rien(vide, corpus):
    r = importer(vide, corpus, appliquer=False)
    assert r.ok and len(r.fiches) == 9
    with psycopg.connect(vide) as c:
        assert _compter(c, "services") == 0 and _compter(c, "ingestion_runs") == 0


def test_import_complet(vide, corpus):
    r = importer(vide, corpus, appliquer=True)
    assert r.ok, r.erreurs
    attendu_elements = sum(sum(f.fiche.compter().values()) for f in r.fiches)
    with psycopg.connect(vide) as c:
        assert _compter(c, "services") == 8
        assert _compter(c, "parcours") == 9
        assert _compter(c, "parcours_versions", "statut = 'brouillon' AND origine = 'import'") == 9
        assert _compter(c, "parcours_versions", "statut <> 'brouillon'") == 0          # rien de publié
        assert _compter(c, "parcours_elements") == attendu_elements
        assert _compter(c, "parcours_elements", "modifie_par_admin") == 0
        assert _compter(c, "formulaires") == 2 and _compter(c, "formulaire_variantes") == 3
        assert _compter(c, "parcours_formulaires") == 8
        assert _compter(c, "parcours_formulaires", "a_verifier") == 5   # 2 acquisitions, sit. foncière, mainlevée, copie
        assert _compter(c, "ingestion_runs", "status = 'reussi'") == 1
        # Provenance : chaque version importée pointe vers le fichier et son empreinte
        sans_source = _compter(c, "parcours_versions", "document_version_id IS NULL")
        assert sans_source == 0
        sha = c.execute("""SELECT dv.sha256 FROM assistant.document_versions dv
                           JOIN assistant.documents d ON d.id = dv.document_id
                           WHERE d.cle = 'data/documents/services/copie-conforme/fr.md'""").fetchone()[0]
        manifeste = {m["path"]: m["sha256"] for m in json.loads((CORPUS / "manifest.json").read_text("utf-8"))}
        assert sha == manifeste["data/documents/services/copie-conforme/fr.md"]
        # Liens hiérarchiques conservés : 3 sous-sous-étapes sous l'étape 1 du littoral
        assert c.execute("""SELECT count(*) FROM assistant.parcours_elements g
                            JOIN assistant.parcours_elements e ON e.id = g.parent_id
                            JOIN assistant.parcours_elements r ON r.id = e.parent_id
                            JOIN assistant.parcours_versions v ON v.id = r.version_id
                            JOIN assistant.parcours p ON p.id = v.parcours_id
                            WHERE p.code = 'acquisition-littoral-grand-tunis' AND r.type = 'etape' AND r.ordre = 1
                         """).fetchone()[0] == 3


def test_reimport_sans_changement(vide, corpus):
    importer(vide, corpus, appliquer=True)
    r = importer(vide, corpus, appliquer=True)
    assert r.ok and r.versions_creees == [] and len(r.inchangees) == 9
    with psycopg.connect(vide) as c:
        assert _compter(c, "parcours_versions") == 9


def test_fiche_modifiee_nouveau_brouillon_seulement_pour_elle(vide, corpus):
    importer(vide, corpus, appliquer=True)
    f = corpus / "data/documents/services/copie-conforme/fr.md"
    f.write_text(f.read_text(encoding="utf-8").replace("(15 dinars par copie)", "(20 dinars par copie)"),
                 encoding="utf-8")
    r = importer(vide, corpus, appliquer=True)
    assert r.versions_creees == ["copie-conforme"]
    assert any("manifest.json" in a for a in r.avertissements)
    with psycopg.connect(vide) as c:
        assert c.execute("""SELECT array_agg(v.numero ORDER BY v.numero) FROM assistant.parcours_versions v
                            JOIN assistant.parcours p ON p.id = v.parcours_id
                            WHERE p.code = 'copie-conforme'""").fetchone()[0] == [1, 2]


def test_erreur_n_ecrit_rien_mais_est_journalisee(vide, corpus):
    f = corpus / "data/documents/services/main-levee/fr.md"
    f.write_text(f.read_text(encoding="utf-8").replace("## Étapes", "## Étapes cachées"), encoding="utf-8")
    r = importer(vide, corpus, appliquer=True)
    assert not r.ok and any("section inconnue" in e for e in r.erreurs)
    with psycopg.connect(vide) as c:
        assert _compter(c, "services") == 0 and _compter(c, "parcours_versions") == 0
        assert _compter(c, "ingestion_runs", "status = 'echec' AND error LIKE '%main-levee%'") == 1


def test_changement_de_l_admin_conserve(vide, corpus):
    importer(vide, corpus, appliquer=True)
    with psycopg.connect(vide) as c:
        c.execute("UPDATE assistant.services SET nom = 'Copie certifiée' WHERE code = 'copie_conforme'")
    r = importer(vide, corpus, appliquer=True)
    assert any("Copie certifiée" in a for a in r.avertissements)
    with psycopg.connect(vide) as c:
        assert c.execute("SELECT nom FROM assistant.services WHERE code = 'copie_conforme'").fetchone()[0] \
            == "Copie certifiée"


def test_relecture_puis_publication(vide, corpus):
    importer(vide, corpus, appliquer=True)
    with psycopg.connect(vide) as c:
        revue = revue_markdown(c, ["copie-conforme"])
        assert "15 DT par copie" in revue and "À vérifier" in revue
        assert len(brouillons(c)) == 9
        with pytest.raises(ValueError):
            publier(c, "  ", ["copie-conforme"])
        faits = publier(c, "Safouen", ["copie-conforme"])
        assert [b.parcours for b in faits] == ["copie-conforme"]
        assert _compter(c, "parcours_versions", "statut = 'publie' AND publie_par = 'Safouen'") == 1
        c.commit()
    # Nouvelle fiche : nouveau brouillon v2, la v1 publiée reste intacte
    f = corpus / "data/documents/services/copie-conforme/fr.md"
    f.write_text(f.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    importer(vide, corpus, appliquer=True)
    with psycopg.connect(vide) as c:
        etats = c.execute("""SELECT v.numero, v.statut FROM assistant.parcours_versions v
                             JOIN assistant.parcours p ON p.id = v.parcours_id
                             WHERE p.code = 'copie-conforme' ORDER BY v.numero""").fetchall()
        assert etats == [(1, "publie"), (2, "brouillon")]
        publier(c, "Safouen", ["copie-conforme"])
        c.commit()
        etats = c.execute("""SELECT v.numero, v.statut FROM assistant.parcours_versions v
                             JOIN assistant.parcours p ON p.id = v.parcours_id
                             WHERE p.code = 'copie-conforme' ORDER BY v.numero""").fetchall()
        assert etats == [(1, "archive"), (2, "publie")]


def test_aucune_donnee_personnelle_dans_le_catalogue():
    texte = (CORPUS / "catalogue.json").read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", texte)          # pas d'adresse e-mail
