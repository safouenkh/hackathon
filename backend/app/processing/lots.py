"""Outils lots : chercher_lots, details_lot, comparer_lots, lots_proches.

Tous les chiffres (filtres, totaux, tris, distances) sont calculés ici, jamais par le LLM.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict

from sqlalchemy import Connection

from app.config import get_settings
from app.db import get_engine
from app.processing.reference import (
    COM_ID_PAR_TYPE, COMMODITES, GOUVERNORATS, GOUVERNORATS_DEDUITS, PRIX_ABERRANTS,
    PRIX_ECART_SITE_PUBLIC, TYPES_DISTANCE, TypeCommodite, TypeServiceProximite,
    coordonnees_valides, gouv_id_depuis_nom, normaliser,
)
from app.processing.schemas import (
    DATE_INSTANTANE_AFI, Avertissement, Balise, ChercherLotsDonnees, ChercherLotsEntree,
    CodeAvertissement as C, Commodite, ComparerLotsDonnees, ComparerLotsEntree, Coordonnees,
    DetailsLotDonnees, DetailsLotEntree, DocumentZone, LigneComparaison, Lot, LotsProchesDonnees,
    LotsProchesEntree, Provenance, ServiceProximite, SortieOutil, StatutLot, TriLots, ZoneProche, ZoneResume,
)
from app.processing.statuts import ETAPES_CONNUES, etapes_pour, statut_depuis_etape
from app.repositories import afi as repo

_PRIX_EXCLUS = sorted(PRIX_ABERRANTS)
_DISTANCE_RE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*km\s*$", re.I)
_RAYON_TERRE_KM = 6371.0088


# =====================================================================
# Briques communes
# =====================================================================

def _zones_par_code() -> dict[int, dict]:
    return {z["code_zone"]: z for z in repo.zones()}


def prix_zone(code_zone: int | None) -> tuple[int | None, list[C]]:
    """Prix indicatif Dt/m² d'une zone et ses avertissements."""
    if code_zone is None:
        return None, [C.prix_inconnu]
    if code_zone in PRIX_ABERRANTS:
        return None, [C.prix_suspect]
    p = _zones_par_code().get(code_zone, {}).get("prixunitaire")
    if not p or p <= 0:
        # Prix AFI vide : complément sourcé (assistant.zone_complements), entier comme en SQL
        comp = repo.complements_par_zone().get(code_zone, {}).get("prixunitaire")
        if comp and comp["valeur"] == int(comp["valeur"]):
            return int(comp["valeur"]), [C.prix_indicatif, C.valeur_complementaire]
        return None, [C.prix_inconnu]
    codes = [C.prix_indicatif]
    if code_zone in PRIX_ECART_SITE_PUBLIC:
        codes.append(C.prix_ecart_site_public)
    return int(p), codes


def gouvernorat(gouv_id: int | None) -> tuple[str | None, list[C]]:
    nom = GOUVERNORATS.get(gouv_id) if gouv_id is not None else None
    if nom is None:
        return None, [C.gouvernorat_non_reconnu]
    return nom, [C.gouvernorat_deduit] if gouv_id in GOUVERNORATS_DEDUITS else []


def zone_resume(z: dict) -> ZoneResume:
    prix, _ = prix_zone(z["code_zone"])
    coords = coordonnees_valides(z["zone_lat"], z["zone_long"])
    gouv, _ = gouvernorat(z["gouv_id"])
    return ZoneResume(
        zone_id=z["code_zone"],
        nom=(z["zone_libelle_francais"] or "").strip() or None,
        nom_ar=(z["zone_libelle_arabe"] or "").strip() or None,
        gouvernorat=gouv,
        prix_indicatif_dt_m2=prix,
        coordonnees=Coordonnees(lat=coords[0], lon=coords[1]) if coords else None,
        visible_carte_publique=bool(z["zone_show"]),
    )


