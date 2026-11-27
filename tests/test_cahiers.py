"""Import des cahiers des charges et des compléments de zone (paquet GraphRAG), sur une base jetable.

La base jetable reçoit les migrations et un petit schéma `afi` de test (3 zones) : `dalila` n'est
jamais touchée. Le paquet est fabriqué dans un dossier temporaire.
"""
import json
from datetime import date
from pathlib import Path

import psycopg
import pytest

from app.sources import cahiers
from scripts import migrer

RECU = date(2026, 11, 27)

_AFI_TEST = """
CREATE SCHEMA afi;
CREATE TABLE afi.zones (code_zone integer, zone_libelle_francais text, prixunitaire numeric);
CREATE TABLE afi.zone_commodites (code_zone integer, com_id integer, zc_distance numeric, zc_unite text);
CREATE TABLE afi.zone_documents (zone_id integer, type text, fichier text, nom_original text);
INSERT INTO afi.zones VALUES (931803, 'EL KRIB', 0), (932112, 'KORBA', 70), (930207, 'MGHIRA', 50);
INSERT INTO afi.zone_commodites VALUES (932112, 2, 35, 'km'), (932112, 3, 4, 'km');
INSERT INTO afi.zone_documents VALUES
  (931803, 'cahier_charges', 'carte/documents/cahier_charges/931803__cc-elkrib-2020-compressed.pdf',
   'CC-ElKrib-2020_compressed.pdf'),
  (931803, 'plan_lotissement', 'carte/documents/plans/931803__cc-autre-zone.pdf', 'Plan.pdf');
"""


@pytest.fixture(scope="module")
def base(base_jetable):
    migrer.appliquer(base_jetable, role_backend=None)
    with psycopg.connect(base_jetable) as c:
        c.execute(_AFI_TEST)
    return base_jetable


def _chunk(doc, fichier, ordre, **kw):
    return {"chunk_id": f"{doc}-a{ordre:03d}-p1", "doc_id": doc, "doc_title": "Test", "year": 2020,
            "doc_part": "regulation", "land_use": None, "path": ["TITRE I"], "article_number": str(ordre),
            "heading": f"Article {ordre}", "order": ordre, "pages": [], "source_file": fichier,
            "needs_review": False, "review_reasons": [], "text": f"Article {ordre} : hauteur maximale 12 m.",
            "zone_id": None, "embed_text": "ignoré"} | kw


