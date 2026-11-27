"""Outils services AFI : services_afi (orientation, BF22), demarche (fiche, BF23/BF24) et
guider_service (un point à la fois).

Sources, sans rien réécrire :
- versions PUBLIÉES du schéma `assistant` (fiches de la page « Nos services », relues et
  publiées ; corrections sourcées marquées « à vérifier ») : la référence ;
- fiches validées de `afi.chatbot_connaissances` : compléments (explications, contact) ;
- ontologie (ontology/afi_ontology.ttl) : synonymes, liens vers les fiches, vocabulaire du
  lieu de dépôt et des frais.
Aucun service, synonyme ou numéro de fiche n'est écrit ici. Un service hors liste, ou un lieu
de dépôt absent des sources, renvoie au contact de l'AFI, jamais à une démarche inventée.
"""
from __future__ import annotations

import re

from sqlalchemy import Connection

from app.processing.lots import _connexion
from app.processing.reference import normaliser
from app.processing.schemas import (
    Avertissement, Balise, CodeAvertissement as C, ContactAfi, DemarcheDonnees, DemarcheEntree,
    ElementDemarche, EtapePlan, FicheAfi, FormulaireService, GuiderServiceDonnees, GuiderServiceEntree,
    ParcoursDemarche, PointGuide, Provenance, ServiceAfi, ServiceCandidat, ServicesAfiDonnees,
    ServicesAfiEntree, SortieOutil, VarianteFormulaire,
)
from app.repositories import afi as repo
from app.repositories import assistant as repo_assistant
from app.semantique.ontologie import Ontologie, ontologie
from app.sources.fiche_service import _MONTANT

TABLE_CONNAISSANCES = "afi.chatbot_connaissances"
TABLE_VERSIONS = "assistant.parcours_versions"

# ---------- Contact et services ----------


def _contact(c: Connection, onto: Ontologie) -> ContactAfi:
    fid = onto.fiche_contact
    fiche = repo.connaissances(c, [fid]).get(fid) if fid is not None else None
    texte = fiche["reponse"] if fiche else ""
    adresse = re.search(r"Siège de l'Agence Foncière Industrielle\s*:\s*([^.]+)\.", texte)
    tel = re.search(r"téléphone\s*(\+?[\d ]{8,})", texte)
    site = re.search(r"\b(www\.[a-z0-9.-]+\.[a-z]{2,})\b", texte)
    return ContactAfi(adresse=adresse.group(1).strip() if adresse else None,
                      telephone=tel.group(1).strip() if tel else None,
                      site=site.group(1) if site else None, fiche=fid if fiche else None)


def services_par_code(c: Connection, onto: Ontologie) -> dict[str, ServiceAfi]:
    return {s["code"]: ServiceAfi(id=s["code"], nom=s["nom"], besoin=s["besoin"],
                                  fiches=list(onto.service(s["code"]).fiches))
            for s in repo_assistant.services(c)}


def _provenance_fiches(ids: list[int | None]) -> list[Provenance]:
    ids = sorted({i for i in ids if i is not None})
    return [Provenance(type="sql", table=TABLE_CONNAISSANCES, ids=[str(i) for i in ids])] if ids else []


# ---------- services_afi ----------

_ARABE = re.compile(r"[؀-ۿ]")
# Proclitiques arabes collés au mot (و ف ب ل ك + article ال / لل) : « البنك », « للقرض ».
_PREFIXES_AR = r"(?:[وفبلك])?(?:ال|لل)?"


def _present(mot: str, texte: str) -> bool:
    """`mot` et `texte` sont normalisés ; le mot doit être entier."""
    prefixe = _PREFIXES_AR if _ARABE.search(mot) else ""
    return re.search(rf"(?<!\w){prefixe}{re.escape(mot)}(?!\w)", texte) is not None


def _mots_cles(service: ServiceAfi, onto: Ontologie, fiches: dict[int, dict]) -> list[str]:
    mots = [service.nom, *onto.service(service.id).synonymes]
    for fid in service.fiches:
        mots += [m for m in (fiches.get(fid, {}).get("mots_cles") or "").split(",") if m.strip()]
    vus = dict.fromkeys(normaliser(m) for m in mots)
    return [m for m in vus if m]


