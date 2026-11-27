"""Formulaires préremplis (BF11) : page du formulaire, préremplissage, envoi d'une demande, et
besoins non couverts (BF24).

- Tout vient de la base : champs, libellés officiels, mentions, valeurs imposées par le parcours,
  et lien entre une donnée du backend et un champ (`prerempli_depuis`).
- Seuls les champs « projet » sont préremplis ou acceptés dans `valeurs`. Le contact est saisi sur
  la page, envoyé seulement avec l'accord du client, et n'est jamais demandé dans le chat.
  CIN, passeport et signature ne sont jamais acceptés (et la base les refuse aussi).
- « Envoyer » enregistre la demande pour l'AFI : ce n'est pas le dépôt officiel.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlencode

from sqlalchemy import Connection
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.config import get_settings
from app.db import EcritureIndisponible, get_engine_ecriture
from app.processing.lots import _PRIX_EXCLUS, _connexion, construire_lot
from app.processing.reference import GOUVERNORATS, gouv_id_depuis_nom
from app.processing.schemas import (
    Avertissement, ChampACompleter, ChampPage, ChoixPage, CodeAvertissement as C, Consentement, DemandeEnvoyee,
    EnvoiDemande, FormulairePage, FormulairePrerempli, Lot, MentionPage, NoterBesoinDonnees, NoterBesoinEntree,
    Projet, SectionPage, SortieOutil,
)
from app.repositories import afi as repo
from app.repositories import assistant as repo_assistant
from app.repositories import ecriture as repo_ecriture
from app.semantique.ontologie import ontologie

log = logging.getLogger(__name__)

_LONGUEUR_MAX = {"texte": 200, "texte_long": 2000, "nombre": 30, "montant": 30, "date": 10}
_NOMBRE_RE = re.compile(r"^\d[\d  .,]*$")
_CONTROLE_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ALPHABET_REFERENCE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sans 0/O ni 1/I


class FormulaireIntrouvable(LookupError):
    """Parcours inconnu, non publié, ou sans formulaire."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class DemandeRefusee(ValueError):
    def __init__(self, code: str, champ: str | None = None):
        super().__init__(f"{code}{f' : {champ}' if champ else ''}")
        self.code, self.champ = code, champ


# ---------------------------------------------------------------------
# Consentement (texte de l'équipe, versionné, dans consentement.json)
# ---------------------------------------------------------------------

@lru_cache
def _consentements() -> dict:
    return json.loads(Path(__file__).with_name("consentement.json").read_text(encoding="utf-8"))


def consentement(*langues: str | None) -> Consentement:
    """Texte dans la première langue disponible parmi `langues`, sinon en français."""
    c = _consentements()
    langue = next((l for l in langues if l in c["textes"]), "fr")
    return Consentement(version=c["version"], texte=c["textes"][langue])


# ---------------------------------------------------------------------
# Structure d'un formulaire (lue en base)
# ---------------------------------------------------------------------

@dataclass
class _Champ:
    code: str
    section: str | None
    type: str
    categorie: str
    unite: str | None
    obligatoire: bool | None
    choix: list[dict] | None
    prerempli_depuis: list[str]
    libelles: dict[str, dict] = field(default_factory=dict)   # langue -> {libelle, officiel, aide}

    def libelle_officiel(self, langue: str) -> str | None:
        l = self.libelles.get(langue)
        return l["libelle"] if l and l["officiel"] else None


@dataclass
class _Structure:
    parcours: dict
    formulaire: dict                    # id, code, valeurs_imposees, a_verifier, note_verification
    variantes: dict[str, dict]          # langue -> titre_officiel, url_fichier, url_page
    champs: list[_Champ]
    sections: list[tuple[str, dict[str, str]]]   # (code, langue -> libellé)


def _structure(c: Connection, parcours_code: str) -> _Structure:
    parcours = repo_assistant.parcours_publies(c, parcours=parcours_code)
    if not parcours:
        raise FormulaireIntrouvable("parcours_inconnu")
    p = parcours[0]
    lignes = repo_assistant.formulaires(c, [p["id"]])
    if not lignes:
        raise FormulaireIntrouvable("formulaire_indisponible")
    f = lignes[0]
    variantes = {l["langue"]: l for l in lignes if l["formulaire_id"] == f["formulaire_id"] and l["langue"]}
    champs: dict[str, _Champ] = {}
    for r in repo_assistant.champs_formulaire(c, f["formulaire_id"]):
        ch = champs.setdefault(r["code"], _Champ(
            r["code"], r["section"], r["type"], r["categorie_donnee"], r["unite"], r["obligatoire"], r["choix"],
            list(r["prerempli_depuis"] or [])))
        if r["langue"]:
            ch.libelles[r["langue"]] = {"libelle": r["libelle"], "officiel": r["officiel"], "aide": r["aide"]}
    sections: dict[str, dict[str, str]] = {}
    for r in repo_assistant.sections_formulaire(c, f["formulaire_id"]):
        sections.setdefault(r["code"], {})
        if r["langue"]:
            sections[r["code"]][r["langue"]] = r["libelle"]
    if not champs:
        raise FormulaireIntrouvable("formulaire_indisponible")
    return _Structure(p, f, variantes, list(champs.values()), list(sections.items()))


