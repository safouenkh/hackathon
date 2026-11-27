"""Lecture d'une fiche de service AFI au format Markdown (corpus afi-services-markdown).

Le texte n'est ni reformulé ni résumé : chaque élément garde le texte de sa ligne, mise en
forme Markdown comprise (gras, liens). Seuls sont retirés les marqueurs de liste (« 1. »,
« - », « **1)** »). Les numérotations atypiques du texte restent dans le texte.

Une fiche mal formée (section inconnue, métadonnée obligatoire absente) est refusée avec
la liste de ses erreurs : jamais d'import silencieux d'un document douteux.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Section « ## … » -> type d'élément en base
SECTIONS = {
    "description": "description",
    "pour qui / dans quels cas": "pour_qui",
    "conditions": "condition",
    "etapes": "etape",
    "documents requis": "piece",
    "formulaires et liens": "lien",
}
METADONNEES_OBLIGATOIRES = ("service", "source_url", "language")

_TITRE1 = re.compile(r"^#\s+(.+?)\s*$")
_SECTION = re.compile(r"^##\s+(.+?)\s*$")
_GROUPE = re.compile(r"^###\s+(.+?)\s*$")
_ENFANT = re.compile(r"^(\s{2,}|\t+)(?:[-*]|\d{1,2}[.)])\s+(.*)$")
_MARQUEURS = (
    re.compile(r"^[-*]\s+(.*)$"),
    re.compile(r"^\d{1,2}[.)]\s+(.*)$"),
    re.compile(r"^\*\*\s*\d{1,2}\s*[.)]\s*\*\*\s*(.*)$"),
)
_GRAS_DEBUT = re.compile(r"^\*\*(.+?)\*\*")
_LIEN = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
_MONTANT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:dinars?\b|DT\b)", re.I)
_PAR_COPIE = re.compile(r"^\s*(?:tunisiens\s*)?(?:\(DT\)\s*)?par\s+copie", re.I)


@dataclass
class Element:
    type: str
    ordre: int
    texte: str
    groupe: str | None = None
    titre: str | None = None
    url: str | None = None
    montant_dt: float | None = None
    unite_montant: str | None = None
    enfants: list["Element"] = field(default_factory=list)


@dataclass
class Fiche:
    metadonnees: dict[str, str | None]
    titre: str | None
    elements: list[Element]
    erreurs: list[str]
    avertissements: list[str]

    @property
    def valide(self) -> bool:
        return not self.erreurs

    def compter(self) -> dict[str, int]:
        n: dict[str, int] = {}
        for e in self.tous():
            n[e.type] = n.get(e.type, 0) + 1
        return n

    def tous(self):
        def parcourir(liste):
            for e in liste:
                yield e
                yield from parcourir(e.enfants)
        yield from parcourir(self.elements)


def _cle_section(titre: str) -> str:
    t = unicodedata.normalize("NFKD", titre)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", t).strip().rstrip(":").strip()


def _valeur(brute: str) -> str | None:
    v = brute.strip()
    if v == "null" or v == "":
        return None
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1]
    return v


def _metadonnees(lignes: list[str]) -> tuple[dict[str, str | None], list[str]]:
    if not lignes or lignes[0].strip() != "---":
        return {}, lignes
    for i in range(1, len(lignes)):
        if lignes[i].strip() == "---":
            meta = {}
            for l in lignes[1:i]:
                if ":" in l:
                    k, v = l.split(":", 1)
                    meta[k.strip()] = _valeur(v)
            return meta, lignes[i + 1:]
    return {}, lignes


def _texte_et_titre(brut: str) -> tuple[str, str | None, str | None]:
    texte = brut.strip()
    titre = None
    m = _GRAS_DEBUT.match(texte)
    if m:
        t = m.group(1).strip().rstrip(":").strip()
        if t and not re.fullmatch(r"[\d\s.)]+", t):
            titre = t
    lien = _LIEN.search(texte)
    return texte, titre, lien.group(1) if lien else None


def _montants(texte: str) -> list[tuple[float, str | None]]:
    res = []
    for m in _MONTANT.finditer(texte):
        unite = "par copie" if _PAR_COPIE.match(texte[m.end():]) else None
        res.append((float(m.group(1).replace(",", ".")), unite))
    return res


def lire(texte_md: str) -> Fiche:
    lignes = texte_md.splitlines()
    meta, corps = _metadonnees(lignes)
    erreurs = [f"métadonnée obligatoire absente : {k}" for k in METADONNEES_OBLIGATOIRES if not meta.get(k)]
    avert: list[str] = []
    titre = None
    elements: list[Element] = []
    type_courant: str | None = None
    groupe: str | None = None
    compteurs: dict[str, int] = {}
    pile: list[tuple[int, Element]] = []      # (retrait, élément) : chaîne des parents ouverts
    contenu_section: dict[str, bool] = {}

    for n, ligne in enumerate(corps, start=1):
        if not ligne.strip():
            continue
        if m := _TITRE1.match(ligne):
            titre = m.group(1)
            continue
        if m := _SECTION.match(ligne):
            cle = _cle_section(m.group(1))
            type_courant = SECTIONS.get(cle)
            if type_courant is None:
                erreurs.append(f"section inconnue : « {m.group(1)} »")
            else:
                contenu_section.setdefault(type_courant, False)
            groupe, pile = None, []
            continue
        if m := _GROUPE.match(ligne):
            groupe, pile = m.group(1).strip(), []
            continue
        if type_courant is None:
            if titre is not None and ligne.strip():
                erreurs.append(f"texte hors section : « {ligne.strip()[:60]} »")
            continue
        if ligne.strip() == "null":
            continue
        contenu_section[type_courant] = True
        if (m := _ENFANT.match(ligne)) and pile:
            retrait = len(m.group(1).expandtabs(4))
            while pile and pile[-1][0] >= retrait:
                pile.pop()
            if pile:
                parent = pile[-1][1]
                texte, t, url = _texte_et_titre(m.group(2))
                enfant = Element(type=type_courant, ordre=len(parent.enfants) + 1, texte=texte,
                                 groupe=groupe, titre=t, url=url)
                parent.enfants.append(enfant)
                pile.append((retrait, enfant))
                continue
        brut = ligne.strip()
        for marqueur in _MARQUEURS:
            if mm := marqueur.match(brut):
                brut = mm.group(1)
                break
        texte, t, url = _texte_et_titre(brut)
        if not texte:
            continue
        compteurs[type_courant] = compteurs.get(type_courant, 0) + 1
        haut = Element(type=type_courant, ordre=compteurs[type_courant], texte=texte, groupe=groupe,
                       titre=t, url=url)
        elements.append(haut)
        pile = [(0, haut)]

    if titre is None:
        erreurs.append("titre « # » absent")
    for t, plein in contenu_section.items():
        if not plein:
            avert.append(f"section vide (null) : {t}")

    # Montants cités en dinars : index vers le texte d'origine, un par (montant, unité)
    vus: set[tuple[float, str | None]] = set()
    for x in list(Fiche({}, None, elements, [], []).tous()):
        for montant, unite in _montants(x.texte):
            if (montant, unite) in vus:
                continue
            vus.add((montant, unite))
            elements.append(Element(type="frais", ordre=len(vus), texte=x.texte,
                                    groupe="Montants cités dans la fiche", montant_dt=montant,
                                    unite_montant=unite))
    return Fiche(meta, titre, elements, erreurs, avert)
