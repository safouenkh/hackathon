"""Import des champs des formulaires officiels (formulaires_champs.json du corpus).

- Le fichier est entièrement contrôlé avant toute écriture (références, catégories, origine de
  chaque libellé) ; une seule erreur arrête l'import.
- Les formulaires et leurs variantes doivent déjà exister (import des services).
- Un formulaire qui a déjà des champs en base n'est pas modifié : ils peuvent avoir été corrigés
  par l'admin ; il est seulement signalé.
- L'écriture se fait en une transaction : tout ou rien.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.sources.import_services import charger_catalogue

FICHIER = "formulaires_champs.json"

SourceTexte = Literal["pdf_texte", "pdf_image", "traduction_equipe"]
TypeChamp = Literal["texte", "texte_long", "nombre", "montant", "date", "choix_unique", "choix_multiple", "case"]
Categorie = Literal["projet", "contact", "non_enregistre", "reserve_afi"]
# Données calculées par le backend (doit rester identique à la contrainte de la migration 0002).
CleePrerempli = Literal["lot.zone_nom", "lot.numero", "lot.surface_m2", "projet.activite", "projet.nombre_emplois",
                        "projet.investissement_dt", "projet.surface_souhaitee_m2", "projet.gouvernorat"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Libelle(_Strict):
    texte: str = Field(min_length=1)
    source: SourceTexte
    page: int | None = Field(default=None, gt=0)
    aide: str | None = None

    @property
    def officiel(self) -> bool:
        return self.source != "traduction_equipe"

    @model_validator(mode="after")
    def _page(self) -> "Libelle":
        if self.source != "traduction_equipe" and self.page is None:
            raise ValueError(f"« {self.texte} » : page obligatoire pour un texte du PDF")
        return self


class Choix(_Strict):
    valeur: str = Field(min_length=1, max_length=50)
    libelles: dict[str, str]


class Section(_Strict):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    ordre: int = Field(ge=0)
    libelles: dict[str, Libelle]


class Champ(_Strict):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    section: str
    ordre: int = Field(ge=0)
    type: TypeChamp
    categorie: Categorie
    unite: str | None = None
    choix: list[Choix] | None = None
    prerempli_depuis: list[CleePrerempli] | None = None
    libelles: dict[str, Libelle] = Field(min_length=1)

    @model_validator(mode="after")
    def _coherence(self) -> "Champ":
        if (self.type in ("choix_unique", "choix_multiple")) != (self.choix is not None):
            raise ValueError(f"{self.code} : des choix sont obligatoires pour un champ à choix, et seulement pour lui")
        if self.prerempli_depuis and self.categorie != "projet":
            raise ValueError(f"{self.code} : seul un champ « projet » peut être prérempli")
        if not any(l.officiel for l in self.libelles.values()):
            raise ValueError(f"{self.code} : aucun libellé officiel")
        for c in self.choix or []:
            manquantes = set(self.libelles) - set(c.libelles)
            if manquantes:
                raise ValueError(f"{self.code} : choix {c.valeur} sans libellé en {sorted(manquantes)}")
        return self


class Condition(_Strict):
    champ: str
    valeur: str


class Mention(_Strict):
    langue: str
    section: str
    ordre: int = Field(ge=0)
    source: Literal["pdf_texte", "pdf_image"]
    page: int = Field(gt=0)
    texte: str = Field(min_length=1)
    si: Condition | None = None


class FormulaireChamps(_Strict):
    code: str
    sections: list[Section]
    champs: list[Champ]
    mentions: list[Mention] = []

    @model_validator(mode="after")
    def _references(self) -> "FormulaireChamps":
        erreurs = []
        for nom, codes in (("sections", [s.code for s in self.sections]), ("champs", [c.code for c in self.champs]),
                           ("ordres des champs", [c.ordre for c in self.champs])):
            if len(codes) != len(set(codes)):
                erreurs.append(f"doublon dans {nom}")
        sections = {s.code for s in self.sections}
        champs = {c.code: c for c in self.champs}
        erreurs += [f"{c.code} : section inconnue {c.section}" for c in self.champs if c.section not in sections]
        cles = [(m.langue, m.section, m.ordre) for m in self.mentions]
        if len(cles) != len(set(cles)):
            erreurs.append("doublon dans les mentions (langue, section, ordre)")
        for m in self.mentions:
            if m.section not in sections:
                erreurs.append(f"mention {m.langue}/{m.ordre} : section inconnue {m.section}")
            if m.si and (m.si.champ not in champs
                         or m.si.valeur not in {c.valeur for c in champs[m.si.champ].choix or []}):
                erreurs.append(f"mention {m.langue}/{m.ordre} : condition inconnue {m.si.champ}={m.si.valeur}")
        if erreurs:
            raise ValueError(f"formulaire {self.code} : " + "; ".join(erreurs))
        return self


class FichierChamps(_Strict):
    version: int
    description: str
    date: date
    statut: str
    formulaires: list[FormulaireChamps]


@dataclass
class RapportFormulaires:
    appliquer: bool
    erreurs: list[str] = field(default_factory=list)
    avertissements: list[str] = field(default_factory=list)
    importes: dict[str, dict[str, int]] = field(default_factory=dict)   # code -> compteurs
    deja_presents: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.erreurs


def lire(dossier: Path) -> tuple[FichierChamps, list[str]]:
    """Lit le fichier et le confronte au catalogue (formulaires et langues des variantes)."""
    fichier = FichierChamps.model_validate_json((dossier / FICHIER).read_text(encoding="utf-8"))
    cat = charger_catalogue(dossier)
    langues = {f.code: {v.langue for v in f.variantes} for f in cat.formulaires}
    erreurs = []
    for f in fichier.formulaires:
        if f.code not in langues:
            erreurs.append(f"formulaire {f.code} absent de catalogue.json")
            continue
        variantes = langues[f.code]
        textes = [(s.code, s.libelles) for s in f.sections] + [(c.code, c.libelles) for c in f.champs]
        erreurs += [f"{f.code}/{code} : libellé officiel en {l} sans variante {l} du formulaire"
                    for code, libs in textes for l, lib in libs.items() if lib.officiel and l not in variantes]
        erreurs += [f"{f.code} : mention en {m.langue} sans variante {m.langue}"
                    for m in f.mentions if m.langue not in variantes]
    codes = [f.code for f in fichier.formulaires]
    if len(codes) != len(set(codes)):
        erreurs.append("formulaire en double")
    return fichier, erreurs


_CATEGORIES = {"projet": "projet (chat ou page)", "contact": "contact (page seulement)",
               "non_enregistre": "**jamais enregistré**", "reserve_afi": "réservé à l'AFI"}
_SOURCES = {"pdf_texte": "texte du PDF ✔", "pdf_image": "**image : à relire**", "traduction_equipe": "traduction"}


def revue_markdown(fichier: FichierChamps) -> str:
    """Tableau de relecture : un champ par ligne, avec catégorie, libellés et origine."""
    lignes = ["# Champs des formulaires : relecture", "",
              f"Fichier `{FICHIER}` du {fichier.date} ({fichier.statut}). Les textes marqués « image : à relire » "
              "ont été recopiés depuis l'image du PDF : à comparer au formulaire papier.", ""]
    for f in fichier.formulaires:
        langues = sorted({l for c in f.champs for l in c.libelles}, key=lambda l: (l != "fr", l))
        lignes += [f"## {f.code}", "", "| Champ | Section | Catégorie | Préremplissage | "
                   + " | ".join(f"Libellé {l}" for l in langues) + " |",
                   "|---|---|---|---|" + "---|" * len(langues)]
        for c in f.champs:
            libs = []
            for l in langues:
                lib = c.libelles.get(l)
                libs.append(f"{lib.texte}{f' ({lib.aide})' if lib.aide else ''} — {_SOURCES[lib.source]}"
                            if lib else "—")
                if lib and c.choix:
                    libs[-1] += "<br>" + " / ".join(ch.libelles[l] for ch in c.choix)
            lignes.append(f"| `{c.code}` | {c.section} | {_CATEGORIES[c.categorie]} | "
                          f"{', '.join(c.prerempli_depuis or []) or '—'} | " + " | ".join(libs) + " |")
        if f.mentions:
            lignes += ["", "Mentions imprimées :", ""]
            lignes += [f"- [{m.langue}, {m.section}{f', si {m.si.champ}={m.si.valeur}' if m.si else ''}] "
                       f"{m.texte} — {_SOURCES[m.source]}" for m in f.mentions]
        lignes.append("")
    return "\n".join(lignes)


def _un(conn, requete: str, params: tuple):
    ligne = conn.execute(requete, params).fetchone()
    return ligne[0] if ligne else None


def _ecrire_formulaire(conn, fid: int, f: FormulaireChamps) -> dict[str, int]:
    for s in f.sections:
        sid = _un(conn, "INSERT INTO assistant.formulaire_sections (formulaire_id, code, ordre) VALUES (%s, %s, %s) "
                        "RETURNING id", (fid, s.code, s.ordre))
        for langue, l in s.libelles.items():
            conn.execute("INSERT INTO assistant.formulaire_section_libelles (section_id, langue, libelle, source_texte, "
                         "page) VALUES (%s, %s, %s, %s, %s)", (sid, langue, l.texte, l.source, l.page))
    for c in f.champs:
        choix = Jsonb([ch.model_dump() for ch in c.choix]) if c.choix is not None else None
        cid = _un(conn, "INSERT INTO assistant.formulaire_champs (formulaire_id, code, section, ordre, type, "
                        "categorie_donnee, choix, unite, prerempli_depuis) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                  (fid, c.code, c.section, c.ordre, c.type, c.categorie, choix, c.unite, c.prerempli_depuis))
        for langue, l in c.libelles.items():
            conn.execute("INSERT INTO assistant.formulaire_champ_libelles (champ_id, langue, libelle, officiel, aide, "
                         "source_texte, page) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                         (cid, langue, l.texte, l.officiel, l.aide, l.source, l.page))
    for m in f.mentions:
        conn.execute("INSERT INTO assistant.formulaire_mentions (formulaire_id, langue, section, ordre, texte, "
                     "source_texte, page, si_champ, si_valeur) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                     (fid, m.langue, m.section, m.ordre, m.texte, m.source, m.page,
                      m.si.champ if m.si else None, m.si.valeur if m.si else None))
    return {"sections": len(f.sections), "champs": len(f.champs),
            "libelles": sum(len(c.libelles) for c in f.champs), "mentions": len(f.mentions)}


def importer(conninfo: str, dossier: Path, appliquer: bool = False) -> RapportFormulaires:
    r = RapportFormulaires(appliquer=appliquer)
    try:
        fichier, erreurs = lire(dossier)
    except ValueError as exc:     # pydantic.ValidationError hérite de ValueError
        r.erreurs.append(str(exc))
        return r
    r.erreurs += erreurs
    if not r.ok:
        return r
    with psycopg.connect(conninfo) as conn:
        try:
            with conn.transaction():
                for f in fichier.formulaires:
                    fid = _un(conn, "SELECT id FROM assistant.formulaires WHERE code = %s", (f.code,))
                    if fid is None:
                        raise LookupError(f"formulaire {f.code} absent de la base : lancer d'abord importer_services")
                    if _un(conn, "SELECT count(*) FROM assistant.formulaire_champs WHERE formulaire_id = %s", (fid,)):
                        r.deja_presents.append(f.code)
                        r.avertissements.append(f"{f.code} : champs déjà en base, non modifiés (à changer par l'admin)")
                        continue
                    r.importes[f.code] = _ecrire_formulaire(conn, fid, f)
                if not appliquer:
                    raise psycopg.Rollback()
        except (LookupError, psycopg.Error) as exc:
            r.erreurs.append(f"écriture annulée : {type(exc).__name__}: {exc}")
            r.importes = {}
    return r
