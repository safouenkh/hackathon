"""Tests des migrations du schéma `assistant`, sur une base jetable.

Chaque session crée une base temporaire dans le même serveur PostgreSQL, y applique les
migrations, puis la supprime : la base `dalila` n'est jamais touchée.
"""
import uuid
from pathlib import Path

import psycopg
import pytest

from scripts import migrer

TABLES = {
    "sources", "documents", "document_versions", "ingestion_runs", "services", "parcours",
    "parcours_versions", "parcours_elements", "formulaires", "formulaire_variantes",
    "formulaire_champs", "formulaire_champ_libelles", "parcours_formulaires", "schema_migrations",
    "formulaire_sections", "formulaire_section_libelles", "formulaire_mentions", "demandes", "demande_contacts",
    "besoins_non_couverts",
}


@pytest.fixture(scope="module")
def migree(base_jetable):
    faits = migrer.appliquer(base_jetable, role_backend=None)
    assert faits == [m.chemin.name for m in migrer.lister()]
    return base_jetable


@pytest.fixture
def conn(migree):
    """Connexion dont tout est annulé à la fin du test."""
    with psycopg.connect(migree) as c:
        yield c
        c.rollback()


def _version(conn, statut="brouillon", parcours_code=None):
    sid = conn.execute("INSERT INTO assistant.services (code, nom, ordre) VALUES (%s, 'S', 1) RETURNING id",
                       (f"s_{uuid.uuid4().hex[:8]}",)).fetchone()[0]
    pid = conn.execute("INSERT INTO assistant.parcours (service_id, code, titre, ordre) VALUES (%s, %s, 'P', 1) "
                       "RETURNING id", (sid, parcours_code or f"p-{uuid.uuid4().hex[:8]}")).fetchone()[0]
    vid = conn.execute("INSERT INTO assistant.parcours_versions (parcours_id, numero, origine, cree_par) "
                       "VALUES (%s, 1, 'admin', 'test') RETURNING id", (pid,)).fetchone()[0]
    if statut == "publie":
        _publier(conn, vid)
    return pid, vid


def _publier(conn, vid):
    conn.execute("UPDATE assistant.parcours_versions SET statut = 'publie', publie_par = 'test', "
                 "publie_le = now() WHERE id = %s", (vid,))


def _element(conn, vid, **kw):
    champs = {"type": "etape", "ordre": 1, "texte": "Dépôt de la demande", "texte_source": "Dépôt de la demande"} | kw
    cols = ", ".join(champs)
    marques = ", ".join(["%s"] * len(champs))
    return conn.execute(f"INSERT INTO assistant.parcours_elements (version_id, {cols}) VALUES (%s, {marques}) "
                        "RETURNING id", (vid, *champs.values())).fetchone()[0]


# ---------- Application des migrations ----------

