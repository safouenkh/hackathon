"""Import des pages des organismes (APIA, APII, TIA, FIPA) et des règles d'orientation.

Deux origines pour une même page (même URL = même document, une version par contenu) :
- les pages lues par scripts.lire_sources puis converties par scripts.extraire_sources
  (sources-organismes/md/*.md, date de lecture dans l'en-tête) ;
- les extraits de afi.chatbot_sources (dump AFI) des organismes ; les fiches SICAD (démarches
  administratives) du même dump sont importées par app.sources.sicad dans la même transaction.
La version la plus récente sert aux réponses ; les anciennes restent (BNF14 : un échec de lecture
garde la dernière version). Chaque version est découpée en passages (assistant.document_chunks).

Règles d'orientation (sources-organismes/regles_orientation.json) : chacune cite une phrase exacte
de la version la plus récente de sa page qui la contient ; la base refuse une citation absente.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.sources.cahiers import uuid_passage

TYPE_DOCUMENT = "page_organisme"
TAILLE_PASSAGE = 1500
# Un reste plus court n'est jamais un passage à part (ex. un « . » final coupé à 1500 caractères) :
# il reste avec le texte qui le précède, quitte à dépasser un peu la taille.
MIN_PASSAGE = 40
AUTEUR = "Import des pages des organismes"
_TITRE = re.compile(r"^(#{1,6})\s+(.*)$")
_PAGE = re.compile(r"^<!-- page (\d+) -->$")


@dataclass
class Rapport:
    appliquer: bool
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    versions_creees: list[str] = field(default_factory=list)
    inchangees: list[str] = field(default_factory=list)
    redecoupees: list[str] = field(default_factory=list)
    passages: int = 0
    regles_ajoutees: int = 0
    regles_desactivees: int = 0
    fiches_sicad: int = 0
    fiches_afi: int = 0
    run_id: int | None = None

    @property
    def ok(self) -> bool:
        return not self.erreurs

    def compteurs(self) -> dict[str, int]:
        return {"versions_creees": len(self.versions_creees), "inchangees": len(self.inchangees),
                "redecoupees": len(self.redecoupees), "passages": self.passages,
                "regles_ajoutees": self.regles_ajoutees, "regles_desactivees": self.regles_desactivees,
                "fiches_sicad": self.fiches_sicad, "fiches_afi": self.fiches_afi}


def cle_document(url: str) -> str:
    return f"page:{url}"


def lire_md(chemin: Path) -> tuple[dict[str, Any], str]:
    """En-tête (valeurs JSON, voir scripts.extraire_sources) et texte."""
    brut = chemin.read_text(encoding="utf-8")
    if not brut.startswith("---\n"):
        raise ValueError(f"{chemin.name} : en-tête absent")
    entete, _, texte = brut[4:].partition("\n---\n")
    meta = {}
    for ligne in entete.splitlines():
        cle, _, valeur = ligne.partition(": ")
        meta[cle.strip()] = json.loads(valeur)
    return meta, texte.strip()


def decouper(texte: str, taille: int = TAILLE_PASSAGE) -> list[dict[str, Any]]:
    """Passages par titres, puis par taille (paragraphes et lignes de tableau jamais coupés au milieu).

    Chaque passage garde son chemin de titres et sa page (PDF). Un tableau trop long est coupé entre
    deux lignes, et chaque morceau reprend la ligne d'en-tête du tableau.
    """
    passages: list[dict[str, Any]] = []
    chemin: list[tuple[int, str]] = []
    page: int | None = None
    blocs: list[str] = []
    page_debut: int | None = None

    def vider() -> None:
        nonlocal blocs, page_debut
        texte_p = "\n\n".join(b for b in blocs if b.strip()).strip()
        if texte_p:
            passages.append({"texte": texte_p, "section": [t for _, t in chemin],
                             "page_from": page_debut, "page_to": page if page_debut else None})
        blocs, page_debut = [], None

    def ajouter(bloc: str) -> None:
        nonlocal page_debut
        if blocs and sum(len(b) for b in blocs) + len(bloc) > taille and len(bloc) >= MIN_PASSAGE:
            vider()
        if page_debut is None:
            page_debut = page
        blocs.append(bloc)

    paragraphes = re.split(r"\n\s*\n", texte)
    for para in paragraphes:
        para = para.strip()
        if not para:
            continue
        m_page = _PAGE.match(para)
        if m_page:
            page = int(m_page.group(1))
            continue
        lignes = para.splitlines()
        m = _TITRE.match(lignes[0])
        if m:
            vider()
            niveau = len(m.group(1))
            chemin = [(n, t) for n, t in chemin if n < niveau] + [(niveau, m.group(2).strip()[:300])]
            reste = "\n".join(lignes[1:]).strip()
            if reste:
                ajouter(reste)
            continue
        if lignes[0].startswith("|") and len(para) > taille:
            entete = lignes[:2]
            morceau: list[str] = []
            for l in lignes[2:]:
                if morceau and len("\n".join(entete + morceau)) + len(l) > taille:
                    ajouter("\n".join(entete + morceau))
                    morceau = []
                morceau.append(l)
            if morceau:
                ajouter("\n".join(entete + morceau))
            continue
        while len(para) > taille:                 # paragraphe très long : coupé entre deux phrases
            coupe = para.rfind(". ", 0, taille)
            coupe = coupe + 1 if coupe > taille // 3 else taille
            if len(para[coupe:].strip()) < MIN_PASSAGE:     # reste minuscule : on ne coupe pas
                break
            ajouter(para[:coupe].strip())
            para = para[coupe:].strip()
        if para:
            ajouter(para)
    vider()
    return [p | {"ordinal": i} for i, p in enumerate(passages)]


# ---------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------

def _un(conn, requete: str, params: tuple) -> Any:
    ligne = conn.execute(requete, params).fetchone()
    return ligne[0] if ligne else None


def _source(conn, organisation: str, titre: str, url: str, statut: str, erreur: str | None) -> int:
    sid = _un(conn, "SELECT id FROM assistant.sources WHERE url = %s", (url,))
    if sid is None:
        sid = _un(conn, "INSERT INTO assistant.sources (organisation, title, url, ingestion_mode) "
                        "VALUES (%s, %s, %s, 'automatique') RETURNING id", (organisation, titre, url))
    conn.execute("UPDATE assistant.sources SET last_status = %s, last_error = %s, last_checked_at = now() "
                 "WHERE id = %s", (statut, erreur, sid))
    return sid


def _version(conn, r: Rapport, *, source_id: int, url: str | None, titre: str, texte: str, chemin: str | None,
             provenance: str, recupere_le: date | None, etiquette: str, type_document: str = TYPE_DOCUMENT,
             cle_doc: str | None = None) -> int:
    """Version du texte (créée si nouvelle) ; renvoie son identifiant. Document : clé `cle_doc`, sinon l'URL."""
    cle = cle_doc or cle_document(url)
    doc = _un(conn, "SELECT id FROM assistant.documents WHERE cle = %s", (cle,))
    if doc is None:
        doc = _un(conn, "INSERT INTO assistant.documents (source_id, cle, title, type, language) "
                        "VALUES (%s, %s, %s, %s, 'fr') RETURNING id", (source_id, cle, titre, type_document))
    sha = hashlib.sha256(texte.encode("utf-8")).hexdigest()
    passages = decouper(texte)
    existante = _un(conn, "SELECT id FROM assistant.document_versions WHERE document_id = %s AND sha256 = %s",
                    (doc, sha))
    if existante:
        anciens = [t for (t,) in conn.execute("SELECT text FROM assistant.document_chunks WHERE version_id = %s "
                                               "ORDER BY ordinal LIMIT 10000", (existante,)).fetchall()]
        if anciens == [p["texte"] for p in passages]:
            r.inchangees.append(etiquette)
            return existante
        # Même texte, découpage corrigé : les passages de cette version sont remplacés (l'index est reconstruit)
        conn.execute("DELETE FROM assistant.document_chunks WHERE version_id = %s", (existante,))
        _ecrire_passages(conn, existante, sha, passages)
        r.passages += len(passages)
        r.redecoupees.append(etiquette)
        return existante
    vid = _un(conn, "INSERT INTO assistant.document_versions (document_id, sha256, media_type, original_path, "
                    "full_text, content_provenance, retrieved_at) VALUES (%s, %s, 'text/markdown', %s, %s, %s, %s) "
                    "RETURNING id", (doc, sha, chemin, texte, provenance, recupere_le))
    _ecrire_passages(conn, vid, sha, passages)
    r.passages += len(passages)
    r.versions_creees.append(etiquette)
    return vid