def construire_lot(ligne: repo.LigneLot) -> Lot:
    codes: list[C] = []
    zone = _zones_par_code().get(ligne.code_zone) if ligne.code_zone is not None else None
    if zone is None:
        codes.append(C.lot_orphelin)
    surface = ligne.surface if ligne.surface is not None and ligne.surface > 0 else None
    if surface is None:
        codes.append(C.surface_invalide)
    prix, codes_prix = prix_zone(ligne.code_zone if zone else None)
    codes += codes_prix
    gouv, codes_gouv = gouvernorat(zone["gouv_id"]) if zone else (None, [])
    codes += codes_gouv
    st = statut_depuis_etape(ligne.etape)
    codes += list(st.avertissements)
    return Lot(
        lot_id=ligne.lot_id,
        numero=(ligne.numero or "").strip() or None,
        zone_id=zone["code_zone"] if zone else None,
        zone_nom=((zone["zone_libelle_francais"] or "").strip() or None) if zone else None,
        gouvernorat=gouv,
        surface_m2=surface,
        prix_indicatif_dt_m2=prix,
        prix_total_indicatif_dt=ligne.prix_total,
        statut=st.statut,
        code_etape=ligne.etape,
        avertissements=list(dict.fromkeys(codes)),
    )


def balise_lot(lot: Lot) -> Balise:
    nom = f"Lot {lot.numero or lot.lot_id}" + (f" - {lot.zone_nom}" if lot.zone_nom else "")
    return Balise(type="LOT", id=str(lot.lot_id), libelle=nom)


def balise_zone(zone_id: int, nom: str | None) -> Balise:
    return Balise(type="ZONE", id=str(zone_id), libelle=nom or str(zone_id))


def _avertissements_globaux(lots: list[Lot]) -> list[Avertissement]:
    """Codes présents dans au moins un lot, remontés une fois au niveau de la réponse."""
    vus = dict.fromkeys(c for lot in lots for c in lot.avertissements)
    return [Avertissement(code=c) for c in vus]


def _prov_lots(lots: list[Lot]) -> list[Provenance]:
    zones = sorted({str(l.zone_id) for l in lots if l.zone_id is not None})
    prov = [
        Provenance(type="sql", table="afi.lots", ids=[str(l.lot_id) for l in lots], date_donnees=DATE_INSTANTANE_AFI),
        Provenance(type="sql", table="afi.zones", ids=zones, date_donnees=DATE_INSTANTANE_AFI),
    ]
    completes = sorted({str(l.zone_id) for l in lots if C.valeur_complementaire in l.avertissements})
    if completes:
        prov.append(Provenance(type="sql", table="assistant.zone_complements", ids=completes))
    return prov


def _detail_complement(champ: str, comp: dict) -> str:
    return f"{champ} ({comp['cle_source']}) : {comp['source']}"


def lignes_commodites(code_zone: int) -> tuple[dict, ...]:
    """Lignes AFI de la zone, plus un complément sourcé pour chaque commodité absente de la base AFI.
    Un complément porte la clé « complement » ; sa valeur est écrite dans l'unité de la colonne AFI."""
    afi = repo.commodites_par_zone().get(code_zone, ())
    presentes = {r["com_id"] for r in afi}
    ajouts = []
    for champ, comp in sorted(repo.complements_par_zone().get(code_zone, {}).items()):
        if not champ.startswith("com_"):
            continue
        com_id = int(champ[4:])
        ref = COMMODITES.get(com_id)
        if ref is None or com_id in presentes or len(ref[2]) != 1:
            continue
        unite = next(iter(ref[2]))
        ajouts.append({"id": f"complement:{champ}", "code_zone": code_zone, "com_id": com_id,
                       "zc_libelle_francais": None, "zc_unite": unite,
                       "value": f"{float(comp['valeur']):g} {unite}",
                       "complement": _detail_complement(champ, comp)})
    return tuple(afi) + tuple(ajouts)


def distance_depuis_texte(valeur: str | None) -> float | None:
    m = _DISTANCE_RE.match(valeur or "")
    return float(m.group(1).replace(",", ".")) if m else None