def test_tables_creees_et_aucune_dans_afi(migree):
    with psycopg.connect(migree) as c:
        tables = {r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'assistant'")}
        assert tables == TABLES
        assert c.execute("SELECT count(*) FROM pg_namespace WHERE nspname = 'afi'").fetchone()[0] == 0


def test_aucune_cle_etrangere_vers_afi(migree):
    with psycopg.connect(migree) as c:
        cibles = {r[0] for r in c.execute(
            "SELECT DISTINCT n.nspname FROM pg_constraint k JOIN pg_class t ON t.oid = k.confrelid "
            "JOIN pg_namespace n ON n.oid = t.relnamespace WHERE k.contype = 'f'")}
    assert cibles == {"assistant"}


def test_reapplication_ne_fait_rien(migree):
    assert migrer.appliquer(migree, role_backend=None) == []


def test_migration_modifiee_bloque(migree):
    with psycopg.connect(migree) as c:
        c.execute("UPDATE assistant.schema_migrations SET sha256 = repeat('0', 64) WHERE version = '0001'")
        with pytest.raises(migrer.MigrationModifiee):
            migrer.en_attente(c, migrer.lister())
        c.rollback()


def test_nom_de_migration_invalide_refuse(tmp_path: Path):
    (tmp_path / "1_sans_numero.sql").write_text("SELECT 1", encoding="utf-8")
    with pytest.raises(ValueError):
        migrer.lister(tmp_path)


# ---------- Versions des parcours ----------

def test_une_seule_version_publiee_par_parcours(conn):
    pid, _ = _version(conn, "publie")
    v2 = conn.execute("INSERT INTO assistant.parcours_versions (parcours_id, numero, origine, cree_par) "
                      "VALUES (%s, 2, 'admin', 'test') RETURNING id", (pid,)).fetchone()[0]
    with pytest.raises(psycopg.errors.UniqueViolation):
        _publier(conn, v2)


def test_publier_une_nouvelle_version_apres_archivage(conn):
    pid, v1 = _version(conn, "publie")
    v2 = conn.execute("INSERT INTO assistant.parcours_versions (parcours_id, numero, origine, cree_par) "
                      "VALUES (%s, 2, 'admin', 'test') RETURNING id", (pid,)).fetchone()[0]
    conn.execute("UPDATE assistant.parcours_versions SET statut = 'archive' WHERE id = %s", (v1,))
    _publier(conn, v2)
    statuts = dict(conn.execute("SELECT numero, statut FROM assistant.parcours_versions WHERE parcours_id = %s",
                                (pid,)).fetchall())
    assert statuts == {1: "archive", 2: "publie"}


def test_publication_exige_auteur_et_date(conn):
    _, vid = _version(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE assistant.parcours_versions SET statut = 'publie' WHERE id = %s", (vid,))


def test_import_exige_une_source(conn):
    pid, _ = _version(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO assistant.parcours_versions (parcours_id, numero, origine, cree_par) "
                     "VALUES (%s, 2, 'import', 'test')", (pid,))


@pytest.mark.parametrize("requete", [
    "UPDATE assistant.parcours_elements SET texte = 'autre' WHERE id = %(e)s",
    "DELETE FROM assistant.parcours_elements WHERE id = %(e)s",
    "INSERT INTO assistant.parcours_elements (version_id, type, ordre, texte) VALUES (%(v)s, 'etape', 9, 'x')",
    "UPDATE assistant.parcours_versions SET note = 'x' WHERE id = %(v)s",
    "DELETE FROM assistant.parcours_versions WHERE id = %(v)s",
])
def test_version_publiee_figee(conn, requete):
    _, vid = _version(conn)
    eid = _element(conn, vid)
    _publier(conn, vid)
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(requete, {"e": eid, "v": vid})


def test_version_archivee_figee(conn):
    _, vid = _version(conn, "publie")
    conn.execute("UPDATE assistant.parcours_versions SET statut = 'archive' WHERE id = %s", (vid,))
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("UPDATE assistant.parcours_versions SET statut = 'publie' WHERE id = %s", (vid,))


def test_brouillon_modifiable_et_supprimable(conn):
    _, vid = _version(conn)
    eid = _element(conn, vid)
    conn.execute("UPDATE assistant.parcours_elements SET texte = 'Dépôt (corrigé)' WHERE id = %s", (eid,))
    conn.execute("DELETE FROM assistant.parcours_versions WHERE id = %s", (vid,))
    assert conn.execute("SELECT count(*) FROM assistant.parcours_elements WHERE id = %s", (eid,)).fetchone()[0] == 0


# ---------- Éléments ----------

def test_modification_admin_detectee(conn):
    _, vid = _version(conn)
    e1 = _element(conn, vid, ordre=1)
    e2 = _element(conn, vid, ordre=2, texte="Texte corrigé")
    e3 = _element(conn, vid, ordre=3, texte_source=None, texte="Ajouté par l'admin")
    marque = dict(conn.execute("SELECT id, modifie_par_admin FROM assistant.parcours_elements WHERE version_id = %s",
                               (vid,)).fetchall())
    assert marque == {e1: False, e2: True, e3: True}


def test_montant_reserve_aux_frais(conn):
    _, vid = _version(conn)
    _element(conn, vid, type="frais", montant_dt=15, unite_montant="par copie", texte="15 dinars par copie")
    with pytest.raises(psycopg.errors.CheckViolation):
        _element(conn, vid, type="etape", ordre=2, montant_dt=50)


def test_point_a_verifier_exige_une_note(conn):
    _, vid = _version(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _element(conn, vid, a_verifier=True)


def test_sous_element_dans_la_meme_version(conn):
    _, v1 = _version(conn)
    _, v2 = _version(conn)
    parent = _element(conn, v1, type="condition")
    _element(conn, v1, type="condition", ordre=1, parent_id=parent)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _element(conn, v2, type="condition", ordre=1, parent_id=parent)


def test_doublon_de_position_refuse(conn):
    _, vid = _version(conn)
    _element(conn, vid, ordre=1)
    with pytest.raises(psycopg.errors.UniqueViolation):
        _element(conn, vid, ordre=1)


# ---------- Formulaires et provenance ----------

def test_categorie_de_donnee_controlee(conn):
    fid = conn.execute("INSERT INTO assistant.formulaires (code, titre) VALUES ('demande_test', 'T') "
                       "RETURNING id").fetchone()[0]
    conn.execute("INSERT INTO assistant.formulaire_champs (formulaire_id, code, ordre, type, categorie_donnee) "
                 "VALUES (%s, 'cin', 1, 'texte', 'non_enregistre')", (fid,))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO assistant.formulaire_champs (formulaire_id, code, ordre, type, categorie_donnee) "
                     "VALUES (%s, 'x', 2, 'texte', 'libre')", (fid,))


def test_choix_obligatoires_pour_un_champ_a_choix(conn):
    fid = conn.execute("INSERT INTO assistant.formulaires (code, titre) VALUES ('demande_test2', 'T') "
                       "RETURNING id").fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO assistant.formulaire_champs (formulaire_id, code, ordre, type, categorie_donnee) "
                     "VALUES (%s, 'nature', 1, 'choix_unique', 'projet')", (fid,))


def test_empreinte_sha256_controlee(conn):
    src = conn.execute("INSERT INTO assistant.sources (organisation, title, ingestion_mode) "
                       "VALUES ('AFI', 'Nos services', 'manuel') RETURNING id").fetchone()[0]
    doc = conn.execute("INSERT INTO assistant.documents (source_id, cle, title, type) "
                       "VALUES (%s, 'services/test/fr.md', 'T', 'fiche_service') RETURNING id", (src,)).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO assistant.document_versions (document_id, sha256, media_type) "
                     "VALUES (%s, 'pas-un-hash', 'text/markdown')", (doc,))


def test_role_lecture_lit_sans_ecrire(conn):
    conn.execute("SET ROLE assistant_lecture")
    assert conn.execute("SELECT count(*) FROM assistant.services").fetchone()[0] >= 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("INSERT INTO assistant.services (code, nom, ordre) VALUES ('x', 'x', 1)")
    conn.rollback()
    conn.execute("SET ROLE assistant_lecture")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT count(*) FROM assistant.ingestion_runs")
