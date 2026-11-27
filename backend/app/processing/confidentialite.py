"""Masquage des données personnelles AVANT tout envoi à un service externe (cahier BNF9).

Un investisseur peut écrire dans le chat son nom, sa CIN, son téléphone ou son e-mail. Ces
données ne doivent jamais partir vers le LLM : elles se saisissent sur la page du formulaire.
Le texte masqué remplace chaque donnée par une marque (« [téléphone masqué] »), et l'agent dit
à l'investisseur de la saisir sur la page.

Limite connue : filtre par motifs. Il reconnaît les e-mails, les numéros tunisiens, les numéros
d'identité cités après leur intitulé (CIN, passeport…) et les noms annoncés (« esmi … »,
« je m'appelle … »). Un nom donné sans annonce n'est pas reconnu.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MARQUES = {
    "email": "[e-mail masqué]",
    "telephone": "[téléphone masqué]",
    "identite": "[n° d'identité masqué]",
    "nom": "[nom masqué]",
}

_REPERE = chr(0xE000)       # caractère « usage privé » : n'apparaît jamais dans un message réel

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# Numéro tunisien : 8 chiffres commençant par 2, 4, 5, 7 ou 9 (groupés 2-2-2-2 ou 2-3-3), avec ou
# sans +216 / 00216. Un nombre suivi d'une unité ou d'une monnaie (« 20 000 000 DT ») n'en est pas un.
_TEL = re.compile(
    r"(?<![\d.,/])(?:(?:\+|00)216[ .-]?)?[24579]\d(?:[ .-]?\d{3}[ .-]?\d{3}|(?:[ .-]?\d{2}){3})(?!\d)")
_APRES_MONTANT = re.compile(r"\s*(?:dt|dinars?|tnd|alf|million|m²|m2|ha\b|د\.ت|دينار|ألف|الف)", re.I)

# Numéro d'identité cité après son intitulé, ou CIN écrite avec un 0 initial.
_INTITULES = (r"cin|cni|c\.i\.n|carte\s+d['’ ]?identit[ée]|identit[ée]|passeport|passport|bitaqa|jawaz|"
              r"بطاقة\s+(?:ال)?تعريف(?:\s+الوطنية)?|بطاقة\s+الهوية|جواز(?:\s+السفر)?")
_IDENTITE = re.compile(rf"(?i)\b({_INTITULES})([^\d]{{0,25}}?)([A-Z]{{0,2}}\d[\d ]{{5,10}}\d)")
_IDENTITE_ARABE = re.compile(rf"({_INTITULES})([^\d]{{0,25}}?)([A-Z]{{0,2}}\d[\d ]{{5,10}}\d)")
_CIN_ZERO = re.compile(r"(?<![\d.,/])0\d{7}(?!\d)")

_NOM_LATIN = re.compile(
    r"(?i)\b(esmi|ismi|asmi|ismy|je m['’]appelle|my name is|ich hei(?:ß|ss)e|mein name ist|ismim|adım)\s+"
    r"([^\W\d_][\w'’-]*(?:\s+(?-i:[A-ZÀ-ÝÇ])[\w'’-]*){0,2})")
_NOM_ARABE = re.compile(r"(اسمي|إسمي|أنا اسمي)\s+([؀-ۿ]+(?:\s+(?:بن|ابن|بنت)\s+[؀-ۿ]+|\s+[؀-ۿ]+)?)")


@dataclass(frozen=True)
class Masque:
    texte: str
    types: tuple[str, ...]      # ex. ("nom", "telephone"), sans doublon, dans l'ordre d'apparition

    @property
    def modifie(self) -> bool:
        return bool(self.types)


def masquer(texte: str) -> Masque:
    """Remplace par des marques les données personnelles reconnues dans `texte`."""
    trouves: list[str] = []

    def marque(type_: str) -> str:
        # Repère neutre : les motifs suivants ne doivent pas relire une marque déjà posée.
        trouves.append(type_)
        return f"{_REPERE}{len(trouves) - 1}{_REPERE}"

    t = _EMAIL.sub(lambda m: marque("email"), texte)
    t = _IDENTITE.sub(lambda m: f"{m.group(1)}{m.group(2)}{marque('identite')}", t)
    t = _IDENTITE_ARABE.sub(lambda m: f"{m.group(1)}{m.group(2)}{marque('identite')}", t)
    t = _CIN_ZERO.sub(lambda m: marque("identite"), t)

    def tel(m: re.Match) -> str:
        if _APRES_MONTANT.match(m.string, m.end()):
            return m.group(0)
        return marque("telephone")

    t = _TEL.sub(tel, t)
    t = _NOM_LATIN.sub(lambda m: f"{m.group(1)} {marque('nom')}", t)
    t = _NOM_ARABE.sub(lambda m: f"{m.group(1)} {marque('nom')}", t)
    t = re.sub(rf"{_REPERE}(\d+){_REPERE}", lambda m: MARQUES[trouves[int(m.group(1))]], t)
    return Masque(t, tuple(dict.fromkeys(trouves)))