def commodites_de_zone(code_zone: int) -> tuple[list[Commodite], list[Avertissement]]:
    res: list[Commodite] = []
    avert: list[Avertissement] = []
    for r in lignes_commodites(code_zone):
        ref = COMMODITES.get(r["com_id"])
        unite = (r["zc_unite"] or "").strip()
        if ref is None or unite not in ref[2]:
            avert.append(Avertissement(code=C.donnee_incoherente, zone_id=code_zone,
                                       detail=f"zone_commodites.id={r['id']}"))
            continue
        if r.get("complement"):
            avert.append(Avertissement(code=C.valeur_complementaire, zone_id=code_zone, detail=r["complement"]))
        type_, libelle, _ = ref
        valeur = (r["value"] or "").strip() or None
        distance = None
        if type_ in TYPES_DISTANCE:
            distance = distance_depuis_texte(valeur)
            if distance is None:
                avert.append(Avertissement(code=C.distance_ambigue, zone_id=code_zone,
                                           detail=f"zone_commodites.id={r['id']}"))
        elif type_ in (TypeCommodite.electricite, TypeCommodite.eau_potable,
                       TypeCommodite.gaz_naturel, TypeCommodite.telephone) and not re.search(r"\d", valeur or ""):
            valeur = None                     # unité seule, sans valeur
        res.append(Commodite(type=type_, libelle_type=libelle,
                             nom=(r["zc_libelle_francais"] or "").strip() or None,
                             valeur_texte=valeur, distance_km=distance))
    return res, avert


def services_de_zone(code_zone: int) -> list[ServiceProximite]:
    res = []
    for r in repo.services_par_zone().get(code_zone, ()):
        try:
            cat = TypeServiceProximite(r["categorie"])
        except ValueError:
            continue
        res.append(ServiceProximite(
            categorie=cat, nom=(r["nom"] or "").strip() or None,
            distance_km=float(r["distance_km"]) if r["distance_km"] is not None else None,
            source=r["source"]))
    return res


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * _RAYON_TERRE_KM * math.asin(math.sqrt(h))


def _connexion(conn: Connection | None):
    return _Noop(conn) if conn is not None else get_engine().connect()


class _Noop:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


# =====================================================================
# chercher_lots
# =====================================================================

def resoudre_zones_par_nom(nom: str) -> list[int]:
    cible = normaliser(nom)
    if not cible:
        return []
    return [z["code_zone"] for z in repo.zones()
            if cible in normaliser(z["zone_libelle_francais"]) or cible in normaliser(z["zone_libelle_arabe"])]