# ---------------------------------------------------------------------
# Préremplissage
# ---------------------------------------------------------------------

def normaliser_projet(projet: Projet) -> tuple[Projet, list[Avertissement]]:
    if not projet.gouvernorat:
        return projet, []
    gid = gouv_id_depuis_nom(projet.gouvernorat)
    if gid is None:
        return projet.model_copy(update={"gouvernorat": None}), [
            Avertissement(code=C.gouvernorat_non_reconnu, detail=projet.gouvernorat)]
    return projet.model_copy(update={"gouvernorat": GOUVERNORATS[gid]}), []


def _depuis(cle: str, lots: list[Lot], projet: Projet) -> tuple[str | None, bool]:
    """Valeur d'une clé de `prerempli_depuis` ; le booléen dit si elle est ambiguë (lots différents)."""
    source, attribut = cle.split(".", 1)
    if source == "projet":
        v = getattr(projet, attribut)
        if v is None:
            return None, False
        return (f"{v} m²" if attribut.endswith("_m2") else str(v)), False
    if not lots:
        return None, False
    if attribut == "surface_m2":
        surfaces = [l.surface_m2 for l in lots]
        return (f"{sum(surfaces)} m²" if None not in surfaces else None), False
    if attribut == "numero" and len(lots) > 1:
        return None, True
    valeurs = [getattr(l, attribut) for l in lots]
    if None in valeurs:
        return None, False
    distinctes = set(valeurs)
    return (str(valeurs[0]), False) if len(distinctes) == 1 else (None, True)


def preremplir(champs: list[_Champ], imposees: dict, lots: list[Lot], projet: Projet
               ) -> tuple[dict[str, tuple[str, str]], list[Avertissement]]:
    """code -> (valeur, origine) pour les champs « projet » ; les valeurs imposées par le parcours gagnent."""
    valeurs: dict[str, tuple[str, str]] = {}
    avert: list[Avertissement] = []
    for ch in champs:
        if ch.categorie != "projet":
            continue
        if ch.code in imposees:
            valeurs[ch.code] = (str(imposees[ch.code]), "parcours")
            continue
        ambigu = False
        for cle in ch.prerempli_depuis:
            v, amb = _depuis(cle, lots, projet)
            ambigu |= amb
            if v is not None:
                valeurs[ch.code] = (v, cle)
                break
        if ch.code not in valeurs and ambigu:
            avert.append(Avertissement(code=C.valeur_non_preremplie, detail=ch.code))
    return valeurs, avert


def _lots(c: Connection, lot_ids: list[int], service: str) -> tuple[list[Lot], list[Avertissement]]:
    ids = list(dict.fromkeys(lot_ids))
    if not ids:
        return [], []
    trouves = {l.lot_id: construire_lot(l) for l in repo.lots_par_ids(c, ids, _PRIX_EXCLUS)}
    avert = [Avertissement(code=C.lot_introuvable, lot_id=i) for i in ids if i not in trouves]
    lots = [trouves[i] for i in ids if i in trouves]
    requis = ontologie().service(service).exige_statut_lot
    for lot in lots:
        if requis and lot.statut.value != requis:
            avert.append(Avertissement(code=C.lot_non_disponible, lot_id=lot.lot_id, detail=lot.statut.value))
        avert += [Avertissement(code=code, lot_id=lot.lot_id) for code in lot.avertissements]
    return lots, avert


def url_page(parcours: str, langue: str, lot_ids: list[int], projet: Projet) -> str:
    """Lien vers la page du formulaire : seulement des données du projet, jamais de contact."""
    params = [("langue", langue)] + [("lots", str(i)) for i in lot_ids]
    params += [(k, str(v)) for k, v in projet.model_dump().items() if v is not None]
    return f"{get_settings().frontend_base_url.rstrip('/')}/formulaire/{parcours}?{urlencode(params)}"