def _paquet(dossier: Path, chunks: list[dict] | None = None, zones: list[dict] | None = None) -> Path:
    (dossier / "sources").mkdir(parents=True)
    (dossier / "vectors").mkdir()
    (dossier / "data").mkdir()
    krib, mghira = "931803__cc-elkrib-2020-compressed.md", "930207__cc-mghira-01-1999.md"
    (dossier / "sources" / krib).write_text("# El Krib\nArticle 1\n", encoding="utf-8")
    (dossier / "sources" / mghira).write_text("# Mghira\nArticle 1\n", encoding="utf-8")
    if chunks is None:
        chunks = [_chunk("931803", krib, 0, pages=[3, 4], land_use="A"), _chunk("931803", krib, 1),
                  _chunk("930207", mghira, 0, doc_part="annex", needs_review=True, review_reasons=["ocr"])]
    (dossier / "vectors" / "chunks.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in chunks), encoding="utf-8")
    if zones is None:
        zones = [{"ZONE_ID": 931803, "ZONE_PRIX": "50", "ZONE_PORT_DIST": "12"},      # AFI vide -> compléments
                 {"ZONE_ID": "932112", "ZONE_PRIX": "90", "ZONE_PORT_DIST": "35",      # prix différent -> écart
                  "ZONE_GARE_DIST": "", "ZONE_PUISSANCE": "abc"},
                 {"ZONE_ID": 999999, "ZONE_PRIX": "10"}]                                # zone inconnue -> ignorée
    (dossier / "data" / "afi_industrial_zones.json").write_text(json.dumps(zones), encoding="utf-8")
    return dossier


def _compter(conninfo, table):
    with psycopg.connect(conninfo) as c:
        return c.execute(f"SELECT count(*) FROM assistant.{table}").fetchone()[0]


def test_controle_n_ecrit_rien(base, tmp_path):
    r = cahiers.importer(base, _paquet(tmp_path / "p"), RECU, appliquer=False)
    assert r.ok, r.erreurs
    assert r.documents == ["930207", "931803"] and r.chunks == 3
    assert _compter(base, "document_chunks") == 0 and _compter(base, "zone_complements") == 0


def test_liens_venus_de_zone_documents_jamais_devines(base, tmp_path):
    r = cahiers.importer(base, _paquet(tmp_path / "p"), RECU)
    # Mghira : la zone 930207 existe, mais l'AFI ne relie aucun cahier à ce fichier -> pas de lien
    assert r.liens == {"931803": 931803, "930207": None}
    assert any("930207" in a and "aucune zone" in a for a in r.avertissements)


def test_complements_seulement_si_afi_vide_et_ecarts_listes(base, tmp_path):
    r = cahiers.importer(base, _paquet(tmp_path / "p"), RECU)
    assert {(c.code_zone, c.champ, c.valeur) for c in r.complements} == {(931803, "prixunitaire", 50.0),
                                                                          (931803, "com_2", 12.0)}
    assert [(e.code_zone, e.champ) for e in r.ecarts] == [(932112, "prixunitaire")]
    assert r.concordance == {"prixunitaire": (0, 1), "com_2": (1, 1)}
    assert any("999999" in a for a in r.avertissements)
    assert any("ZONE_PUISSANCE" in a for a in r.avertissements)


def test_import_puis_reimport_identique(base, tmp_path):
    p = _paquet(tmp_path / "p")
    r = cahiers.importer(base, p, RECU, appliquer=True)
    assert r.ok, r.erreurs
    with psycopg.connect(base) as c:
        lignes = c.execute(
            "SELECT d.zone_id, ch.cle, ch.page_from, ch.page_to, ch.partie, ch.categorie_sol, ch.a_verifier "
            "FROM assistant.document_chunks ch JOIN assistant.document_versions v ON v.id = ch.version_id "
            "JOIN assistant.documents d ON d.id = v.document_id ORDER BY ch.cle").fetchall()
        assert lignes == [(None, "930207-a000-p1", None, None, "annexe", None, True),
                          (931803, "931803-a000-p1", 3, 4, "reglement", "A", False),
                          (931803, "931803-a001-p1", None, None, "reglement", None, False)]
        comp = c.execute("SELECT code_zone, champ, valeur, cle_source FROM assistant.zone_complements "
                         "ORDER BY champ").fetchall()
        assert [(z, ch, float(v), k) for z, ch, v, k in comp] == [(931803, "com_2", 12.0, "ZONE_PORT_DIST"),
                                                                  (931803, "prixunitaire", 50.0, "ZONE_PRIX")]
        assert c.execute("SELECT status FROM assistant.ingestion_runs ORDER BY id DESC LIMIT 1").fetchone()[0] == "reussi"
    r2 = cahiers.importer(base, p, RECU, appliquer=True)
    assert r2.ok and r2.documents == [] and sorted(r2.inchanges) == ["930207", "931803"]
    assert _compter(base, "document_chunks") == 3 and _compter(base, "zone_complements") == 2


def test_passage_invalide_arrete_tout(base, tmp_path):
    krib = "931803__cc-elkrib-2020-compressed.md"
    mauvais = [_chunk("931803", krib, 0), _chunk("931803", krib, 1, text="")]
    avant = _compter(base, "document_chunks")
    r = cahiers.importer(base, _paquet(tmp_path / "p", chunks=mauvais), RECU, appliquer=True)
    assert not r.ok and "ligne 2" in r.erreurs[0]
    assert _compter(base, "document_chunks") == avant


def test_fichier_source_absent_refuse(base, tmp_path):
    r = cahiers.importer(base, _paquet(tmp_path / "p", chunks=[_chunk("931803", "931803__absent.md", 0)]), RECU)
    assert not r.ok and "absent" in r.erreurs[0]


def test_nom_comparable_sans_suffixe_de_compression():
    # Cas réel : l'AFI garde le PDF compressé, le paquet a le nom sans suffixe (Ghezala, zone 930902)
    assert cahiers._nom("carte/documents/cahier_charges/930902__cc-ghazela-2002-compressed.pdf") == \
        cahiers._nom("930902__cc-ghazela-2002.md") == "930902__cc-ghazela-2002"
    assert cahiers._nom("x/930902__cc-ghazela-2003.pdf") != cahiers._nom("930902__cc-ghazela-2002.md")


def test_uuid_de_passage_stable():
    assert cahiers.uuid_passage("a" * 64, "931803-a000-p1") == cahiers.uuid_passage("a" * 64, "931803-a000-p1")
    assert cahiers.uuid_passage("a" * 64, "931803-a000-p1") != cahiers.uuid_passage("b" * 64, "931803-a000-p1")


def test_contraintes_des_complements(base):
    with psycopg.connect(base) as c:
        vid = c.execute("SELECT id FROM assistant.document_versions LIMIT 1").fetchone()
        if vid is None:
            pytest.skip("aucune version : lancer le module entier")
        for champ, valeur in (("com_9", 1), ("prixunitaire", 0)):
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("INSERT INTO assistant.zone_complements (code_zone, champ, valeur, version_id, cle_source) "
                          "VALUES (1, %s, %s, %s, 'X')", (champ, valeur, vid[0]))
            c.rollback()


def test_analyse_en_lecture_seule(base, tmp_path):
    avant = _compter(base, "ingestion_runs")
    r = cahiers.analyser(base, _paquet(tmp_path / "p"))
    assert r.ok and r.liens["931803"] == 931803 and len(r.complements) == 2
    assert r.documents == [] and _compter(base, "ingestion_runs") == avant


def test_revue_markdown_contient_ecarts_et_liens(base, tmp_path):
    r = cahiers.importer(base, _paquet(tmp_path / "p"), RECU)
    md = cahiers.revue_markdown(r)
    assert "| 930207 | **aucune** |" in md and "| 932112 | prix (Dt/m², colonne prixunitaire) | 70 | 90 |" in md
