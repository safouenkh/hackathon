"""Outils services AFI : services_afi (orientation, BF22) et demarche (fiche de service, BF23/BF24).

Le contenu vient uniquement de `afi.chatbot_connaissances` (réponses validées par l'AFI) :
les sections (conditions, étapes, pièces, frais) sont extraites du texte des fiches, sans réécriture.
Un service hors liste renvoie au contact AFI (fiche 26), jamais à une démarche inventée.
"""
from __future__ import annotations

import re

from sqlalchemy import Connection

from app.processing.lots import _connexion
from app.processing.reference import URL_SERVICES_AFI, normaliser
from app.processing.schemas import (
    Avertissement, Balise, CodeAvertissement as C, ContactAfi, DemarcheDonnees, DemarcheEntree,
    FicheDemarche, Frais, GroupePieces, Provenance, ServiceAfi, ServiceAfiId, ServiceCandidat,
    ServicesAfiDonnees, ServicesAfiEntree, SortieOutil, VarianteAcquisition,
)
from app.repositories import afi as repo

FICHE_CONTACT = 26

# Les 8 services du cahier des charges §IV.6 (nom, besoin, fiches existantes).
# Fiche 12 écartée : ancienne version du contenu repris par les fiches 13 et 14.
SERVICES: dict[ServiceAfiId, ServiceAfi] = {s.id: s for s in [
    ServiceAfi(id=ServiceAfiId.acquisition, nom="Acquisition d'un lot", besoin="Acheter un lot industriel",
               fiches=[13, 14, 15, 16, 17]),
    ServiceAfi(id=ServiceAfiId.encheres, nom="Vente aux enchères", besoin="Participer à une vente publique",
               fiches=[24, 25]),
    ServiceAfi(id=ServiceAfiId.situation_fonciere, nom="Attestation de situation foncière",
               besoin="Connaître la situation d'un lot", fiches=[18]),
    ServiceAfi(id=ServiceAfiId.insertion_hypotheque, nom="Attestation d'insertion d'hypothèque",
               besoin="Obtenir un prêt bancaire", fiches=[19]),
    ServiceAfi(id=ServiceAfiId.mainlevee, nom="Attestation de mainlevée",
               besoin="Obtenir la mainlevée sur son terrain", fiches=[23]),
    ServiceAfi(id=ServiceAfiId.acte_precision, nom="Acte de précision ou contrat final",
               besoin="Isoler le lot comme propriété distincte", fiches=[20]),
    ServiceAfi(id=ServiceAfiId.autorisation_vente_leasing, nom="Autorisation de vente",
               besoin="Vente d'un lot par une société de leasing", fiches=[21]),
    ServiceAfi(id=ServiceAfiId.copie_conforme, nom="Copie conforme",
               besoin="Obtenir une copie du contrat ou de l'acte", fiches=[22]),
]}

VARIANTES_ACQUISITION: dict[VarianteAcquisition, list[int]] = {
    VarianteAcquisition.developpement_regional: [13, 14],
    VarianteAcquisition.littoral_grand_tunis: [15, 16, 17],
}

