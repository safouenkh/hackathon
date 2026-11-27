"""Corrections sourcées des brouillons (corrections.json), sur une base jetable."""
import json
import shutil
from pathlib import Path

import psycopg
import pytest

from app.sources.corrections import corriger
from app.sources.import_services import importer
from app.sources.publication import publier, revue_markdown
from scripts import migrer

CORPUS = Path(__file__).resolve().parents[1] / "afi-services-markdown"
pytestmark = pytest.mark.skipif(not (CORPUS / "corrections.json").is_file(), reason="corrections.json absent")


@pytest.fixture(scope="module")
def base(base_jetable):
    migrer.appliquer(base_jetable, role_backend=None)
    return base_jetable


@pytest.fixture
def corpus(tmp_path):
    copie = tmp_path / "afi-services-markdown"
    shutil.copytree(CORPUS, copie)
    return copie


from conftest import vider_assistant as _vider  # noqa: E402


@pytest.fixture
def importee(base, corpus):
    _vider(base)
    assert importer(base, corpus, appliquer=True).ok
    yield base
    _vider(base)


def _elements(conninfo, parcours, type_=None):
    with psycopg.connect(conninfo) as c:
        return c.execute("""
            SELECT e.type, e.ordre, e.texte, e.texte_source, e.modifie_par_admin, e.a_verifier, e.note_verification
            FROM assistant.parcours_elements e JOIN assistant.parcours_versions v ON v.id = e.version_id
            JOIN assistant.parcours p ON p.id = v.parcours_id
            WHERE p.code = %(p)s AND (%(t)s::text IS NULL OR e.type = %(t)s) ORDER BY e.type, e.ordre, e.id""",
                         {"p": parcours, "t": type_}).fetchall()


def _etat(conninfo):
    with psycopg.connect(conninfo) as c:
        return (c.execute("SELECT count(*), count(*) FILTER (WHERE modifie_par_admin), "
                          "count(*) FILTER (WHERE a_verifier) FROM assistant.parcours_elements").fetchone(),
                c.execute("SELECT count(*) FROM assistant.sources").fetchone()[0],
                c.execute("SELECT count(*) FROM assistant.document_versions").fetchone()[0])


def _modifier_donnees(corpus, modification):
    chemin = corpus / "corrections.json"
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    modification(donnees)
    chemin.write_text(json.dumps(donnees, ensure_ascii=False), encoding="utf-8")


def test_controle_seul_n_ecrit_rien(importee, corpus):
    avant = _etat(importee)
    r = corriger(importee, corpus, par=None, appliquer=False)
    assert r.ok, r.erreurs
    assert r.faites and _etat(importee) == avant


def test_mainlevee_et_hypotheque_corrigees(importee, corpus):
    r = corriger(importee, corpus, par="Safouen", appliquer=True)
    assert r.ok, r.erreurs
    for parcours in ("main-levee", "insertion-hypotheque"):
        assert not [e for e in _elements(importee, parcours) if "livres explicatifs" in e[2]], parcours
    etape4 = next(e for e in _elements(importee, "insertion-hypotheque", "etape") if e[1] == 4)
    assert "prépare le certificat" in etape4[2]
    assert "livres explicatifs" in etape4[3]                       # le texte d'origine est gardé
    assert etape4[4] and etape4[5] and "non officielle" in etape4[6]
    pieces = _elements(importee, "main-levee", "piece")
    assert len(pieces) == 10
    recu = pieces[-1]
    assert "50 dinars" in recu[2] and recu[3] is None and recu[5]  # ajout : pas de texte d'origine
    assert sum(e[4] for e in _elements(importee, "main-levee")) == 5
    assert sum(e[4] for e in _elements(importee, "insertion-hypotheque")) == 1


def test_le_validateur_est_trace_sur_les_versions_changees(importee, corpus):
    corriger(importee, corpus, par="Safouen", appliquer=True)
    corriger(importee, corpus, par="Safouen", appliquer=True)      # relance : pas de seconde mention
    with psycopg.connect(importee) as c:
        notes = dict(c.execute("SELECT p.code, v.note FROM assistant.parcours_versions v "
                               "JOIN assistant.parcours p ON p.id = v.parcours_id").fetchall())
    assert notes["main-levee"].count("validés par Safouen") == 1
    assert "validés par" not in notes["copie-conforme"]            # rien changé pour ce parcours


