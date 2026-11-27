"""Champs des formulaires officiels : fidélité aux PDF, contrôle du fichier, import, et garanties
de la migration 0002 (catégories des valeurs, rôle d'écriture). Base jetable : `dalila` n'est pas touchée."""
import json
import shutil
import unicodedata
from functools import lru_cache
from pathlib import Path

import psycopg
import pytest
from pypdf import PdfReader

from app.sources import formulaires as fo
from app.sources.import_services import importer as importer_services
from scripts import migrer

CORPUS = Path(__file__).resolve().parents[1] / "afi-services-markdown"
DONNEES = json.loads((CORPUS / fo.FICHIER).read_text(encoding="utf-8"))


def _norm(t: str) -> str:
    """Lettres et chiffres seulement. Le texte des PDF inverse parfois la ligature arabe lam-alif
    (« الامكان » extrait « االمكان ») : les alifs sont retirés des deux côtés (règle caractère par
    caractère, indépendante du texte voisin)."""
    return "".join(c for c in unicodedata.normalize("NFKC", t).casefold() if c.isalnum() and c not in "اأإآ")


@lru_cache
def _page(fichier: str, page: int) -> str:
    return _norm(PdfReader(CORPUS / fichier).pages[page - 1].extract_text())


def _textes_pdf():
    cat = json.loads((CORPUS / "catalogue.json").read_text(encoding="utf-8"))
    fichiers = {(f["code"], v["langue"]): v["fichier"] for f in cat["formulaires"] for v in f["variantes"]}
    for f in DONNEES["formulaires"]:
        for s in f["sections"]:
            for langue, l in s["libelles"].items():
                yield f["code"], langue, l, l["texte"], fichiers
        for c in f["champs"]:
            for langue, l in c["libelles"].items():
                yield f["code"], langue, l, l["texte"], fichiers
                if l.get("aide"):
                    yield f["code"], langue, l, l["aide"], fichiers
                for ch in c.get("choix") or []:
                    yield f["code"], langue, l, ch["libelles"][langue], fichiers
        for m in f["mentions"]:
            yield f["code"], m["langue"], m, m["texte"], fichiers


def test_chaque_texte_pdf_texte_est_dans_le_pdf():
    absents, controles = [], 0
    for code, langue, l, texte, fichiers in _textes_pdf():
        if l["source"] != "pdf_texte":
            continue
        controles += 1
        if _norm(texte) not in _page(fichiers[(code, langue)], l["page"]):
            absents.append((code, langue, l["page"], texte))
    assert controles > 100 and absents == []


def test_le_pdf_arabe_d_acquisition_est_illisible_d_ou_pdf_image():
    """Justifie la source « pdf_image » : le texte extrait n'est pas de l'arabe lisible."""
    page = _page("data/documents/formulaire/مطلب-إقتناء-بالعربية.pdf", 1)
    assert _norm("الاسم واللقب") not in page and _norm("مساحة قطعة الارض المطلوبة") not in page
    sources = {l["source"] for code, langue, l, *_ in _textes_pdf() if code == "demande_acquisition" and langue == "ar"}
    assert sources <= {"pdf_image", "traduction_equipe"}


def test_cin_passeport_et_signature_jamais_enregistres():
    for f in DONNEES["formulaires"]:
        non_enr = {c["code"] for c in f["champs"] if c["categorie"] == "non_enregistre"}
        assert {x for x in non_enr if x.startswith(("cin", "passeport", "signature"))} == non_enr
        assert all(c["categorie"] == "non_enregistre" for c in f["champs"]
                   if c["code"].startswith(("cin", "passeport", "signature")))
    acquisition = {c["code"]: c["categorie"] for c in DONNEES["formulaires"][0]["champs"]}
    # Décision du 2026-11-27 : toute la partie « identification » se saisit sur la page seulement.
    assert {k for k, v in acquisition.items() if v == "contact"} == {
        "nom_prenom", "raison_sociale", "forme_juridique", "registre_commerce", "taux_participation_tunisienne",
        "taux_participation_non_residente", "nationalite", "adresse", "email", "telephone", "fax", "code_postal"}


def test_le_fichier_reel_est_valide():
    fichier, erreurs = fo.lire(CORPUS)
    assert erreurs == [] and [f.code for f in fichier.formulaires] == ["demande_acquisition",
                                                                        "demande_service_administratif"]