# Mots-clés d'orientation (complètent `mots_cles` des fiches). Filet de sécurité multilingue :
# la compréhension fine (dialectes, arabizi) relève des rôles 2 et 4.
MOTS_CLES_SUPPLEMENTAIRES: dict[ServiceAfiId, list[str]] = {
    ServiceAfiId.acquisition: ["acheter", "achat", "acquerir", "acquisition", "terrain", "lot", "reserver",
                               "buy", "plot", "land", "kaufen", "grundstuck", "arsa", "satin al",
                               "شراء", "ارض", "أرض", "قطعة", "n7eb terrain", "nechri", "9at3a"],
    ServiceAfiId.encheres: ["enchere", "encheres", "adjudication", "vente publique", "auction",
                            "versteigerung", "ihale", "مزاد", "بتة", "betta"],
    ServiceAfiId.situation_fonciere: ["situation fonciere", "situation du lot", "situation juridique",
                                      "land status", "وضعية عقارية", "شهادة في الوضعية"],
    ServiceAfiId.insertion_hypotheque: ["hypotheque", "pret", "banque", "credit", "bank", "loan", "mortgage",
                                        "kredi", "ipotek", "hypothek", "رهن", "قرض", "بنك", "karedi", "credi"],
    ServiceAfiId.mainlevee: ["mainlevee", "main levee", "lever l hypotheque", "radiation", "release",
                             "رفع الرهن", "رفع اليد"],
    ServiceAfiId.acte_precision: ["acte de precision", "contrat final", "acte definitif", "titre foncier",
                                  "propriete distincte", "final contract", "title deed", "عقد نهائي",
                                  "رسم عقاري"],
    ServiceAfiId.autorisation_vente_leasing: ["leasing", "credit bail", "autorisation de vente", "revendre",
                                              "ليزينغ", "إيجار مالي", "ترخيص في البيع"],
    ServiceAfiId.copie_conforme: ["copie conforme", "copie", "duplicata", "copy", "kopie", "kopya",
                                  "نسخة مطابقة", "نسخة"],
}

# ---------- Extraction des sections d'une fiche ----------

_LABEL_RE = re.compile(
    r"(?im)^(?:[^\n:]*?—\s*)?(conditions|étapes|déroulement|documents requis)\b[^:\n]*:[ \t]*")
_PHASE_RE = re.compile(r"(?m)^\s*(I{1,3}|IV)\.\s*([^:\n]+?)\s*:\s*(.*)$")
_NUM_RE = re.compile(r"(?:^|\s)(\d{1,2})\)\s*")
_SOURCE_RE = re.compile(r"\(Source[^)]*?(www\.[^\s)]+)[^)]*\)", re.I)
_FRAIS_RE = re.compile(r"frais\s*:\s*(\d+)\s*DT([^.\n]*)", re.I)


def _items(texte: str) -> list[str]:
    """Découpe une section en éléments : listes numérotées « 1) », sinon séparateur « ; »."""
    texte = texte.strip()
    if _NUM_RE.search(texte):
        morceaux = _NUM_RE.split(texte)
        items = [morceaux[i + 1] for i in range(1, len(morceaux) - 1, 2)]
    else:
        items = texte.split(";")
    return [i.strip().rstrip(";").rstrip(".").strip() for i in items if i.strip().rstrip(".;").strip()]


