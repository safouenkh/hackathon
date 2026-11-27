"""Corrections et signalements sourcés des brouillons (`corrections.json` du corpus).

Trois actions, toutes marquées « à vérifier » avec leur preuve :
- remplacer : nouveau texte, le texte d'origine reste dans `texte_source` ;
- ajouter   : élément absent de la fiche (`texte_source` nul) ;
- signaler  : le texte ne change pas, seule une note est ajoutée.

Garanties : tout ou rien ; seuls les brouillons changent ; un texte ou une note déjà modifiés
par quelqu'un d'autre ne sont pas écrasés ; chaque citation doit se trouver dans la page
enregistrée comme preuve, dont l'empreinte est contrôlée.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal

import psycopg
from pydantic import model_validator

from app.sources.import_services import SourceCat, _source, _Strict, _un, _version_document
from app.sources.publication import brouillons


class Preuve(_Strict):
    cle: str
    organisation: str
    title: str
    url: str
    langue: str
    fichier: str
    sha256: str
    collecte: date


class Correction(_Strict):
    action: Literal["remplacer", "ajouter", "signaler"]
    parcours: str
    type: str
    avant: str | None = None
    apres: str | None = None
    note: str
    preuve: str
    citation: str

    @model_validator(mode="after")
    def _textes(self) -> "Correction":
        if (self.avant is None) != (self.action == "ajouter"):
            raise ValueError(f"{self.parcours} : « avant » requis sauf pour « ajouter »")
        if (self.apres is None) != (self.action == "signaler"):
            raise ValueError(f"{self.parcours} : « apres » requis sauf pour « signaler »")
        return self


class FichierCorrections(_Strict):
    version: int
    description: str
    date: date
    decision: str
    preuves: list[Preuve]
    corrections: list[Correction]


@dataclass
class RapportCorrections:
    appliquer: bool
    erreurs: list[str] = field(default_factory=list)
    faites: list[str] = field(default_factory=list)
    deja_faites: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.erreurs


class _Texte(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.morceaux: list[str] = []

    def handle_data(self, data: str) -> None:
        self.morceaux.append(data)


def _compacter(texte: str) -> str:
    return " ".join(texte.split())


def _controler_preuves(dossier: Path, f: FichierCorrections, erreurs: list[str]) -> None:
    textes: dict[str, str] = {}
    for p in f.preuves:
        chemin = dossier / p.fichier
        if not chemin.is_file():
            erreurs.append(f"preuve {p.cle} : fichier absent {p.fichier}")
            continue
        octets = chemin.read_bytes()
        if hashlib.sha256(octets).hexdigest() != p.sha256:
            erreurs.append(f"preuve {p.cle} : SHA-256 différent (page enregistrée modifiée)")
            continue
        lecteur = _Texte()
        lecteur.feed(octets.decode("utf-8"))
        textes[p.cle] = _compacter("".join(lecteur.morceaux))
    for c in f.corrections:
        if c.preuve not in {p.cle for p in f.preuves}:
            erreurs.append(f"{c.parcours} : preuve inconnue {c.preuve}")
        elif c.preuve in textes and _compacter(c.citation) not in textes[c.preuve]:
            erreurs.append(f"{c.parcours} : citation absente de la page {c.preuve} : « {c.citation} »")


def _appliquer_une(conn, version_id: int, c: Correction, note: str, r: RapportCorrections) -> None:
    libelle = f"{c.parcours} : {c.action} ({c.type}) « {(c.apres or c.avant)[:70]} »"

    if c.action == "ajouter":
        deja = conn.execute("SELECT texte FROM assistant.parcours_elements WHERE version_id = %s AND type = %s "
                            "AND texte_source IS NULL AND (texte = %s OR note_verification = %s)",
                            (version_id, c.type, c.apres, note)).fetchone()
        if deja:
            if deja[0] == c.apres:
                r.deja_faites.append(libelle)
            else:
                r.erreurs.append(f"{libelle} : élément ajouté puis modifié par ailleurs, non écrasé")
            return
        ordre = _un(conn, "SELECT coalesce(max(ordre), 0) + 1 FROM assistant.parcours_elements WHERE version_id = %s "
                          "AND type = %s AND parent_id IS NULL AND groupe IS NULL", (version_id, c.type))
        conn.execute("INSERT INTO assistant.parcours_elements (version_id, type, ordre, texte, a_verifier, "
                     "note_verification) VALUES (%s, %s, %s, %s, true, %s)",
                     (version_id, c.type, ordre, c.apres, note))
        r.faites.append(libelle)
        return

    lignes = conn.execute("SELECT id, texte, note_verification FROM assistant.parcours_elements "
                          "WHERE version_id = %s AND type = %s AND texte_source = %s",
                          (version_id, c.type, c.avant)).fetchall()
    if len(lignes) != 1:
        r.erreurs.append(f"{libelle} : texte d'origine {'introuvable' if not lignes else 'présent plusieurs fois'}")
        return
    ident, texte, note_actuelle = lignes[0]
    voulu = c.apres if c.action == "remplacer" else c.avant
    if texte == voulu and note_actuelle == note:
        r.deja_faites.append(libelle)
    elif texte != c.avant or note_actuelle is not None:
        r.erreurs.append(f"{libelle} : texte ou note modifié par ailleurs, non écrasé")
    else:
        conn.execute("UPDATE assistant.parcours_elements SET texte = %s, a_verifier = true, note_verification = %s "
                     "WHERE id = %s", (voulu, note, ident))
        r.faites.append(libelle)


def corriger(conninfo: str, dossier: Path, par: str | None, appliquer: bool = False) -> RapportCorrections:
    """Sans `appliquer`, tout est exécuté puis annulé : le rapport dit ce qui serait fait."""
    if appliquer and not (par or "").strip():
        raise ValueError("indiquer qui valide les corrections (--par)")
    f = FichierCorrections.model_validate_json((dossier / "corrections.json").read_text(encoding="utf-8"))
    r = RapportCorrections(appliquer=appliquer)
    _controler_preuves(dossier, f, r.erreurs)
    if not r.ok:
        return r
    preuves = {p.cle: p for p in f.preuves}
    with psycopg.connect(conninfo) as conn, conn.transaction():
        versions = {b.parcours: b.version_id for b in brouillons(conn)}
        for p in f.preuves:
            source_id = _source(conn, SourceCat(cle=p.cle, organisation=p.organisation, title=p.title,
                                                url=p.url, ingestion_mode="manuel"))
            _version_document(conn, source_id=source_id, cle=p.fichier, title=p.title, type_="page_web",
                              langue=p.langue, chemin=f"{dossier.name}/{p.fichier}", sha=p.sha256,
                              media_type="text/html", full_text=None,
                              provenance="Page publique du site de l'AFI enregistrée comme preuve",
                              recupere_le=p.collecte)
        changees: set[int] = set()
        for c in f.corrections:
            if c.parcours not in versions:
                r.erreurs.append(f"{c.parcours} : aucun brouillon à corriger (une version publiée ne change pas)")
                continue
            note = f"{c.note} — Preuve : {preuves[c.preuve].url} — « {c.citation} »"
            avant = len(r.faites)
            _appliquer_une(conn, versions[c.parcours], c, note, r)
            if len(r.faites) > avant:
                changees.add(versions[c.parcours])
        if changees and r.ok and appliquer:
            mention = f"Corrections et signalements validés par {par.strip()} (corrections.json du {f.date})"
            conn.execute("UPDATE assistant.parcours_versions SET note = concat_ws(' | ', note, %s::text) "
                         "WHERE id = ANY(%s)", (mention, sorted(changees)))
        if not r.ok or not appliquer:
            if not r.ok:
                r.faites = []
            raise psycopg.Rollback()
    return r
