"""Import des cahiers des charges des zones et des compléments de zone (paquet GraphRAG de l'équipe).

Entrée : le dossier du paquet (`sources/*.md`, `vectors/chunks.jsonl`, `data/afi_industrial_zones.json`).
Ces fichiers sont des données NON FIABLES : ils sont lus et validés, jamais exécutés, et leur texte
n'est jamais une instruction.

Règles :
- Le lien document ↔ zone vient de la table AFI `afi.zone_documents` (type `cahier_charges`, même nom
  de fichier). Jamais deviné : un document sans ligne AFI garde `zone_id` null et il est signalé.
- Un complément de zone n'est créé que si la valeur AFI est vide (prix null ou 0 ; commodité absente
  ou sans valeur). Une valeur AFI présente n'est jamais remplacée.
- Les écarts (valeur AFI et valeur du JSON différentes) sont listés pour relecture, jamais appliqués.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError

FICHIER_CHUNKS = Path("vectors") / "chunks.jsonl"
FICHIER_ZONES = Path("data") / "afi_industrial_zones.json"
DOSSIER_SOURCES = Path("sources")

# Espace de noms des UUID de passages : même texte d'entrée -> même UUID (import idempotent).
_NS_CHUNK = uuid.uuid5(uuid.NAMESPACE_URL, "https://example.org/afi/resource/chunk")

_PARTIES = {"regulation": "reglement", "presentation_report": "rapport_presentation",
            "front_matter": "en_tete", "annex": "annexe"}

# Colonne AFI complétée -> champ du JSON. Unités : celles de la colonne AFI (voir migration 0003).
CHAMPS_JSON: dict[str, str] = {
    "prixunitaire": "ZONE_PRIX",
    "com_1": "ZONE_AEROPORT_DIST", "com_2": "ZONE_PORT_DIST", "com_3": "ZONE_GARE_DIST",
    "com_4": "ZONE_AUTOROUTE_DIST", "com_5": "ZONE_GP_DIST", "com_6": "ZONE_PUISSANCE", "com_7": "ZONE_DEBIT",
}

SOURCE_CAHIERS = ("AFI", "Cahiers des charges des zones : texte extrait par l'équipe (paquet GraphRAG)")
SOURCE_JSON = ("Équipe Dalila", "Paquet GraphRAG : afi_industrial_zones.json (origine non documentée)")


class ChunkPaquet(BaseModel):
    """Une ligne de `chunks.jsonl` (champs utiles seulement ; les autres sont ignorés)."""
    model_config = ConfigDict(extra="ignore")

    chunk_id: str = Field(pattern=r"^\d{6,7}-[a-z0-9-]{1,80}$")
    doc_id: str = Field(pattern=r"^\d{6,7}$")
    doc_title: str = Field(min_length=1, max_length=200)
    year: int | None = Field(default=None, ge=1950, le=2100)
    doc_part: Literal["regulation", "presentation_report", "front_matter", "annex"]
    land_use: str | None = Field(default=None, max_length=20)
    path: list[str] = Field(default_factory=list, max_length=20)
    article_number: str | None = Field(default=None, max_length=20)
    heading: str | None = Field(default=None, max_length=1000)
    order: int = Field(ge=0)
    pages: list[int] = Field(default_factory=list)
    source_file: str = Field(pattern=r"^\d{6,7}__[a-z0-9-]+\.md$")
    needs_review: bool
    review_reasons: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1, max_length=8000)


@dataclass
class DocumentPaquet:
    doc_id: str
    fichier: str                  # nom du .md (= nom du PDF AFI, extension changée)
    titre: str
    annee: int | None
    sha256: str
    texte: str
    chunks: list[ChunkPaquet]


@dataclass
class Complement:
    code_zone: int
    champ: str
    valeur: float


@dataclass
class Ecart:
    code_zone: int
    champ: str
    valeur_afi: Any
    valeur_json: Any


@dataclass
class RapportCahiers:
    appliquer: bool
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)             # doc_id importés (nouvelle version)
    inchanges: list[str] = field(default_factory=list)
    liens: dict[str, int | None] = field(default_factory=dict)     # doc_id -> code_zone AFI
    chunks: int = 0
    complements: list[Complement] = field(default_factory=list)
    ecarts: list[Ecart] = field(default_factory=list)
    concordance: dict[str, tuple[int, int]] = field(default_factory=dict)  # champ -> (égaux, comparés)
    run_id: int | None = None

    @property
    def ok(self) -> bool:
        return not self.erreurs

    def compteurs(self) -> dict[str, int]:
        return {"documents": len(self.documents), "inchanges": len(self.inchanges), "chunks": self.chunks,
                "complements": len(self.complements), "ecarts": len(self.ecarts),
                "documents_sans_zone": sum(1 for z in self.liens.values() if z is None)}


# ---------------------------------------------------------------------
# Lecture du paquet
# ---------------------------------------------------------------------

def _sha256(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


def lire_paquet(dossier: Path) -> tuple[list[DocumentPaquet], list[dict], str, list[str]]:
    """Documents (avec leurs passages), zones du JSON, SHA-256 du JSON, erreurs."""
    erreurs: list[str] = []
    chunks: list[ChunkPaquet] = []
    for n, ligne in enumerate((dossier / FICHIER_CHUNKS).read_text(encoding="utf-8").splitlines(), 1):
        if not ligne.strip():
            continue
        try:
            chunks.append(ChunkPaquet.model_validate_json(ligne))
        except ValidationError as exc:
            erreurs.append(f"chunks.jsonl ligne {n} : {exc.errors()[0]['loc']} {exc.errors()[0]['msg']}")
    ids = [c.chunk_id for c in chunks]
    if len(ids) != len(set(ids)):
        erreurs.append("chunks.jsonl : identifiant de passage en double")

    par_fichier: dict[str, list[ChunkPaquet]] = {}
    for c in chunks:
        if not c.source_file.startswith(c.doc_id + "__"):
            erreurs.append(f"{c.chunk_id} : doc_id {c.doc_id} différent du fichier {c.source_file}")
        par_fichier.setdefault(c.source_file, []).append(c)

    documents: list[DocumentPaquet] = []
    for fichier, liste in sorted(par_fichier.items()):
        chemin = dossier / DOSSIER_SOURCES / fichier
        if not chemin.is_file():
            erreurs.append(f"{fichier} : fichier source absent de {DOSSIER_SOURCES}/")
            continue
        octets = chemin.read_bytes()
        liste.sort(key=lambda c: c.order)
        if len({c.order for c in liste}) != len(liste):
            erreurs.append(f"{fichier} : ordre de passage en double")
        if len({(c.doc_title, c.year) for c in liste}) != 1:
            erreurs.append(f"{fichier} : titres ou années différents selon les passages")
        documents.append(DocumentPaquet(doc_id=liste[0].doc_id, fichier=fichier, titre=liste[0].doc_title,
                                        annee=liste[0].year, sha256=_sha256(octets),
                                        texte=octets.decode("utf-8"), chunks=liste))

    octets_json = (dossier / FICHIER_ZONES).read_bytes()
    zones = json.loads(octets_json)
    if not isinstance(zones, list) or not all(isinstance(z, dict) and "ZONE_ID" in z for z in zones):
        erreurs.append(f"{FICHIER_ZONES} : liste de zones attendue")
        zones = []
    return documents, zones, _sha256(octets_json), erreurs


def _nombre(x: Any) -> float | None:
    if x is None or isinstance(x, bool):
        return None
    try:
        return float(str(x).strip().replace(",", "."))
    except ValueError:
        return None


# ---------------------------------------------------------------------
# Rapprochement avec la base AFI (lecture seule)
# ---------------------------------------------------------------------

def _nom(fichier: str) -> str:
    """Nom comparable : sans dossier, sans extension, sans le suffixe de compression du PDF.
    Ex. AFI « 930902__cc-ghazela-2002-compressed.pdf » = paquet « 930902__cc-ghazela-2002.md »."""
    nom = PurePosixPath(fichier.replace("\\", "/")).stem.lower()
    return nom.removesuffix("-compressed").removesuffix("_compressed")


def liens_afi(conn: psycopg.Connection, documents: list[DocumentPaquet]) -> dict[str, int | None]:
    """doc_id -> code_zone selon afi.zone_documents (même nom de fichier) ; None si l'AFI ne le relie pas."""
    lignes = conn.execute(
        "SELECT d.zone_id::text, d.fichier, EXISTS (SELECT 1 FROM afi.zones z WHERE z.code_zone::text = d.zone_id::text) "
        "FROM afi.zone_documents d WHERE d.type = 'cahier_charges' LIMIT 1000").fetchall()
    par_nom: dict[str, list[tuple[str, bool]]] = {}
    for zone_id, fichier, zone_existe in lignes:
        if fichier:
            par_nom.setdefault(_nom(fichier), []).append((zone_id, zone_existe))
    liens: dict[str, int | None] = {}
    for d in documents:
        trouves = {z for z, existe in par_nom.get(_nom(d.fichier), []) if existe}
        liens[d.doc_id] = int(trouves.pop()) if len(trouves) == 1 else None
    return liens