def services_afi(entree: ServicesAfiEntree, conn: Connection | None = None) -> SortieOutil[ServicesAfiDonnees]:
    onto = ontologie()
    with _connexion(conn) as c:
        services = services_par_code(c, onto)
        fiches = repo.connaissances(c, sorted({f for s in services.values() for f in s.fiches}))
        contact = _contact(c, onto)
    avert: list[Avertissement] = []
    candidats: list[ServiceCandidat] = []
    if entree.besoin:
        texte = normaliser(entree.besoin)
        for s in services.values():
            reconnus = [m for m in _mots_cles(s, onto, fiches) if _present(m, texte)]
            if reconnus:
                # Un mot-clé long ou composé (« leasing », « copie conforme ») pèse plus qu'un mot
                # générique (« lot ») : score = nombre total de caractères reconnus.
                candidats.append(ServiceCandidat(service=s, score=sum(len(m) for m in reconnus),
                                                 mots_cles_reconnus=reconnus))
        ordre = list(services)
        candidats.sort(key=lambda x: (-x.score, ordre.index(x.service.id)))
        if not candidats:
            avert.append(Avertissement(code=C.besoin_non_reconnu))
    choix = [x.service for x in candidats] or list(services.values())
    return SortieOutil[ServicesAfiDonnees](
        outil="services_afi",
        donnees=ServicesAfiDonnees(services=list(services.values()), candidats=candidats, contact_afi=contact),
        provenance=[Provenance(type="sql", table="assistant.services", ids=list(services))]
                   + _provenance_fiches(list(fiches) + [contact.fiche]),
        avertissements=avert,
        balises=[Balise(type="CHOIX", libelle=s.nom) for s in choix],
    )


# ---------- Construction des parcours publiés ----------

_LISTES = {"description": "description", "pour_qui": "pour_qui", "condition": "conditions", "etape": "etapes",
           "piece": "pieces", "frais": "frais", "lien": "liens", "remarque": "remarques"}


def _arbres(lignes: list[dict]) -> dict[int, list[ElementDemarche]]:
    """Racines par version, avec leurs sous-éléments, dans l'ordre du document."""
    noeuds: dict[int, ElementDemarche] = {}
    racines: dict[int, list[ElementDemarche]] = {}
    for l in lignes:
        e = ElementDemarche(
            id=l["id"], type=l["type"], groupe=l["groupe"], ordre=l["ordre"], texte=l["texte"], url=l["url"],
            montant_dt=float(l["montant_dt"]) if l["montant_dt"] is not None else None,
            unite_montant=l["unite_montant"], a_verifier=l["a_verifier"],
            note_verification=l["note_verification"], corrige=l["modifie_par_admin"])
        noeuds[l["id"]] = e
        if l["parent_id"] is None:
            racines.setdefault(l["version_id"], []).append(e)
        else:
            noeuds[l["parent_id"]].enfants.append(e)
    return racines


def _tous(elements: list[ElementDemarche]):
    for e in elements:
        yield e
        yield from _tous(e.enfants)


def _contient(texte: str, libelles: tuple[str, ...]) -> bool:
    t = normaliser(texte)
    return any(_present(l, t) for l in libelles)


def _lieu_depot(racines: list[ElementDemarche], onto: Ontologie) -> list[str]:
    """Phrases qui disent où déposer ; une ligne « à vérifier » n'est jamais donnée comme lieu."""
    return [e.texte for e in _tous([r for r in racines if r.type not in ("frais", "lien")])
            if not e.a_verifier and _contient(e.texte, onto.lieu_depot)]


def _chiffre(e: ElementDemarche) -> bool:
    return any(_MONTANT.search(x.texte) for x in _tous([e]))


def _frais_sans_montant(racines: list[ElementDemarche], onto: Ontologie) -> list[str]:
    return [e.texte for e in _tous([r for r in racines if r.type not in ("frais", "lien")])
            if _contient(e.texte, onto.frais) and not _chiffre(e)]


def _formulaires(lignes: list[dict]) -> dict[int, list[FormulaireService]]:
    par_parcours: dict[int, dict[str, FormulaireService]] = {}
    for l in lignes:
        f = par_parcours.setdefault(l["parcours_id"], {}).setdefault(l["code"], FormulaireService(
            code=l["code"], titre=l["titre"], valeurs_imposees=l["valeurs_imposees"] or {},
            a_verifier=l["a_verifier"], note_verification=l["note_verification"], variantes=[]))
        if l["langue"]:
            f.variantes.append(VarianteFormulaire(langue=l["langue"], titre_officiel=l["titre_officiel"],
                                                  url_page=l["url_page"], url_fichier=l["url_fichier"]))
    return {pid: list(fs.values()) for pid, fs in par_parcours.items()}