def formulaires_preremplis(c: Connection, parcours_codes: list[str], lots: list[Lot], projet: Projet
                           ) -> tuple[list[FormulairePrerempli], list[Avertissement]]:
    """Pour preparer_demande : une page préremplie par parcours et par langue officielle."""
    sortie, avert = [], []
    for code in parcours_codes:
        try:
            s = _structure(c, code)
        except FormulaireIntrouvable as exc:
            avert.append(Avertissement(code=C.formulaire_indisponible, detail=code))
            log.debug("pas de formulaire pour %s : %s", code, exc.code)
            continue
        valeurs, a = preremplir(s.champs, s.formulaire["valeurs_imposees"] or {}, lots, projet)
        avert += a
        for langue in sorted(s.variantes):
            projet_langue = [ch for ch in s.champs if ch.categorie == "projet" and ch.libelle_officiel(langue)]
            sortie.append(FormulairePrerempli(
                parcours=code, formulaire=s.formulaire["code"], langue=langue,
                url_page=url_page(code, langue, [l.lot_id for l in lots], projet),
                valeurs={ch.code: valeurs[ch.code][0] for ch in projet_langue if ch.code in valeurs},
                champs_projet_a_completer=[ChampACompleter(code=ch.code, libelle=ch.libelle_officiel(langue))
                                           for ch in projet_langue if ch.code not in valeurs]))
    return sortie, avert


# ---------------------------------------------------------------------
# Page du formulaire (front)
# ---------------------------------------------------------------------

def page_formulaire(parcours: str, langue: str | None, langue_aide: str | None, lot_ids: list[int],
                    projet: Projet, conn: Connection | None = None) -> FormulairePage:
    with _connexion(conn) as c:
        s = _structure(c, parcours)
        langues = sorted(s.variantes)
        langue = langue or (langue_aide if langue_aide in langues else langues[0])
        if langue not in s.variantes:
            raise FormulaireIntrouvable("langue_indisponible")
        projet, avert = normaliser_projet(projet)
        lots, a = _lots(c, lot_ids, s.parcours["service"])
        avert += a
        mentions = repo_assistant.mentions_formulaire(c, s.formulaire["formulaire_id"], langue)
    aide = langue_aide if langue_aide and langue_aide != langue else None
    valeurs, a = preremplir(s.champs, s.formulaire["valeurs_imposees"] or {}, lots, projet)
    avert = [Avertissement(code=C.confirmation_requise)] + avert + a
    if s.formulaire["a_verifier"]:
        avert.append(Avertissement(code=C.point_a_verifier, detail=s.formulaire["note_verification"]))

    sections = []
    for code, libelles in s.sections:
        champs = []
        for ch in s.champs:
            libelle = ch.libelle_officiel(langue)
            if ch.section != code or not libelle:
                continue        # un champ absent de cette variante officielle n'est pas affiché
            trad = ch.libelles.get(aide) if aide else None
            v = valeurs.get(ch.code)
            champs.append(ChampPage(
                code=ch.code, type=ch.type, categorie=ch.categorie, unite=ch.unite, obligatoire=ch.obligatoire,
                libelle=libelle, aide=ch.libelles[langue]["aide"],
                traduction=trad["libelle"] if trad else None, traduction_officielle=trad["officiel"] if trad else None,
                choix=[ChoixPage(valeur=x["valeur"], libelle=x["libelles"].get(langue),
                                 traduction=x["libelles"].get(aide) if aide else None) for x in ch.choix]
                if ch.choix is not None else None,
                valeur=v[0] if v else None, origine_valeur=v[1] if v else None,
                impose=bool(v and v[1] == "parcours")))
        ments = [MentionPage(texte=m["texte"], si_champ=m["si_champ"], si_valeur=m["si_valeur"])
                 for m in mentions if m["section"] == code]
        if champs or ments or libelles.get(langue):
            sections.append(SectionPage(code=code, libelle=libelles.get(langue),
                                        traduction=libelles.get(aide) if aide else None,
                                        champs=champs, mentions=ments))
    v = s.variantes[langue]
    return FormulairePage(
        parcours=s.parcours["code"], parcours_titre=s.parcours["titre"], service=s.parcours["service"],
        version=s.parcours["numero"], formulaire=s.formulaire["code"], titre_officiel=v["titre_officiel"],
        langue=langue, langues=langues, langue_aide=aide, url_fichier=v["url_fichier"],
        url_source=s.parcours["url_source"], sections=sections, lots=lots, avertissements=avert,
        note_verification=s.formulaire["note_verification"], consentement=consentement(aide, langue))


# ---------------------------------------------------------------------
# Envoi d'une demande (après relecture et accord du client)
# ---------------------------------------------------------------------