def comparer_zones(conn: psycopg.Connection, zones_json: list[dict], r: RapportCahiers) -> None:
    """Compléments (AFI vide, JSON renseigné), écarts (les deux renseignés et différents), concordance."""
    afi_zones = {str(code): prix for code, prix in conn.execute(
        "SELECT code_zone, prixunitaire FROM afi.zones LIMIT 5000")}
    commodites: dict[tuple[str, int], Any] = {(str(code), cid): dist for code, cid, dist in conn.execute(
        "SELECT code_zone, com_id, zc_distance FROM afi.zone_commodites WHERE com_id BETWEEN 1 AND 7 LIMIT 10000")}
    for z in zones_json:
        code = str(z.get("ZONE_ID", "")).strip()
        if code not in afi_zones:
            r.avertissements.append(f"zone {code} du JSON absente de afi.zones : ignorée")
            continue
        for champ, cle in CHAMPS_JSON.items():
            v_json = _nombre(z.get(cle))
            if z.get(cle) not in (None, "") and v_json is None:
                r.avertissements.append(f"zone {code} : {cle} = {z.get(cle)!r} n'est pas un nombre, ignoré")
            if v_json is None or v_json <= 0:
                continue
            if champ == "prixunitaire":
                v_afi = _nombre(afi_zones[code])
                vide = v_afi is None or v_afi <= 0
            else:
                v_afi = _nombre(commodites.get((code, int(champ[4:]))))
                vide = v_afi is None
            if vide:
                r.complements.append(Complement(int(code), champ, v_json))
                continue
            egaux, compares = r.concordance.get(champ, (0, 0))
            r.concordance[champ] = (egaux + (v_afi == v_json), compares + 1)
            if v_afi != v_json:
                r.ecarts.append(Ecart(int(code), champ, v_afi, v_json))