def chercher_lots(entree: ChercherLotsEntree, conn: Connection | None = None) -> SortieOutil[ChercherLotsDonnees]:
    avert: list[Avertissement] = []

    def vide(code: C, detail: str | None = None) -> SortieOutil[ChercherLotsDonnees]:
        return SortieOutil[ChercherLotsDonnees](
            outil="chercher_lots",
            donnees=ChercherLotsDonnees(lots=[], total_correspondants=0, criteres_appliques=entree,
                                        tri=entree.tri),
            provenance=[Provenance(type="sql", table="afi.lots", date_donnees=DATE_INSTANTANE_AFI)],
            avertissements=avert + [Avertissement(code=code, detail=detail), Avertissement(code=C.aucun_resultat)],
        )

    gouv_id = None
    if entree.gouvernorat:
        gouv_id = gouv_id_depuis_nom(entree.gouvernorat)
        if gouv_id is None:
            return vide(C.gouvernorat_non_reconnu, entree.gouvernorat)

    zone_ids = list(entree.zone_ids) if entree.zone_ids else None
    if entree.zone_nom:
        par_nom = resoudre_zones_par_nom(entree.zone_nom)
        if not par_nom:
            return vide(C.zone_introuvable, entree.zone_nom)
        zone_ids = [z for z in par_nom if zone_ids is None or z in zone_ids]
        if not zone_ids:
            return vide(C.zone_introuvable, entree.zone_nom)

    if entree.activite:
        avert.append(Avertissement(code=C.activite_non_filtree, detail=entree.activite))

    # Proximité d'un équipement : distance par zone (données AFI pour port/gare/…, OSM pour les services)
    distances: dict[int, float] | None = None
    noms_equipement: dict[int, str | None] = {}
    distances_completees: dict[int, str] = {}
    if entree.pres_de is not None:
        distances, ambigues = {}, 0
        for code in (zone_ids if zone_ids is not None else _zones_par_code()):
            nom, km, ambigu, complement = _equipement(code, entree.pres_de)
            ambigues += ambigu and km is None
            if km is not None and (entree.distance_max_km is None or km <= entree.distance_max_km):
                distances[code], noms_equipement[code] = km, nom
                if complement:
                    distances_completees[code] = complement
        if ambigues:
            avert.append(Avertissement(code=C.distance_ambigue, detail=f"{ambigues} zones écartées"))
        if not distances:
            return vide(C.aucun_resultat, f"aucune zone avec {entree.pres_de.value} dans le rayon demandé")
        zone_ids = sorted(distances)

    etapes, inclure_inconnues = etapes_pour(entree.statuts)
    with _connexion(conn) as c:
        lignes, total, sans_prix = repo.chercher_lots(
            c, etapes=etapes, inclure_etapes_inconnues=inclure_inconnues,
            etapes_connues=list(ETAPES_CONNUES), gouv_id=gouv_id, zone_ids=zone_ids,
            surface_min=entree.surface_min_m2, surface_max=entree.surface_max_m2,
            budget_max=entree.budget_max_dt, prix_exclus=_PRIX_EXCLUS, limite=entree.limite,
            distances_zones=distances, tri_par_distance=entree.tri is TriLots.distance_equipement)

    lots = [construire_lot(l) for l in lignes]
    if distances is not None:
        lots = [l.model_copy(update={"distance_equipement_km": distances.get(l.zone_id),
                                     "equipement_nom": noms_equipement.get(l.zone_id)}) for l in lots]
    if entree.budget_max_dt is not None and sans_prix:
        avert.append(Avertissement(code=C.budget_non_verifiable, detail=f"{sans_prix} lots sans prix exclus"))
    if total > len(lots):
        avert.append(Avertissement(code=C.resultats_tronques, detail=f"{len(lots)}/{total}"))
    if not lots:
        avert.append(Avertissement(code=C.aucun_resultat))
    avert += _avertissements_globaux(lots)
    avert += [Avertissement(code=C.valeur_complementaire, zone_id=z, detail=distances_completees[z])
              for z in sorted({l.zone_id for l in lots if l.zone_id in distances_completees})]

    zones_vues = {}
    for l in lots:
        if l.zone_id is not None:
            zones_vues.setdefault(l.zone_id, l.zone_nom)
    return SortieOutil[ChercherLotsDonnees](
        outil="chercher_lots",
        donnees=ChercherLotsDonnees(lots=lots, total_correspondants=total, criteres_appliques=entree,
                                    tri=entree.tri),
        provenance=_prov_lots(lots) + ([Provenance(
            type="sql", table="afi.zone_commodites" if isinstance(entree.pres_de, TypeCommodite) else "afi.zone_services",
            ids=sorted({str(l.zone_id) for l in lots if l.zone_id is not None}), date_donnees=DATE_INSTANTANE_AFI)]
            if entree.pres_de is not None else []),
        avertissements=avert,
        balises=[balise_lot(l) for l in lots] + [balise_zone(z, n) for z, n in zones_vues.items()],
    )


# =====================================================================
# details_lot
# =====================================================================