def _valeur_valide(ch: _Champ, brute: str) -> str:
    v = brute.strip()
    if _CONTROLE_RE.search(v) or (ch.type != "texte_long" and "\n" in v):
        raise DemandeRefusee("valeur_invalide", ch.code)
    if len(v) > _LONGUEUR_MAX.get(ch.type, 200):
        raise DemandeRefusee("valeur_trop_longue", ch.code)
    if ch.type in ("nombre", "montant") and not _NOMBRE_RE.match(v):
        raise DemandeRefusee("nombre_attendu", ch.code)
    if ch.type == "date":
        try:
            date.fromisoformat(v)
        except ValueError:
            raise DemandeRefusee("date_attendue", ch.code) from None
    if ch.choix is not None:
        permis = {x["valeur"] for x in ch.choix}
        choisis = [x.strip() for x in v.split(",")] if ch.type == "choix_multiple" else [v]
        if not set(choisis) <= permis:
            raise DemandeRefusee("choix_inconnu", ch.code)
    return v


def _trier(champs: dict[str, _Champ], brutes: dict[str, str], categorie: str, langue: str) -> dict[str, str]:
    propres = {}
    for code, brute in brutes.items():
        ch = champs.get(code)
        if ch is None or ch.categorie != categorie or not ch.libelle_officiel(langue):
            raise DemandeRefusee("champ_refuse", code)     # CIN, signature, réservé AFI, autre catégorie…
        v = _valeur_valide(ch, brute)
        if v:
            propres[code] = v
    return propres


def _reference() -> str:
    tirage = "".join(secrets.choice(_ALPHABET_REFERENCE) for _ in range(8))
    return f"{tirage[:4]}-{tirage[4:]}"


def envoyer_demande(e: EnvoiDemande, conn: Connection | None = None) -> DemandeEnvoyee:
    with _connexion(conn) as c:
        try:
            s = _structure(c, e.parcours)
        except FormulaireIntrouvable as exc:
            raise DemandeRefusee(exc.code) from None
        if e.langue not in s.variantes:
            raise DemandeRefusee("langue_indisponible")
        champs = {ch.code: ch for ch in s.champs}
        valeurs = _trier(champs, e.valeurs, "projet", e.langue)
        contact = _trier(champs, e.contact, "contact", e.langue)
        for code, v in (s.formulaire["valeurs_imposees"] or {}).items():
            if code in valeurs and valeurs[code] != str(v):
                raise DemandeRefusee("valeur_imposee", code)
            valeurs[code] = str(v)
        if not contact:
            raise DemandeRefusee("contact_requis")
        accord = consentement(e.langue_aide, e.langue)
        if not e.consentement or e.consentement_version != accord.version:
            raise DemandeRefusee("consentement_requis")
        lot_ids = list(dict.fromkeys(e.lot_ids))
        if lot_ids:
            connus = {l.lot_id for l in repo.lots_par_ids(c, lot_ids, _PRIX_EXCLUS)}
            inconnus = [i for i in lot_ids if i not in connus]
            if inconnus:
                raise DemandeRefusee("lot_introuvable", ",".join(map(str, inconnus)))

    moteur = get_engine_ecriture()
    for _ in range(3):
        reference = _reference()
        try:
            with moteur.begin() as w:
                did, le = repo_ecriture.inserer_demande(
                    w, reference=reference, parcours_id=s.parcours["id"], version_id=s.parcours["version_id"],
                    formulaire_id=s.formulaire["formulaire_id"], langue=e.langue, lot_ids=lot_ids, valeurs=valeurs)
                repo_ecriture.inserer_contact(w, demande_id=did, valeurs=contact, consentement_texte=accord.texte)
            return DemandeEnvoyee(reference=reference, envoyee_le=le)
        except IntegrityError as exc:
            if "reference" not in str(exc.orig):
                raise
    raise RuntimeError("référence unique introuvable après 3 essais")


# ---------------------------------------------------------------------
# BF24 : question hors des services
# ---------------------------------------------------------------------

def noter_besoin(entree: NoterBesoinEntree, conn: Connection | None = None) -> SortieOutil[NoterBesoinDonnees]:
    note = True
    try:
        with get_engine_ecriture().begin() as w:
            repo_ecriture.inserer_besoin(w, question=entree.question.strip(), langue=entree.langue)
    except (EcritureIndisponible, SQLAlchemyError):
        log.exception("besoin non couvert : enregistrement impossible")
        note = False
    return SortieOutil[NoterBesoinDonnees](outil="noter_besoin", donnees=NoterBesoinDonnees(note=note),
                                           provenance=[], avertissements=[], balises=[])