# ---------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------

def _un(conn, requete: str, params: tuple) -> Any:
    ligne = conn.execute(requete, params).fetchone()
    return ligne[0] if ligne else None


def _source(conn, organisation: str, titre: str) -> int:
    sid = _un(conn, "SELECT id FROM assistant.sources WHERE url IS NULL AND organisation = %s AND title = %s "
                    "ORDER BY id LIMIT 1", (organisation, titre))
    if sid is None:
        sid = _un(conn, "INSERT INTO assistant.sources (organisation, title, url, ingestion_mode) "
                        "VALUES (%s, %s, NULL, 'manuel') RETURNING id", (organisation, titre))
    return sid


def _version(conn, *, source_id: int, cle: str, titre: str, type_: str, zone_id: int | None, langue: str | None,
             chemin: str, sha: str, media_type: str, texte: str | None, provenance: str,
             recu_le: date) -> tuple[int, bool]:
    """(id de la version, créée maintenant ?). Le document garde sa zone d'origine : un écart est signalé."""
    ligne = conn.execute("SELECT id, zone_id FROM assistant.documents WHERE cle = %s", (cle,)).fetchone()
    if ligne is None:
        doc = _un(conn, "INSERT INTO assistant.documents (source_id, cle, title, type, zone_id, language) "
                        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (source_id, cle, titre, type_, zone_id, langue))
    else:
        doc = ligne[0]
        if ligne[1] != zone_id:
            raise ValueError(f"document {cle} : zone {ligne[1]} en base, {zone_id} selon afi.zone_documents "
                             "(à trancher à la main)")
    dv = _un(conn, "SELECT id FROM assistant.document_versions WHERE document_id = %s AND sha256 = %s", (doc, sha))
    if dv is not None:
        return dv, False
    dv = _un(conn, "INSERT INTO assistant.document_versions (document_id, sha256, media_type, original_path, full_text, "
                   "content_provenance, retrieved_at) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
             (doc, sha, media_type, chemin, texte, provenance, recu_le))
    return dv, True