def details_lot(entree: DetailsLotEntree, conn: Connection | None = None) -> SortieOutil[DetailsLotDonnees]:
    with _connexion(conn) as c:
        lignes = repo.lots_par_ids(c, [entree.lot_id], _PRIX_EXCLUS)
        if not lignes:
            return SortieOutil[DetailsLotDonnees](
                outil="details_lot", donnees=DetailsLotDonnees(lot=None, zone=None),
                provenance=[Provenance(type="sql", table="afi.lots", ids=[str(entree.lot_id)],
                                       date_donnees=DATE_INSTANTANE_AFI)],
                avertissements=[Avertissement(code=C.lot_introuvable, lot_id=entree.lot_id)])
        ligne = lignes[0]
        lot = construire_lot(ligne)
        polygone = repo.lot_a_un_polygone(c, ligne.zone_id_brut, ligne.numero)
        docs_bruts = repo.documents_zone(c, lot.zone_id) if lot.zone_id is not None else []

    avert = _avertissements_globaux([lot])
    zone = commodites = services = None
    documents: list[DocumentZone] = []
    balises = [balise_lot(lot)]
    provenance = _prov_lots([lot])
    if lot.zone_id is not None:
        z = _zones_par_code()[lot.zone_id]
        zone = zone_resume(z)
        if zone.coordonnees is None:
            avert.append(Avertissement(code=C.coordonnees_manquantes, zone_id=lot.zone_id))
        commodites, avert_com = commodites_de_zone(lot.zone_id)
        avert += avert_com
        services = services_de_zone(lot.zone_id)
        base = get_settings().afi_documents_base_url.rstrip("/")
        for d in docs_bruts:
            url = f"{base}/{d['fichier']}" if base and d["fichier"] else None
            documents.append(DocumentZone(document_id=d["id"], type=d["type"],
                                          nom=(d["nom_original"] or "").strip() or None, url=url))
            if url:
                balises.append(Balise(type="PDF", id=url, libelle=d["nom_original"] or d["type"]))
        if documents and not base:
            avert.append(Avertissement(code=C.document_sans_lien, zone_id=lot.zone_id))
        balises.append(balise_zone(lot.zone_id, zone.nom))
        provenance += [
            Provenance(type="sql", table="afi.zone_commodites", ids=[str(lot.zone_id)], date_donnees=DATE_INSTANTANE_AFI),
            Provenance(type="sql", table="afi.zone_services", ids=[str(lot.zone_id)], date_donnees=DATE_INSTANTANE_AFI),
            Provenance(type="sql", table="afi.zone_documents", ids=[str(d.document_id) for d in documents],
                       date_donnees=DATE_INSTANTANE_AFI),
        ]
        if any(a.code is C.valeur_complementaire for a in avert_com) and not any(
                p.table == "assistant.zone_complements" for p in provenance):
            provenance.append(Provenance(type="sql", table="assistant.zone_complements", ids=[str(lot.zone_id)]))
    return SortieOutil[DetailsLotDonnees](
        outil="details_lot",
        donnees=DetailsLotDonnees(lot=lot, zone=zone, commodites_zone=commodites or [],
                                  services_proximite=services or [], documents_zone=documents,
                                  a_un_polygone=polygone),
        provenance=provenance, avertissements=avert, balises=balises)


# =====================================================================
# comparer_lots
# =====================================================================

def _distances_zone(code_zone: int | None) -> dict[TypeCommodite, float | None]:
    d: dict[TypeCommodite, float | None] = {t: None for t in TYPES_DISTANCE}
    if code_zone is None:
        return d
    for com in commodites_de_zone(code_zone)[0]:
        if com.type in TYPES_DISTANCE and com.distance_km is not None:
            prev = d[com.type]
            d[com.type] = com.distance_km if prev is None else min(prev, com.distance_km)
    return d


def _ids_min(valeurs: dict[int, float | int | None], maximum: bool = False) -> list[int]:
    connues = {k: v for k, v in valeurs.items() if v is not None}
    if not connues:
        return []
    cible = max(connues.values()) if maximum else min(connues.values())
    return sorted(k for k, v in connues.items() if v == cible)