def _parcours(c: Connection, onto: Ontologie, service: str | None = None,
              parcours: str | None = None) -> tuple[list[ParcoursDemarche], list[dict]]:
    lignes = repo_assistant.parcours_publies(c, service, parcours)
    if not lignes:
        return [], []
    racines = _arbres(repo_assistant.elements(c, [l["version_id"] for l in lignes]))
    formulaires = _formulaires(repo_assistant.formulaires(c, [l["id"] for l in lignes]))
    resultat = []
    for l in lignes:
        r = racines.get(l["version_id"], [])
        listes = {nom: [e for e in r if e.type == t] for t, nom in _LISTES.items()}
        resultat.append(ParcoursDemarche(
            code=l["code"], titre=l["titre"], critere_choix=l["critere_choix"], version=l["numero"],
            publie_le=l["publie_le"], url_source=l["url_source"], date_collecte=l["date_collecte"],
            lieu_depot=_lieu_depot(r, onto), frais_sans_montant=_frais_sans_montant(r, onto),
            formulaires=formulaires.get(l["id"], []), **listes))
    return resultat, lignes


def _fiches_afi(c: Connection, ids: tuple[int, ...] | list[int]) -> list[FicheAfi]:
    fiches = repo.connaissances(c, list(ids)) if ids else {}
    return [FicheAfi(fiche=i, question=fiches[i]["question"].strip(), reponse=fiches[i]["reponse"])
            for i in ids if i in fiches and fiches[i]["actif"]]


def _a_verifier(p: ParcoursDemarche) -> bool:
    return any(e.a_verifier for e in _tous(sum((p.description, p.pour_qui, p.conditions, p.etapes, p.pieces,
                                                p.frais, p.liens, p.remarques), []))) \
        or any(f.a_verifier for f in p.formulaires)


def _balises_pdf(formulaires: list[FormulaireService]) -> list[Balise]:
    return [Balise(type="PDF", id=v.url_fichier, libelle=f"{v.titre_officiel} ({v.langue})")
            for f in formulaires for v in f.variantes if v.url_fichier]


def _provenance_parcours(lignes: list[dict]) -> list[Provenance]:
    prov = [Provenance(type="sql", table=TABLE_VERSIONS, ids=[str(l["version_id"]) for l in lignes])]
    urls = {(l["url_source"], l["date_collecte"]) for l in lignes if l["url_source"]}
    return prov + [Provenance(type="url", url=u, date_donnees=d) for u, d in sorted(urls, key=str)]


# ---------- demarche ----------

def demarche(entree: DemarcheEntree, conn: Connection | None = None) -> SortieOutil[DemarcheDonnees]:
    onto = ontologie()
    with _connexion(conn) as c:
        contact = _contact(c, onto)
        services = services_par_code(c, onto)
        service = services.get(entree.service)
        if service is None:
            return SortieOutil[DemarcheDonnees](
                outil="demarche",
                donnees=DemarcheDonnees(service=None, parcours=[], fiches_afi=[], contact_afi=contact),
                provenance=[Provenance(type="sql", table="assistant.services", ids=list(services))]
                           + _provenance_fiches([contact.fiche]),
                avertissements=[Avertissement(code=C.service_non_couvert, detail=entree.service)],
                balises=[Balise(type="CHOIX", libelle=s.nom) for s in services.values()])
        parcours, lignes = _parcours(c, onto, service.id, entree.parcours)
        fiches = _fiches_afi(c, service.fiches)

    avert: list[Avertissement] = []
    balises: list[Balise] = []
    if not parcours:
        avert.append(Avertissement(code=C.parcours_inconnu if entree.parcours else C.demarche_non_publiee,
                                   detail=entree.parcours or service.id))
    elif len(parcours) > 1:
        avert.append(Avertissement(code=C.parcours_a_choisir, detail=service.id))
        balises += [Balise(type="CHOIX", libelle=p.critere_choix or p.titre) for p in parcours]
    for p in parcours:
        if not p.lieu_depot:
            avert.append(Avertissement(code=C.lieu_depot_non_precise, detail=p.code))
        if p.frais_sans_montant:
            avert.append(Avertissement(code=C.frais_non_chiffres, detail=p.code))
        if _a_verifier(p):
            avert.append(Avertissement(code=C.point_a_verifier, detail=p.code))
    balises += _balises_pdf([f for p in parcours for f in p.formulaires])
    return SortieOutil[DemarcheDonnees](
        outil="demarche",
        donnees=DemarcheDonnees(service=service, parcours=parcours, fiches_afi=fiches, contact_afi=contact),
        provenance=_provenance_parcours(lignes) + _provenance_fiches([f.fiche for f in fiches] + [contact.fiche]),
        avertissements=avert, balises=list({b.texte: b for b in balises}.values()))