def analyser_fiche(fiche_id: int, question: str, reponse: str,
                   variante: VarianteAcquisition | None) -> tuple[FicheDemarche, list[C]]:
    codes: list[C] = []
    m_src = _SOURCE_RE.search(reponse)
    url = None
    if m_src:
        url = URL_SERVICES_AFI if "nos-services" in m_src.group(1) else "https://" + m_src.group(1).rstrip("/.")
    corps = _SOURCE_RE.sub("", reponse).strip()

    labels = list(_LABEL_RE.finditer(corps))
    entete = corps[: labels[0].start()] if labels else corps
    lignes_entete = [l.strip() for l in entete.splitlines() if l.strip()]
    description = list(lignes_entete)

    conditions, etapes, pieces = [], [], []
    for i, m in enumerate(labels):
        fin = labels[i + 1].start() if i + 1 < len(labels) else len(corps)
        bloc = corps[m.end():fin].strip()
        label = m.group(1).lower()
        if label == "documents requis":
            phases = list(_PHASE_RE.finditer(bloc))
            if phases:
                pieces += [GroupePieces(phase=p.group(2).strip(), pieces=_items(p.group(3))) for p in phases]
            else:
                pieces.append(GroupePieces(phase=None, pieces=_items(bloc)))
        elif label == "conditions":
            lignes = bloc.splitlines()
            conditions += _items(" ".join(lignes) if not _NUM_RE.search(bloc) else bloc.replace("\n", " "))
        else:  # étapes, déroulement
            # Une phrase après la dernière étape (ex. délai de 3 ans) est gardée en description.
            if _NUM_RE.search(bloc) and "\n" in bloc:
                lignes = [l.strip() for l in bloc.splitlines() if l.strip()]
                num = [l for l in lignes if re.match(r"\d{1,2}\)", l)]
                description += [l for l in lignes if not re.match(r"\d{1,2}\)", l)]
                etapes += _items(" ".join(num))
            else:
                etapes += _items(bloc)

    frais: list[Frais] = []
    m_frais = _FRAIS_RE.search(lignes_entete[0] if lignes_entete else "")
    if m_frais:
        complement = m_frais.group(2).strip()
        frais.append(Frais(libelle="frais du service" + (f" ({complement})" if complement else ""),
                           montant_dt=int(m_frais.group(1)), texte_source=m_frais.group(0).strip()))
    for groupe in pieces:
        for p in groupe.pieces:
            if re.match(r"(?i)(frais|prix du lot|paiement des frais)", p):
                frais.append(Frais(libelle=p, montant_dt=None, texte_source=p))
    if any(f.montant_dt is None for f in frais):
        codes.append(C.frais_non_chiffres)

    # « Dépôt », « dépose », « déposé » : phrases de la source qui disent où déposer.
    lieu = [x for x in conditions + etapes if re.search(r"(?i)\bd[ée]p[oô][st]", x)]
    if not (conditions or etapes or pieces):
        codes.append(C.extraction_partielle)
    return FicheDemarche(
        fiche=fiche_id, titre=question.strip(), variante=variante, description=description,
        conditions=conditions, etapes=etapes, pieces=pieces, frais=frais, lieu_depot=lieu,
        texte_source=reponse, url_source=url,
    ), codes


def _contact(c: Connection) -> ContactAfi:
    fiche = repo.connaissances(c, [FICHE_CONTACT]).get(FICHE_CONTACT)
    texte = fiche["reponse"] if fiche else ""
    adresse = re.search(r"Siège de l'Agence Foncière Industrielle\s*:\s*([^.]+)\.", texte)
    tel = re.search(r"téléphone\s*(\+?[\d ]{8,})", texte)
    site = re.search(r"\b(www\.[a-z0-9.-]+\.[a-z]{2,})\b", texte)
    return ContactAfi(adresse=adresse.group(1).strip() if adresse else None,
                      telephone=tel.group(1).strip() if tel else None,
                      site=site.group(1) if site else None, fiche=FICHE_CONTACT)


# ---------- services_afi ----------

def _mots_cles(service: ServiceAfi, fiches: dict[int, dict]) -> list[str]:
    mots = list(MOTS_CLES_SUPPLEMENTAIRES[service.id])
    for fid in service.fiches:
        mots += [m for m in (fiches.get(fid, {}).get("mots_cles") or "").split(",") if m.strip()]
    vus = dict.fromkeys(normaliser(m) for m in mots)
    return [m for m in vus if m]


_ARABE = re.compile(r"[؀-ۿ]")
# Proclitiques arabes collés au mot (و ف ب ل ك + article ال / لل) : « البنك », « للقرض ».
_PREFIXES_AR = r"(?:[وفبلك])?(?:ال|لل)?"


def _present(mot: str, texte: str) -> bool:
    prefixe = _PREFIXES_AR if _ARABE.search(mot) else ""
    return re.search(rf"(?<!\w){prefixe}{re.escape(mot)}(?!\w)", texte) is not None