def _ecrire(tmp_path: Path, modifier) -> Path:
    copie = tmp_path / "corpus"
    shutil.copytree(CORPUS, copie)
    d = json.loads((copie / fo.FICHIER).read_text(encoding="utf-8"))
    modifier(d)
    (copie / fo.FICHIER).write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return copie


def _champ(d, form, code):
    f = next(f for f in d["formulaires"] if f["code"] == form)
    return next(c for c in f["champs"] if c["code"] == code)


@pytest.mark.parametrize("modifier, message", [
    (lambda d: _champ(d, "demande_acquisition", "email").update(prerempli_depuis=["projet.activite"]),
     "seul un champ « projet »"),
    (lambda d: _champ(d, "demande_acquisition", "activite").update(section="inconnue"), "section inconnue"),
    (lambda d: _champ(d, "demande_acquisition", "nature").pop("choix"), "des choix sont obligatoires"),
    (lambda d: _champ(d, "demande_acquisition", "nom_prenom")["libelles"]["fr"].pop("page"), "page obligatoire"),
    (lambda d: _champ(d, "demande_acquisition", "nom_prenom").update(prerempli_depuis=["lot.prix"]), "prerempli"),
    (lambda d: _champ(d, "demande_service_administratif", "email")["libelles"]["fr"].update(
        source="pdf_texte", page=1), "sans variante fr"),
    (lambda d: d["formulaires"][1]["mentions"][1]["si"].update(valeur="9"), "condition inconnue"),
])
def test_fichier_incoherent_refuse(tmp_path, modifier, message):
    r = fo.importer("dbname=inutilise", _ecrire(tmp_path, modifier))
    assert not r.ok and message in " ".join(r.erreurs)


# ---------- Import et migration 0002 (base jetable) ----------

@pytest.fixture(scope="module")
def base(base_jetable):
    migrer.appliquer(base_jetable, role_backend=None)
    assert importer_services(base_jetable, CORPUS, appliquer=True).ok
    return base_jetable


def _compter(conninfo, table):
    with psycopg.connect(conninfo) as c:
        return c.execute(f"SELECT count(*) FROM assistant.{table}").fetchone()[0]


def test_import_controle_puis_applique_puis_rien_a_refaire(base):
    r = fo.importer(base, CORPUS, appliquer=False)
    assert r.ok and r.importes["demande_acquisition"]["champs"] == 43
    assert _compter(base, "formulaire_champs") == 0                  # contrôle : écrit puis annulé
    r = fo.importer(base, CORPUS, appliquer=True)
    assert r.ok and r.importes == {
        "demande_acquisition": {"sections": 11, "champs": 43, "libelles": 86, "mentions": 13},
        "demande_service_administratif": {"sections": 4, "champs": 17, "libelles": 34, "mentions": 7}}
    r = fo.importer(base, CORPUS, appliquer=True)
    assert r.ok and r.importes == {} and len(r.deja_presents) == 2   # rien n'est écrasé
    with psycopg.connect(base) as c:
        officiels = dict(c.execute(
            "SELECT l.source_texte, count(*) FROM assistant.formulaire_champ_libelles l GROUP BY 1").fetchall())
        assert officiels == {"pdf_texte": 58, "pdf_image": 43, "traduction_equipe": 19}
        assert c.execute("SELECT count(*) FROM assistant.formulaire_champ_libelles WHERE officiel "
                         "<> (source_texte <> 'traduction_equipe')").fetchone()[0] == 0


@pytest.fixture
def conn(base):
    if not _compter(base, "formulaire_champs"):
        assert fo.importer(base, CORPUS, appliquer=True).ok
    with psycopg.connect(base) as c:
        yield c
        c.rollback()


def _ids(conn, parcours="main-levee"):
    return conn.execute(
        "SELECT p.id, v.id, pf.formulaire_id FROM assistant.parcours p "
        "JOIN assistant.parcours_versions v ON v.parcours_id = p.id "
        "JOIN assistant.parcours_formulaires pf ON pf.parcours_id = p.id WHERE p.code = %s LIMIT 1",
        (parcours,)).fetchone()


def _demande(conn, valeurs, langue="ar", parcours="main-levee", reference="ABCD-1234"):
    pid, vid, fid = _ids(conn, parcours)
    return conn.execute(
        "INSERT INTO assistant.demandes (reference, parcours_id, parcours_version_id, formulaire_id, langue, valeurs) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (reference, pid, vid, fid, langue,
                                                         psycopg.types.json.Jsonb(valeurs))).fetchone()[0]


