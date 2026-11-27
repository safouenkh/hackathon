"""Import des fiches de services et des formulaires dans le schéma `assistant`.

- Le catalogue (catalogue.json du corpus) dit quel fichier correspond à quel service : rien
  n'est écrit dans le code.
- Toutes les fiches sont lues et contrôlées AVANT toute écriture ; une seule erreur arrête
  l'import, qui est alors noté en échec dans `assistant.ingestion_runs`.
- L'écriture se fait en une transaction : tout ou rien.
- Chaque fiche importée devient une version BROUILLON de son parcours ; rien n'est publié
  automatiquement (publication : scripts/publier_parcours.py, après relecture).
- Un fichier inchangé (même SHA-256) ne crée pas de nouvelle version.
- Les services, parcours et liens de formulaire déjà présents ne sont pas écrasés : ils
  peuvent avoir été modifiés par l'admin ; une différence est seulement signalée.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
from pydantic import BaseModel, ConfigDict, Field, model_validator
from psycopg.types.json import Jsonb

from app.sources.fiche_service import Element, Fiche, lire

AUTEUR_IMPORT = "import"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceCat(_Strict):
    cle: str
    organisation: str
    title: str
    url: str | None
    ingestion_mode: str


class ServiceCat(_Strict):
    code: str
    nom: str
    besoin: str | None = None
    ordre: int
    source: str


class ParcoursCat(_Strict):
    code: str
    service: str
    ordre: int
    fichier: str
    source: str
    critere_choix: str | None = None


class VarianteCat(_Strict):
    langue: str
    titre_officiel: str
    fichier: str
    source: str
    url_fichier: str | None = None
    provenance: str


class FormulaireCat(_Strict):
    code: str
    titre: str
    variantes: list[VarianteCat] = Field(min_length=1)


class LienFormulaireCat(_Strict):
    parcours: str
    formulaire: str
    valeurs_imposees: dict[str, Any] = {}
    note_verification: str | None = None


class Catalogue(_Strict):
    version: int
    description: str
    date: date
    sources: list[SourceCat]
    services: list[ServiceCat]
    parcours: list[ParcoursCat]
    formulaires: list[FormulaireCat]
    parcours_formulaires: list[LienFormulaireCat]

    @model_validator(mode="after")
    def _references(self) -> "Catalogue":
        sources = {s.cle for s in self.sources}
        services = {s.code for s in self.services}
        parcours = {p.code for p in self.parcours}
        formulaires = {f.code for f in self.formulaires}
        erreurs = []
        for nom, codes in (("sources", [s.cle for s in self.sources]), ("services", [s.code for s in self.services]),
                           ("parcours", [p.code for p in self.parcours]),
                           ("formulaires", [f.code for f in self.formulaires])):
            if len(codes) != len(set(codes)):
                erreurs.append(f"doublon dans {nom}")
        erreurs += [f"parcours {p.code} : service inconnu {p.service}" for p in self.parcours if p.service not in services]
        erreurs += [f"parcours {p.code} : source inconnue {p.source}" for p in self.parcours if p.source not in sources]
        erreurs += [f"formulaire {f.code} : source inconnue {v.source}"
                    for f in self.formulaires for v in f.variantes if v.source not in sources]
        erreurs += [f"lien {l.parcours} -> {l.formulaire} : référence inconnue"
                    for l in self.parcours_formulaires if l.parcours not in parcours or l.formulaire not in formulaires]
        if erreurs:
            raise ValueError("; ".join(erreurs))
        return self


@dataclass
class FicheLue:
    parcours: ParcoursCat
    chemin: Path
    sha256: str
    texte: str
    fiche: Fiche


@dataclass
class Rapport:
    appliquer: bool
    fiches: list[FicheLue] = field(default_factory=list)
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    versions_creees: list[str] = field(default_factory=list)
    inchangees: list[str] = field(default_factory=list)
    run_id: int | None = None

    @property
    def ok(self) -> bool:
        return not self.erreurs

    def compteurs(self) -> dict[str, int]:
        return {"fiches": len(self.fiches), "versions_creees": len(self.versions_creees),
                "inchangees": len(self.inchangees),
                "elements": sum(sum(f.fiche.compter().values()) for f in self.fiches
                                if f.parcours.code in self.versions_creees)}


def _sha256(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def charger_catalogue(dossier: Path) -> Catalogue:
    return Catalogue.model_validate_json((dossier / "catalogue.json").read_text(encoding="utf-8"))


def lire_corpus(dossier: Path, cat: Catalogue) -> Rapport:
    """Lit et contrôle tout, sans rien écrire."""
    r = Rapport(appliquer=False)
    manifeste = {}
    if (dossier / "manifest.json").is_file():
        manifeste = {m["path"]: m.get("sha256") for m in json.loads((dossier / "manifest.json").read_text("utf-8"))}
    for p in cat.parcours:
        chemin = dossier / p.fichier
        if not chemin.is_file():
            r.erreurs.append(f"{p.code} : fichier absent {p.fichier}")
            continue
        texte = chemin.read_text(encoding="utf-8")
        sha = _sha256(chemin)
        attendu = manifeste.get(p.fichier)
        if attendu and attendu not in (sha, hashlib.sha256(texte.replace("\r\n", "\n").encode()).hexdigest()):
            r.avertissements.append(f"{p.code} : SHA-256 différent de manifest.json (fichier modifié depuis)")
        fiche = lire(texte)
        r.erreurs += [f"{p.code} : {e}" for e in fiche.erreurs]
        r.avertissements += [f"{p.code} : {a}" for a in fiche.avertissements]
        if not [e for e in fiche.elements if e.type in ("etape", "condition", "piece")]:
            r.erreurs.append(f"{p.code} : ni étape, ni condition, ni pièce lue : extraction douteuse")
        r.fiches.append(FicheLue(p, chemin, sha, texte, fiche))
    for f in cat.formulaires:
        for v in f.variantes:
            if not (dossier / v.fichier).is_file():
                r.erreurs.append(f"formulaire {f.code}/{v.langue} : fichier absent {v.fichier}")
    listes = {p.fichier for p in cat.parcours}
    for md in sorted((dossier / "data/documents/services").glob("*/*.md")):
        rel = md.relative_to(dossier).as_posix()
        if rel not in listes:
            r.avertissements.append(f"fichier non référencé par catalogue.json : {rel}")
    return r


# ---------------------------------------------------------------------
# Écriture
# ---------------------------------------------------------------------

def _un(conn, requete: str, params: tuple) -> Any:
    ligne = conn.execute(requete, params).fetchone()
    return ligne[0] if ligne else None


def _source(conn, s: SourceCat) -> int:
    sid = _un(conn, "SELECT id FROM assistant.sources WHERE url = %s", (s.url,)) if s.url else None
    if sid is None:
        sid = _un(conn, "INSERT INTO assistant.sources (organisation, title, url, ingestion_mode) "
                        "VALUES (%s, %s, %s, %s) RETURNING id", (s.organisation, s.title, s.url, s.ingestion_mode))
    return sid


def _version_document(conn, *, source_id: int, cle: str, title: str, type_: str, langue: str | None,
                      chemin: str, sha: str, media_type: str, full_text: str | None, provenance: str | None,
                      recupere_le: date | None) -> int:
    doc = _un(conn, "SELECT id FROM assistant.documents WHERE cle = %s", (cle,))
    if doc is None:
        doc = _un(conn, "INSERT INTO assistant.documents (source_id, cle, title, type, language) "
                        "VALUES (%s, %s, %s, %s, %s) RETURNING id", (source_id, cle, title, type_, langue))
    dv = _un(conn, "SELECT id FROM assistant.document_versions WHERE document_id = %s AND sha256 = %s", (doc, sha))
    if dv is None:
        dv = _un(conn, "INSERT INTO assistant.document_versions (document_id, sha256, media_type, original_path, "
                       "full_text, content_provenance, retrieved_at) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                 (doc, sha, media_type, chemin, full_text, provenance, recupere_le))
    return dv


def _inserer_elements(conn, version_id: int, elements: list[Element], parent_id: int | None = None) -> None:
    for e in elements:
        eid = _un(conn, "INSERT INTO assistant.parcours_elements (version_id, parent_id, type, groupe, ordre, titre, "
                        "texte, texte_source, montant_dt, unite_montant, url) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                  (version_id, parent_id, e.type, e.groupe, e.ordre, e.titre, e.texte, e.texte,
                   e.montant_dt, e.unite_montant, e.url))
        _inserer_elements(conn, version_id, e.enfants, eid)


def _ecrire(conn, dossier: Path, cat: Catalogue, r: Rapport) -> None:
    sources = {s.cle: _source(conn, s) for s in cat.sources}

    services: dict[str, int] = {}
    for s in cat.services:
        row = conn.execute("SELECT id, nom FROM assistant.services WHERE code = %s", (s.code,)).fetchone()
        if row is None:
            services[s.code] = _un(conn, "INSERT INTO assistant.services (code, nom, besoin, ordre) "
                                         "VALUES (%s, %s, %s, %s) RETURNING id", (s.code, s.nom, s.besoin, s.ordre))
        else:
            services[s.code] = row[0]
            if row[1] != s.nom:
                r.avertissements.append(f"service {s.code} : nom en base « {row[1]} » conservé (catalogue : « {s.nom} »)")

    for f in r.fiches:
        p, fiche = f.parcours, f.fiche
        pid = _un(conn, "SELECT id FROM assistant.parcours WHERE code = %s", (p.code,))
        if pid is None:
            pid = _un(conn, "INSERT INTO assistant.parcours (service_id, code, titre, critere_choix, ordre) "
                            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                      (services[p.service], p.code, fiche.titre, p.critere_choix, p.ordre))
        meta = fiche.metadonnees
        dv = _version_document(
            conn, source_id=sources[p.source], cle=p.fichier, title=fiche.titre or p.code, type_="fiche_service",
            langue=meta.get("language"), chemin=f"{dossier.name}/{p.fichier}", sha=f.sha256,
            media_type="text/markdown",
            full_text=f.texte, provenance=meta.get("content_provenance"),
            recupere_le=date.fromisoformat(meta["retrieval_date"]) if meta.get("retrieval_date") else None)
        derniere = conn.execute("SELECT document_version_id FROM assistant.parcours_versions WHERE parcours_id = %s "
                                "AND origine = 'import' ORDER BY numero DESC LIMIT 1", (pid,)).fetchone()
        if derniere and derniere[0] == dv:
            r.inchangees.append(p.code)
            continue
        numero = _un(conn, "SELECT coalesce(max(numero), 0) + 1 FROM assistant.parcours_versions WHERE parcours_id = %s",
                     (pid,))
        vid = _un(conn, "INSERT INTO assistant.parcours_versions (parcours_id, numero, origine, document_version_id, "
                        "cree_par, note) VALUES (%s, %s, 'import', %s, %s, %s) RETURNING id",
                  (pid, numero, dv, AUTEUR_IMPORT, "Import automatique : à relire avant publication"))
        _inserer_elements(conn, vid, fiche.elements)
        r.versions_creees.append(p.code)

    formulaires: dict[str, int] = {}
    for fo in cat.formulaires:
        fid = _un(conn, "SELECT id FROM assistant.formulaires WHERE code = %s", (fo.code,))
        if fid is None:
            fid = _un(conn, "INSERT INTO assistant.formulaires (code, titre) VALUES (%s, %s) RETURNING id",
                      (fo.code, fo.titre))
        formulaires[fo.code] = fid
        for v in fo.variantes:
            chemin = dossier / v.fichier
            src = next(s for s in cat.sources if s.cle == v.source)
            dv = _version_document(
                conn, source_id=sources[v.source], cle=v.fichier, title=v.titre_officiel, type_="formulaire",
                langue=v.langue, chemin=f"{dossier.name}/{v.fichier}", sha=_sha256(chemin),
                media_type="application/pdf", full_text=None,
                provenance=v.provenance, recupere_le=cat.date)
            existe = conn.execute("SELECT document_version_id FROM assistant.formulaire_variantes "
                                  "WHERE formulaire_id = %s AND langue = %s", (fid, v.langue)).fetchone()
            if existe is None:
                conn.execute("INSERT INTO assistant.formulaire_variantes (formulaire_id, langue, titre_officiel, "
                             "document_version_id, url_page, url_fichier) VALUES (%s, %s, %s, %s, %s, %s)",
                             (fid, v.langue, v.titre_officiel, dv, src.url, v.url_fichier))
            elif existe[0] != dv:
                r.avertissements.append(f"formulaire {fo.code}/{v.langue} : nouveau fichier enregistré, "
                                        "la variante en base garde l'ancien (à mettre à jour par l'admin)")

    for lien in cat.parcours_formulaires:
        pid = _un(conn, "SELECT id FROM assistant.parcours WHERE code = %s", (lien.parcours,))
        conn.execute("INSERT INTO assistant.parcours_formulaires (parcours_id, formulaire_id, valeurs_imposees, "
                     "a_verifier, note_verification) VALUES (%s, %s, %s, %s, %s) "
                     "ON CONFLICT (parcours_id, formulaire_id) DO NOTHING",
                     (pid, formulaires[lien.formulaire], Jsonb(lien.valeurs_imposees),
                      lien.note_verification is not None, lien.note_verification))


def importer(conninfo: str, dossier: Path, appliquer: bool = False) -> Rapport:
    cat = charger_catalogue(dossier)
    r = lire_corpus(dossier, cat)
    r.appliquer = appliquer
    if not appliquer:
        return r
    principale = next(s for s in cat.sources if s.cle == cat.parcours[0].source)

    def journaliser_echec(conn) -> int:
        # Un échec n'écrit aucune donnée : seulement sa trace (source existante ou null).
        sid = _un(conn, "SELECT id FROM assistant.sources WHERE url = %s", (principale.url,)) if principale.url else None
        rid = _un(conn, "INSERT INTO assistant.ingestion_runs (source_id, status, error, finished_at) "
                        "VALUES (%s, 'echec', %s, now()) RETURNING id", (sid, "\n".join(r.erreurs)))
        conn.commit()
        return rid

    with psycopg.connect(conninfo) as conn:
        if not r.ok:
            r.run_id = journaliser_echec(conn)
            return r
        try:
            with conn.transaction():
                _ecrire(conn, dossier, cat, r)
                r.run_id = _un(conn, "INSERT INTO assistant.ingestion_runs (source_id, status, counts, finished_at) "
                                     "VALUES (%s, 'reussi', %s, now()) RETURNING id",
                               (_source(conn, principale), Jsonb(r.compteurs())))
        except Exception as exc:  # tout est annulé ; l'échec est journalisé à part
            r.erreurs.append(f"écriture annulée : {type(exc).__name__}: {exc}")
            r.versions_creees, r.inchangees = [], []
            r.run_id = journaliser_echec(conn)
    return r