def services_afi(entree: ServicesAfiEntree, conn: Connection | None = None) -> SortieOutil[ServicesAfiDonnees]:
    tous = [fid for s in SERVICES.values() for fid in s.fiches]
    with _connexion(conn) as c:
        fiches = repo.connaissances(c, tous)
        contact = _contact(c)
    avert: list[Avertissement] = []
    candidats: list[ServiceCandidat] = []
    if entree.besoin:
        texte = normaliser(entree.besoin)
        for s in SERVICES.values():
            reconnus = [m for m in _mots_cles(s, fiches) if _present(m, texte)]
            if reconnus:
                # Un mot-clé long ou composé (« leasing », « copie conforme ») pèse plus qu'un mot
                # générique (« lot ») : score = nombre total de caractères reconnus.
                score = sum(len(m) for m in reconnus)
                candidats.append(ServiceCandidat(service=s, score=score, mots_cles_reconnus=reconnus))
        candidats.sort(key=lambda x: (-x.score, list(SERVICES).index(x.service.id)))
        if not candidats:
            avert.append(Avertissement(code=C.besoin_non_reconnu))
    choix = [x.service for x in candidats] or list(SERVICES.values())
    return SortieOutil[ServicesAfiDonnees](
        outil="services_afi",
        donnees=ServicesAfiDonnees(services=list(SERVICES.values()), candidats=candidats, contact_afi=contact),
        provenance=[Provenance(type="sql", table="afi.chatbot_connaissances",
                               ids=[str(i) for i in sorted(set(tous) | {FICHE_CONTACT})]),
                    Provenance(type="document", url=None, table=None,
                               ids=["cahier des charges §IV.6"])],
        avertissements=avert,
        balises=[Balise(type="CHOIX", libelle=s.nom) for s in choix],
    )


# ---------- demarche ----------

def demarche(entree: DemarcheEntree, conn: Connection | None = None) -> SortieOutil[DemarcheDonnees]:
    try:
        sid = ServiceAfiId(entree.service)
    except ValueError:
        sid = None
    with _connexion(conn) as c:
        contact = _contact(c)
        if sid is None:
            return SortieOutil[DemarcheDonnees](
                outil="demarche", donnees=DemarcheDonnees(service=None, fiches=[], contact_afi=contact),
                provenance=[Provenance(type="sql", table="afi.chatbot_connaissances", ids=[str(FICHE_CONTACT)])],
                avertissements=[Avertissement(code=C.service_non_couvert, detail=entree.service)],
                balises=[Balise(type="CHOIX", libelle=s.nom) for s in SERVICES.values()])
        service = SERVICES[sid]
        if sid is ServiceAfiId.acquisition:
            variantes = [entree.variante] if entree.variante else list(VARIANTES_ACQUISITION)
            plan = [(fid, v) for v in variantes for fid in VARIANTES_ACQUISITION[v]]
        else:
            plan = [(fid, None) for fid in service.fiches]
        fiches_brutes = repo.connaissances(c, [fid for fid, _ in plan])

    fiches, codes = [], []
    for fid, var in plan:
        f = fiches_brutes.get(fid)
        if f is None or not f["actif"]:
            codes.append(C.extraction_partielle)
            continue
        fiche, cs = analyser_fiche(fid, f["question"], f["reponse"], var)
        fiches.append(fiche)
        codes += cs
    if not any(f.lieu_depot for f in fiches):
        codes.append(C.lieu_depot_non_precise)
    avert = [Avertissement(code=x) for x in dict.fromkeys(codes)]
    balises = []
    if sid is ServiceAfiId.acquisition and entree.variante is None:
        balises = [Balise(type="CHOIX", libelle="Zone de développement régional"),
                   Balise(type="CHOIX", libelle="Zone littorale ou Grand Tunis")]
    urls = sorted({f.url_source for f in fiches if f.url_source})
    return SortieOutil[DemarcheDonnees](
        outil="demarche", donnees=DemarcheDonnees(service=service, fiches=fiches, contact_afi=contact),
        provenance=[Provenance(type="sql", table="afi.chatbot_connaissances",
                               ids=[str(f.fiche) for f in fiches] + [str(FICHE_CONTACT)])]
                   + [Provenance(type="url", url=u) for u in urls],
        avertissements=avert, balises=balises)