def uuid_passage(sha_version: str, cle: str) -> uuid.UUID:
    return uuid.uuid5(_NS_CHUNK, f"{sha_version}:{cle}")


def _ecrire_passages(conn, version_id: int, d: DocumentPaquet) -> int:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO assistant.document_chunks (id, version_id, cle, ordinal, text, page_from, page_to, article, "
            "section, heading, partie, categorie_sol, a_verifier, raisons_verification) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [(uuid_passage(d.sha256, c.chunk_id), version_id, c.chunk_id, c.order, c.text,
              min(c.pages) if c.pages else None, max(c.pages) if c.pages else None,
              c.article_number, c.path, c.heading, _PARTIES[c.doc_part], c.land_use,
              c.needs_review, c.review_reasons) for c in d.chunks])
    return len(d.chunks)


def _ecrire(conn, dossier: Path, documents: list[DocumentPaquet], sha_json: str, recu_le: date,
            r: RapportCahiers) -> None:
    src_cahiers = _source(conn, *SOURCE_CAHIERS)
    noms_afi = {_nom(f): n for f, n in conn.execute("SELECT fichier, nom_original FROM afi.zone_documents "
                                                    "WHERE type = 'cahier_charges' AND fichier IS NOT NULL LIMIT 1000")}
    for d in documents:
        nom_pdf = noms_afi.get(_nom(d.fichier))
        provenance = (f"Texte extrait par l'équipe (paquet GraphRAG) du cahier des charges AFI"
                      f"{f' « {nom_pdf} »' if nom_pdf else ''} ; OCR pour une partie des documents ; "
                      "non relu contre le PDF.")
        titre = f"Cahier des charges : {d.titre}" + (f" ({d.annee})" if d.annee else "")
        vid, nouvelle = _version(conn, source_id=src_cahiers, cle=f"cahier/{Path(d.fichier).stem}", titre=titre,
                                 type_="cahier_charges", zone_id=r.liens.get(d.doc_id), langue="fr",
                                 chemin=f"{dossier.name}/{DOSSIER_SOURCES.as_posix()}/{d.fichier}", sha=d.sha256,
                                 media_type="text/markdown", texte=d.texte, provenance=provenance, recu_le=recu_le)
        if not nouvelle:
            r.inchanges.append(d.doc_id)
            continue
        r.chunks += _ecrire_passages(conn, vid, d)
        r.documents.append(d.doc_id)

    if r.complements:
        src_json = _source(conn, *SOURCE_JSON)
        vid, _ = _version(conn, source_id=src_json, cle="paquet/afi_industrial_zones.json",
                          titre="Zones industrielles AFI (JSON du paquet GraphRAG)", type_="donnees_zones",
                          zone_id=None, langue=None, chemin=f"{dossier.name}/{FICHIER_ZONES.as_posix()}",
                          sha=sha_json, media_type="application/json", texte=None,
                          provenance="Fichier JSON transmis par l'équipe ; origine non documentée (à confirmer).",
                          recu_le=recu_le)
        for c in r.complements:
            existe = conn.execute("SELECT valeur FROM assistant.zone_complements WHERE code_zone = %s AND champ = %s",
                                  (c.code_zone, c.champ)).fetchone()
            if existe is None:
                conn.execute("INSERT INTO assistant.zone_complements (code_zone, champ, valeur, version_id, cle_source) "
                             "VALUES (%s, %s, %s, %s, %s)", (c.code_zone, c.champ, c.valeur, vid, CHAMPS_JSON[c.champ]))
            elif float(existe[0]) != c.valeur:
                r.avertissements.append(f"complément {c.code_zone}/{c.champ} : {existe[0]} en base conservé "
                                        f"(JSON : {c.valeur})")