def comparer_lots(entree: ComparerLotsEntree, conn: Connection | None = None) -> SortieOutil[ComparerLotsDonnees]:
    ids = list(dict.fromkeys(entree.lot_ids))
    with _connexion(conn) as c:
        lignes = repo.lots_par_ids(c, ids, _PRIX_EXCLUS)
    trouves = {l.lot_id: construire_lot(l) for l in lignes}
    avert = [Avertissement(code=C.lot_introuvable, lot_id=i) for i in ids if i not in trouves]
    lots = [trouves[i] for i in ids if i in trouves]
    lignes_comp = [LigneComparaison(lot=l, distances_km=_distances_zone(l.zone_id)) for l in lots]
    avert += _avertissements_globaux(lots)
    donnees = ComparerLotsDonnees(
        lignes=lignes_comp,
        prix_total_le_plus_bas=_ids_min({l.lot_id: l.prix_total_indicatif_dt for l in lots}),
        prix_m2_le_plus_bas=_ids_min({l.lot_id: l.prix_indicatif_dt_m2 for l in lots}),
        surface_la_plus_grande=_ids_min({l.lot_id: l.surface_m2 for l in lots}, maximum=True),
        plus_proche={t: _ids_min({lc.lot.lot_id: lc.distances_km[t] for lc in lignes_comp})
                     for t in sorted(TYPES_DISTANCE, key=lambda t: t.value)},
    )
    prov = _prov_lots(lots) + [Provenance(type="sql", table="afi.zone_commodites",
                                          ids=sorted({str(l.zone_id) for l in lots if l.zone_id is not None}),
                                          date_donnees=DATE_INSTANTANE_AFI)]
    return SortieOutil[ComparerLotsDonnees](
        outil="comparer_lots", donnees=donnees, provenance=prov, avertissements=avert,
        balises=[balise_lot(l) for l in lots])


# =====================================================================
# lots_proches
# =====================================================================

def _equipement(code_zone: int, type_) -> tuple[str | None, float | None, bool, str | None]:
    """(nom, distance_km, ambigu, complement) de l'équipement le plus proche de ce type pour la zone.
    `complement` : détail de la source quand la distance vient de assistant.zone_complements."""
    if isinstance(type_, TypeCommodite):
        meilleur, ambigu = (None, None, None), False
        com_id = COM_ID_PAR_TYPE[type_]
        for r in lignes_commodites(code_zone):
            if r["com_id"] != com_id or (r["zc_unite"] or "").strip() != "km":
                continue
            d = distance_depuis_texte(r["value"])
            if d is None:
                ambigu = True
            elif meilleur[1] is None or d < meilleur[1]:
                meilleur = ((r["zc_libelle_francais"] or "").strip() or None, d, r.get("complement"))
        return meilleur[0], meilleur[1], ambigu, meilleur[2]
    for s in services_de_zone(code_zone):
        if s.categorie == type_:
            return s.nom, s.distance_km, False, None
    return None, None, False, None