# ---------- guider_service ----------

def _points(p: ParcoursDemarche, presentation: list[FicheAfi], contact: ContactAfi) -> list[PointGuide]:
    """Ordre du guidage : présentation, conditions, pièces, formulaire, étapes, frais, lieu de dépôt."""
    pts = [PointGuide(rubrique="presentation", fiches_afi=presentation)] if presentation else []
    for rubrique, liste in (("description", p.description), ("pour_qui", p.pour_qui),
                            ("condition", p.conditions), ("piece", p.pieces)):
        pts += [PointGuide(rubrique=rubrique, groupe=e.groupe, element=e) for e in liste]
    pts += [PointGuide(rubrique="formulaire", formulaire=f) for f in p.formulaires]
    for rubrique, liste in (("etape", p.etapes), ("frais", p.frais), ("remarque", p.remarques)):
        pts += [PointGuide(rubrique=rubrique, groupe=e.groupe, element=e) for e in liste]
    pts.append(PointGuide(rubrique="lieu_depot", lieu_depot=p.lieu_depot,
                          contact_afi=None if p.lieu_depot else contact))
    return pts


def _plan(points: list[PointGuide]) -> list[EtapePlan]:
    plan: list[EtapePlan] = []
    for i, pt in enumerate(points):
        if plan and plan[-1].rubrique == pt.rubrique:
            plan[-1].nombre += 1
        else:
            plan.append(EtapePlan(rubrique=pt.rubrique, debut=i, nombre=1))
    return plan


def guider_service(entree: GuiderServiceEntree, conn: Connection | None = None) -> SortieOutil[GuiderServiceDonnees]:
    onto = ontologie()
    with _connexion(conn) as c:
        contact = _contact(c, onto)
        parcours, lignes = _parcours(c, onto, parcours=entree.parcours)
        service = services_par_code(c, onto).get(lignes[0]["service"]) if lignes else None
        presentation = _fiches_afi(c, onto.service(service.id).fiches_presentation) if service else []

    if not parcours:
        return SortieOutil[GuiderServiceDonnees](
            outil="guider_service",
            donnees=GuiderServiceDonnees(service=None, parcours=entree.parcours, titre=None, url_source=None,
                                         position=entree.position, total=0, point=None, precedent=None,
                                         suivant=None, plan=[]),
            provenance=_provenance_fiches([contact.fiche]),
            avertissements=[Avertissement(code=C.parcours_inconnu, detail=entree.parcours)])

    p = parcours[0]
    points = _points(p, presentation, contact)
    total, pos = len(points), entree.position
    point = points[pos] if pos < total else None
    avert: list[Avertissement] = []
    balises: list[Balise] = []
    if point is None:
        avert.append(Avertissement(code=C.position_hors_parcours, detail=str(pos)))
    else:
        if point.element is not None:
            if any(e.a_verifier for e in _tous([point.element])):
                avert.append(Avertissement(code=C.point_a_verifier, detail=p.code))
            if any(e.texte in p.frais_sans_montant for e in _tous([point.element])):
                avert.append(Avertissement(code=C.frais_non_chiffres, detail=p.code))
        if point.formulaire is not None:
            if point.formulaire.a_verifier:
                avert.append(Avertissement(code=C.point_a_verifier, detail=p.code))
            balises = _balises_pdf([point.formulaire])
        if point.rubrique == "lieu_depot" and not point.lieu_depot:
            avert.append(Avertissement(code=C.lieu_depot_non_precise, detail=p.code))
    return SortieOutil[GuiderServiceDonnees](
        outil="guider_service",
        donnees=GuiderServiceDonnees(
            service=service, parcours=p.code, titre=p.titre, url_source=p.url_source, position=pos, total=total,
            point=point, precedent=min(pos, total) - 1 if pos > 0 else None,
            suivant=pos + 1 if pos + 1 < total else None, plan=_plan(points)),
        provenance=_provenance_parcours(lignes)
                   + _provenance_fiches([f.fiche for f in presentation] + [contact.fiche]),
        avertissements=avert, balises=balises)