def test_demande_avec_champs_projet_acceptee(conn):
    did = _demande(conn, {"document_demande": "3", "zone_industrielle": "Ras El Morj", "numero_lot": "37"})
    conn.execute("INSERT INTO assistant.demande_contacts (demande_id, valeurs, consentement_texte) "
                 "VALUES (%s, %s, 'accord')", (did, psycopg.types.json.Jsonb({"telephone": "71 000 000"})))


@pytest.mark.parametrize("table, valeurs", [
    ("demandes", {"cin_numero": "01234567"}),                  # jamais enregistré
    ("demandes", {"signature_demandeur": "x"}),
    ("demandes", {"telephone": "71 000 000"}),                 # contact : pas dans les valeurs du projet
    ("demandes", {"recu_date_cachet": "x"}),                   # réservé à l'AFI
    ("demandes", {"champ_inconnu": "x"}),
    ("demandes", {"numero_lot": 37}),                          # texte seulement
    ("demandes", {"informations_complementaires": "x" * 2001}),
    ("demande_contacts", {"cin_numero": "01234567"}),
    ("demande_contacts", {"zone_industrielle": "x"}),          # projet : pas dans le contact
])
def test_valeur_hors_categorie_refusee_par_la_base(conn, table, valeurs):
    if table == "demandes":
        with pytest.raises(psycopg.errors.RaiseException, match="valeur refusée"):
            _demande(conn, valeurs)
    else:
        did = _demande(conn, {})
        with pytest.raises(psycopg.errors.RaiseException, match="valeur refusée"):
            conn.execute("INSERT INTO assistant.demande_contacts (demande_id, valeurs, consentement_texte) "
                         "VALUES (%s, %s, 'accord')", (did, psycopg.types.json.Jsonb(valeurs)))


def test_langue_sans_variante_refusee(conn):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _demande(conn, {}, langue="fr")      # le formulaire administratif n'existe qu'en arabe


def test_version_d_un_autre_parcours_refusee(conn):
    pid, _, fid = _ids(conn, "main-levee")
    _, autre_version, _ = _ids(conn, "copie-conforme")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("INSERT INTO assistant.demandes (reference, parcours_id, parcours_version_id, formulaire_id, "
                     "langue) VALUES ('ZZZZ-0000', %s, %s, %s, 'ar')", (pid, autre_version, fid))


def test_role_ecriture_ajoute_sans_pouvoir_relire_ni_modifier(conn):
    pid, vid, fid = _ids(conn)
    conn.execute("SET ROLE assistant_ecriture")
    did, ref = conn.execute(
        "INSERT INTO assistant.demandes (reference, parcours_id, parcours_version_id, formulaire_id, langue, valeurs) "
        "VALUES ('WXYZ-9876', %s, %s, %s, 'ar', '{\"document_demande\": \"3\"}') RETURNING id, reference",
        (pid, vid, fid)).fetchone()
    assert ref == "WXYZ-9876"
    conn.execute("INSERT INTO assistant.demande_contacts (demande_id, valeurs, consentement_texte) "
                 "VALUES (%s, '{\"email\": \"a@b.tn\"}', 'accord')", (did,))
    conn.execute("INSERT INTO assistant.besoins_non_couverts (question, langue) VALUES ('permis de construire ?', 'fr')")
    for requete in ("SELECT valeurs FROM assistant.demandes", "SELECT * FROM assistant.demande_contacts",
                    "SELECT * FROM assistant.besoins_non_couverts",
                    "UPDATE assistant.demandes SET statut = 'envoyee'", "DELETE FROM assistant.demandes",
                    "SELECT * FROM assistant.formulaire_champs"):
        conn.execute("SAVEPOINT s")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(requete)
        conn.execute("ROLLBACK TO SAVEPOINT s")


def test_role_lecture_ne_voit_ni_demandes_ni_contacts(conn):
    conn.execute("SET ROLE assistant_lecture")
    assert conn.execute("SELECT count(*) FROM assistant.formulaire_mentions").fetchone()[0] == 20
    for table in ("demandes", "demande_contacts", "besoins_non_couverts"):
        conn.execute("SAVEPOINT s")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(f"SELECT count(*) FROM assistant.{table}")
        conn.execute("ROLLBACK TO SAVEPOINT s")