def _ecrire_passages(conn, vid: int, sha: str, passages: list[dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO assistant.document_chunks (id, version_id, cle, ordinal, text, page_from, page_to, article, "
            "section, heading, partie, categorie_sol, a_verifier, raisons_verification) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s, %s, 'contenu', NULL, false, '{}')",
            [(uuid_passage(sha, f"p{p['ordinal']:04d}"), vid, f"p{p['ordinal']:04d}", p["ordinal"], p["texte"],
              p["page_from"], p["page_to"], p["section"], p["section"][-1] if p["section"] else None)
             for p in passages])


def _normaliser_espaces(t: str) -> str:
    return re.sub(r"\s+", " ", t)


def _ecrire_regles(conn, dossier: Path, r: Rapport) -> None:
    donnees = json.loads((dossier / "regles_orientation.json").read_text(encoding="utf-8"))
    gardees: list[int] = []
    for regle in donnees["regles"]:
        citation = regle["citation"]
        versions = conn.execute(
            "SELECT dv.id, dv.full_text FROM assistant.document_versions dv "
            "JOIN assistant.documents d ON d.id = dv.document_id WHERE d.cle = %s "
            "ORDER BY dv.retrieved_at DESC NULLS LAST, dv.id DESC LIMIT 20", (cle_document(regle["source_url"]),)).fetchall()
        version = next((v for v, t in versions if _normaliser_espaces(citation) in _normaliser_espaces(t or "")), None)
        if version is None:
            r.erreurs.append(f"règle {regle['organisation']} : citation absente de {regle['source_url']}")
            continue
        if versions and version != versions[0][0]:
            r.avertissements.append(f"règle {regle['organisation']} : citation absente de la version la plus récente "
                                    f"de {regle['source_url']}, version plus ancienne citée")
        criteres = (regle["organisation"], regle["role"], regle.get("secteur"), regle.get("secteurs_exclus"),
                    regle.get("investissement_min_dt"), regle.get("investissement_max_dt"),
                    regle.get("investisseur_etranger"))
        existe = _un(conn, "SELECT id FROM assistant.regles_orientation WHERE organisation = %s AND role = %s "
                           "AND secteur IS NOT DISTINCT FROM %s AND secteurs_exclus IS NOT DISTINCT FROM %s::text[] "
                           "AND investissement_min_dt IS NOT DISTINCT FROM %s "
                           "AND investissement_max_dt IS NOT DISTINCT FROM %s "
                           "AND investisseur_etranger IS NOT DISTINCT FROM %s", criteres)
        if existe:
            conn.execute("UPDATE assistant.regles_orientation SET actif = true WHERE id = %s AND NOT actif", (existe,))
            gardees.append(existe)
            continue
        gardees.append(_un(conn, "INSERT INTO assistant.regles_orientation (organisation, role, secteur, "
                                 "secteurs_exclus, investissement_min_dt, investissement_max_dt, investisseur_etranger, "
                                 "citation, version_id, ajoute_par) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                                 "RETURNING id", (*criteres, citation, version, donnees["ajoute_par"])))
        r.regles_ajoutees += 1
    # Le fichier est la référence de cet import : une règle qui en a disparu est désactivée (historique gardé).
    if not r.erreurs:
        n = conn.execute("UPDATE assistant.regles_orientation SET actif = false WHERE ajoute_par = %s AND actif "
                         "AND NOT (id = ANY(%s))", (donnees["ajoute_par"], gardees)).rowcount
        r.regles_desactivees += n


def _ecrire(conn, dossier: Path, r: Rapport) -> None:
    liens = json.loads((dossier / "liens.json").read_text(encoding="utf-8"))["liens"]
    manifeste = json.loads((dossier / "manifeste.json").read_text(encoding="utf-8"))
    extraction = json.loads((dossier / "extraction.json").read_text(encoding="utf-8"))
    for lien in liens:
        url = lien["url"]
        if lien.get("lien_seul"):       # contenu jamais stocké : seulement la source (lien) pour orienter
            sid = _un(conn, "SELECT id FROM assistant.sources WHERE url = %s", (url,))
            if sid is None:
                _un(conn, "INSERT INTO assistant.sources (organisation, title, url, ingestion_mode, last_status) "
                          "VALUES (%s, %s, %s, 'lien_seul', 'lien_seul') RETURNING id",
                    (lien["organisation"], lien["titre"], url))
            if _un(conn, "SELECT count(*) FROM assistant.documents WHERE cle = %s", (cle_document(url),)):
                raise ValueError(f"{url} : lien seul, mais un contenu est en base (à retirer)")
            continue
        m, x = manifeste.get(url, {}), extraction.get(url, {})
        statut = "ok" if x.get("statut") == "ok" else (m.get("statut") or "non_lu")
        sid = _source(conn, lien["organisation"], lien["titre"], url, statut,
                      m.get("erreur") or m.get("derniere_erreur") or (x.get("raison") if statut != "ok" else None))
        if x.get("statut") != "ok":
            r.avertissements.append(f"{url} : pas de texte ({statut})")
            continue
        meta, texte = lire_md(dossier / x["fichier"])
        if meta["source_url"] != url:
            raise ValueError(f"{x['fichier']} : l'en-tête ne correspond pas à {url}")
        _version(conn, r, source_id=sid, url=url, titre=lien["titre"], texte=texte,
                 chemin=f"{dossier.name}/{x['fichier']}",
                 provenance=(f"Page lue le {meta['date_collecte']} (scripts.lire_sources, réponse brute "
                             f"SHA-256 {meta['sha256_brut'][:12]}…), texte extrait par {meta['extraction']} ; "
                             "non relu."),
                 recupere_le=date.fromisoformat(meta["date_collecte"]), etiquette=url)

    # Extraits du dump AFI : organismes (les fiches SICAD sont traitées à part, voir app.sources.sicad)
    for id_, organisme, url, titre, contenu, collecte in conn.execute(
            "SELECT id, upper(source), url, titre, contenu, created_at::date FROM afi.chatbot_sources "
            "WHERE lower(source) <> 'sicad' AND url IS NOT NULL AND coalesce(contenu, '') <> '' ORDER BY id LIMIT 200"
    ).fetchall():
        sid = _un(conn, "SELECT id FROM assistant.sources WHERE url = %s", (url,))
        if sid is None:     # page connue seulement par le dump : jamais lue par nous (pas de date de vérification)
            sid = _un(conn, "INSERT INTO assistant.sources (organisation, title, url, ingestion_mode, last_status) "
                            "VALUES (%s, %s, %s, 'manuel', 'dump_afi') RETURNING id", (organisme, titre, url))
        _version(conn, r, source_id=sid, url=url, titre=titre, texte=contenu.strip(), chemin=None,
                 provenance=f"Extrait afi.chatbot_sources id={id_} (dump AFI), collecté le {collecte} ; non relu.",
                 recupere_le=collecte, etiquette=f"chatbot_sources:{id_}")
    from app.semantique.ontologie import ontologie
    from app.sources import connaissances, sicad
    r.fiches_sicad = sicad.ecrire(conn, r)
    r.fiches_afi = connaissances.ecrire(conn, r, ontologie().fiches_ecartees)
    _ecrire_regles(conn, dossier, r)


def importer(conninfo: str, dossier: Path, appliquer: bool = False) -> Rapport:
    """Contrôle (écrit puis annule) ou import réel avec `appliquer=True`."""
    r = Rapport(appliquer=appliquer)
    with psycopg.connect(conninfo) as conn:
        try:
            with conn.transaction():
                _ecrire(conn, dossier, r)
                if r.erreurs:
                    raise psycopg.Rollback()
                r.run_id = _un(conn, "INSERT INTO assistant.ingestion_runs (status, counts, finished_at) "
                                     "VALUES ('reussi', %s, now()) RETURNING id", (Jsonb(r.compteurs()),))
                if not appliquer:
                    raise psycopg.Rollback()
        except (ValueError, OSError, psycopg.Error) as exc:
            r.erreurs.append(f"écriture annulée : {type(exc).__name__}: {exc}")
        if r.erreurs:
            r.versions_creees, r.inchangees, r.redecoupees, r.passages, r.regles_ajoutees, r.run_id = \
                [], [], [], 0, 0, None
            r.regles_desactivees, r.fiches_sicad, r.fiches_afi = 0, 0, 0
            if appliquer:
                conn.execute("INSERT INTO assistant.ingestion_runs (status, error, finished_at) VALUES "
                             "('echec', %s, now())", ("\n".join(r.erreurs[:50]),))
                conn.commit()
    return r