def lots_proches(entree: LotsProchesEntree, conn: Connection | None = None) -> SortieOutil[LotsProchesDonnees]:
    avert: list[Avertissement] = []
    zones_idx = _zones_par_code()

    def sortie(zones: list[ZoneProche], ref, total: int) -> SortieOutil[LotsProchesDonnees]:
        if not zones:
            avert.append(Avertissement(code=C.aucun_resultat))
        tables = ["afi.zones", "afi.lots"]
        if isinstance(entree.type, TypeCommodite):
            tables.append("afi.zone_commodites")
        elif entree.type is not None:
            tables.append("afi.zone_services")
        return SortieOutil[LotsProchesDonnees](
            outil="lots_proches",
            donnees=LotsProchesDonnees(zones=zones, reference=ref, total_correspondants=total),
            provenance=[Provenance(type="sql", table=t, ids=[str(z.zone.zone_id) for z in zones] if t == "afi.zones" else [],
                                   date_donnees=DATE_INSTANTANE_AFI) for t in tables],
            avertissements=avert,
            balises=[balise_zone(z.zone.zone_id, z.zone.nom) for z in zones])

    # Référence éventuelle
    ref: tuple[float, float] | None = None
    if entree.point is not None:
        ref = (entree.point.lat, entree.point.lon)
    elif entree.lot_id is not None or entree.zone_id is not None:
        code = entree.zone_id
        if entree.lot_id is not None:
            with _connexion(conn) as c:
                lignes = repo.lots_par_ids(c, [entree.lot_id], _PRIX_EXCLUS)
            if not lignes:
                avert.append(Avertissement(code=C.lot_introuvable, lot_id=entree.lot_id))
                return sortie([], None, 0)
            if lignes[0].code_zone is None:
                avert.append(Avertissement(code=C.lot_orphelin, lot_id=entree.lot_id))
                return sortie([], None, 0)
            code = lignes[0].code_zone
        if code not in zones_idx:
            avert.append(Avertissement(code=C.zone_introuvable, zone_id=code))
            return sortie([], None, 0)
        ref = coordonnees_valides(zones_idx[code]["zone_lat"], zones_idx[code]["zone_long"])
        if ref is None:
            avert.append(Avertissement(code=C.coordonnees_manquantes, zone_id=code))
            return sortie([], None, 0)

    gouv_id = None
    if entree.gouvernorat:
        gouv_id = gouv_id_depuis_nom(entree.gouvernorat)
        if gouv_id is None:
            avert.append(Avertissement(code=C.gouvernorat_non_reconnu, detail=entree.gouvernorat))
            return sortie([], None, 0)

    comptes = repo.comptes_lots_par_zone_etape()
    etapes_dispo, _ = etapes_pour([StatutLot.disponible])
    etapes_ench, _ = etapes_pour([StatutLot.aux_encheres])
    sans_coord, ambigus = 0, 0
    candidats: list[ZoneProche] = []
    complets: list[Avertissement] = []
    for code, z in zones_idx.items():
        if gouv_id is not None and z["gouv_id"] != gouv_id:
            continue
        n_dispo = sum(comptes.get((code, e), 0) for e in etapes_dispo)
        n_ench = sum(comptes.get((code, e), 0) for e in etapes_ench)
        if entree.uniquement_avec_lots_disponibles and n_dispo == 0:
            continue
        eq_nom, eq_dist, ambigu, complement = (None, None, False, None)
        if entree.type is not None:
            eq_nom, eq_dist, ambigu, complement = _equipement(code, entree.type)
        if ref is None:
            if eq_dist is None:
                ambigus += ambigu
                continue
            cle, mode = eq_dist, "equipement_selon_donnees"
        else:
            coords = coordonnees_valides(z["zone_lat"], z["zone_long"])
            if coords is None:
                sans_coord += 1
                continue
            cle, mode = round(haversine_km(ref, coords), 2), "vol_oiseau_depuis_reference"
        if entree.distance_max_km is not None and cle > entree.distance_max_km:
            continue
        if complement:
            complets.append(Avertissement(code=C.valeur_complementaire, zone_id=code, detail=complement))
        candidats.append(ZoneProche(
            zone=zone_resume(z), distance_km=cle, mode_distance=mode,
            equipement_nom=eq_nom, equipement_distance_km=eq_dist,
            nb_lots_disponibles=n_dispo, nb_lots_aux_encheres=n_ench))

    if sans_coord:
        avert.append(Avertissement(code=C.coordonnees_manquantes, detail=f"{sans_coord} zones écartées"))
    if ambigus:
        avert.append(Avertissement(code=C.distance_ambigue, detail=f"{ambigus} zones écartées"))
    if any(z.zone.prix_indicatif_dt_m2 is not None for z in candidats):
        avert.append(Avertissement(code=C.prix_indicatif))
    avert.append(Avertissement(code=C.donnee_non_fraiche, detail="comptes de lots du dump du 13/11/2026"))
    candidats.sort(key=lambda z: (z.distance_km, z.zone.zone_id))
    total = len(candidats)
    gardees = {z.zone.zone_id for z in candidats[: entree.limite]}
    avert += [a for a in complets if a.zone_id in gardees]
    avert += [Avertissement(code=C.valeur_complementaire, zone_id=z.zone.zone_id, detail="prix")
              for z in candidats[: entree.limite]
              if C.valeur_complementaire in prix_zone(z.zone.zone_id)[1]]
    if total > entree.limite:
        avert.append(Avertissement(code=C.resultats_tronques, detail=f"{entree.limite}/{total}"))
    return sortie(candidats[: entree.limite], Coordonnees(lat=ref[0], lon=ref[1]) if ref else None, total)