def test_signalements_sans_changer_le_texte(importee, corpus):
    corriger(importee, corpus, par="Safouen", appliquer=True)
    etapes = _elements(importee, "acte-precision-contrats-finaux", "etape")
    assert len(etapes) == 5                                        # les étapes restent
    assert [e[5] for e in etapes] == [True, True, True, True, False]
    assert not [e for e in _elements(importee, "acte-precision-contrats-finaux") if e[4]]


def test_chaque_note_cite_sa_preuve_et_les_preuves_sont_en_base(importee, corpus):
    corriger(importee, corpus, par="Safouen", appliquer=True)
    donnees = json.loads((corpus / "corrections.json").read_text(encoding="utf-8"))
    with psycopg.connect(importee) as c:
        notes = [n for (n,) in c.execute("SELECT note_verification FROM assistant.parcours_elements WHERE a_verifier")]
        assert notes and all("https://www.afi.nat.tn/" in n and "«" in n for n in notes)
        for p in donnees["preuves"]:
            assert c.execute("""SELECT count(*) FROM assistant.document_versions dv
                                JOIN assistant.documents d ON d.id = dv.document_id
                                JOIN assistant.sources s ON s.id = d.source_id
                                WHERE s.url = %s AND dv.sha256 = %s""", (p["url"], p["sha256"])).fetchone()[0] == 1


def test_relancer_ne_change_rien(importee, corpus):
    corriger(importee, corpus, par="Safouen", appliquer=True)
    apres = _etat(importee)
    r = corriger(importee, corpus, par="Safouen", appliquer=True)
    assert r.ok and r.faites == [] and r.deja_faites
    assert _etat(importee) == apres


def test_texte_introuvable_n_ecrit_rien(importee, corpus):
    _modifier_donnees(corpus, lambda d: d["corrections"][-1].update(avant="ligne qui n'existe pas"))
    avant = _etat(importee)
    r = corriger(importee, corpus, par="Safouen", appliquer=True)
    assert not r.ok and any("introuvable" in e for e in r.erreurs)
    assert _etat(importee) == avant


def test_modification_de_l_admin_non_ecrasee(importee, corpus):
    with psycopg.connect(importee) as c:
        c.execute("UPDATE assistant.parcours_elements SET texte = 'Texte de l''admin' "
                  "WHERE type = 'etape' AND texte LIKE 'Remise des livres explicatifs%'")
    avant = _etat(importee)
    r = corriger(importee, corpus, par="Safouen", appliquer=True)
    assert not r.ok and any("modifié" in e for e in r.erreurs)
    assert _etat(importee) == avant


def test_version_publiee_non_touchee(importee, corpus):
    with psycopg.connect(importee) as c:
        publier(c, "Safouen", ["main-levee"])
    avant = _etat(importee)
    r = corriger(importee, corpus, par="Safouen", appliquer=True)
    assert not r.ok and any("aucun brouillon" in e for e in r.erreurs)
    assert _etat(importee) == avant


def test_citation_absente_de_la_page_refusee(importee, corpus):
    _modifier_donnees(corpus, lambda d: d["corrections"][0].update(citation="عبارة غير موجودة في الصفحة"))
    r = corriger(importee, corpus, par="Safouen", appliquer=True)
    assert not r.ok and any("citation absente" in e for e in r.erreurs)


def test_preuve_modifiee_refusee(importee, corpus):
    donnees = json.loads((corpus / "corrections.json").read_text(encoding="utf-8"))
    page = corpus / donnees["preuves"][0]["fichier"]
    page.write_bytes(page.read_bytes() + b"<!-- modifie -->")
    r = corriger(importee, corpus, par="Safouen", appliquer=True)
    assert not r.ok and any("SHA-256" in e for e in r.erreurs)


def test_appliquer_exige_un_nom(importee, corpus):
    with pytest.raises(ValueError):
        corriger(importee, corpus, par="  ", appliquer=True)


def test_relecture_montre_corrections_et_notes(importee, corpus):
    corriger(importee, corpus, par="Safouen", appliquer=True)
    with psycopg.connect(importee) as c:
        revue = revue_markdown(c, ["main-levee"])
    assert "✏️ corrigé" in revue and "➕ ajouté" in revue
    assert "Texte d'origine" in revue and "À vérifier :" in revue