def _lire_et_rapprocher(conn, dossier: Path, r: RapportCahiers):
    try:
        documents, zones_json, sha_json, erreurs = lire_paquet(dossier)
    except (OSError, ValueError) as exc:
        r.erreurs.append(f"lecture du paquet : {type(exc).__name__}: {exc}")
        return None
    r.erreurs += erreurs
    r.liens = liens_afi(conn, documents)
    r.avertissements += [f"document {d} : aucune zone dans afi.zone_documents (zone_id laissé vide)"
                         for d, z in r.liens.items() if z is None]
    comparer_zones(conn, zones_json, r)
    return documents, sha_json


def analyser(conninfo: str, dossier: Path) -> RapportCahiers:
    """Lecture seule : liens, compléments proposés et écarts, sans rien écrire (relecture)."""
    r = RapportCahiers(appliquer=False)
    with psycopg.connect(conninfo) as conn:
        _lire_et_rapprocher(conn, dossier, r)
    return r


def importer(conninfo: str, dossier: Path, recu_le: date, appliquer: bool = False) -> RapportCahiers:
    """Contrôle (écrit puis annule) ou import réel avec `appliquer=True`."""
    r = RapportCahiers(appliquer=appliquer)
    with psycopg.connect(conninfo) as conn:
        lu = _lire_et_rapprocher(conn, dossier, r)
        if lu is None:
            return r
        documents, sha_json = lu
        if not r.ok:
            if appliquer:
                conn.execute("INSERT INTO assistant.ingestion_runs (status, error, finished_at) "
                             "VALUES ('echec', %s, now())", ("\n".join(r.erreurs[:50]),))
                conn.commit()
            return r
        try:
            with conn.transaction():
                _ecrire(conn, dossier, documents, sha_json, recu_le, r)
                r.run_id = _un(conn, "INSERT INTO assistant.ingestion_runs (source_id, status, counts, finished_at) "
                                     "VALUES (%s, 'reussi', %s, now()) RETURNING id",
                               (_source(conn, *SOURCE_CAHIERS), Jsonb(r.compteurs())))
                if not appliquer:
                    raise psycopg.Rollback()
        except (ValueError, psycopg.Error) as exc:
            r.erreurs.append(f"écriture annulée : {type(exc).__name__}: {exc}")
            r.documents, r.inchanges, r.chunks, r.run_id = [], [], 0, None
    return r


_LIBELLES = {"prixunitaire": "prix (Dt/m², colonne prixunitaire)", "com_1": "aéroport (km)", "com_2": "port (km)",
             "com_3": "gare (km)", "com_4": "autoroute (km)", "com_5": "route GP (km)",
             "com_6": "électricité (Kva/Hec)", "com_7": "eau potable (m3/j/hec)"}


def revue_markdown(r: RapportCahiers) -> str:
    """Relecture humaine : liens, compléments proposés, écarts (non appliqués)."""
    l = ["# Paquet GraphRAG : relecture avant import", "",
         "Généré par `scripts.importer_cahiers --revue`. La base AFI reste la référence : un complément ne sert "
         "que si la valeur AFI est vide ; un écart n'est jamais appliqué.", "",
         "## Cahiers des charges ↔ zones (table AFI `zone_documents`)", "",
         "| Document | Zone AFI |", "|---|---|"]
    l += [f"| {d} | {z if z is not None else '**aucune**'} |" for d, z in sorted(r.liens.items())]
    l += ["", "## Concordance JSON / base AFI (valeurs présentes des deux côtés)", "",
          "| Champ | Égales | Comparées |", "|---|---|---|"]
    l += [f"| {_LIBELLES[c]} | {e} | {n} |" for c, (e, n) in sorted(r.concordance.items())]
    l += ["", "## Compléments proposés (valeur AFI vide)", "", "| Zone | Champ | Valeur du JSON |", "|---|---|---|"]
    l += [f"| {c.code_zone} | {_LIBELLES[c.champ]} | {c.valeur:g} |" for c in r.complements]
    l += ["", "## Écarts (non appliqués : la base AFI est gardée)", "",
          "| Zone | Champ | Base AFI | JSON |", "|---|---|---|---|"]
    l += [f"| {e.code_zone} | {_LIBELLES[e.champ]} | {e.valeur_afi:g} | {e.valeur_json:g} |" for e in r.ecarts]
    if r.avertissements:
        l += ["", "## Avertissements", ""] + [f"- {a}" for a in r.avertissements]
    return "\n".join(l) + "\n"
