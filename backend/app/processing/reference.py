"""Données de référence stables, chacune avec sa source (voir docs/).

Rien ici n'est un chiffre métier inventé : ce sont des correspondances de codes
relevées sur des sources AFI publiques, ou des constats faits sur les données.
"""
from __future__ import annotations

import re
import unicodedata
from enum import Enum

URL_CARTE_PUBLIQUE = "https://afi.e-industrie.gov.tn/"
URL_LISTE_LOTS_DISPONIBLES = "https://afi.e-industrie.gov.tn/liste.php"
# L'URL source des services vient de la base (assistant.sources), plus du code.

# ---------- Gouvernorats (zones.gouv_id) ----------
# Source : colonne « Gvt » de liste.php (26/11/2026) pour les zones rattachées à un code_zone.
# 15 : zone 931103 (Tejra) rangée sous « Mednine » sur le site ; zones 930614 Ben Gerdane et
#      932104 Zarzis ont aussi gouv_id 15.
# 8  : déduit (seule zone : 932001 « GAFSA » ; seul gouvernorat restant). Voir docs/qualite_donnees.md.
GOUVERNORATS: dict[int, str] = {
    1: "Tunis", 2: "Ariana", 3: "Ben Arous", 4: "La Manouba", 5: "Béja", 6: "Bizerte",
    7: "Gabès", 8: "Gafsa", 9: "Jendouba", 10: "Kairouan", 11: "Kasserine", 12: "Kébili",
    13: "Le Kef", 14: "Mahdia", 15: "Médenine", 16: "Monastir", 17: "Nabeul", 18: "Sidi Bouzid",
    19: "Siliana", 20: "Sfax", 21: "Sousse", 22: "Tataouine", 23: "Tozeur", 24: "Zaghouan",
}
GOUVERNORATS_DEDUITS = {8}

# Variantes d'écriture acceptées en entrée (le module langue du rôle 4 normalise en amont ;
# ceci n'est qu'un filet de sécurité). Noms arabes officiels des gouvernorats.
_VARIANTES_GOUV: dict[int, tuple[str, ...]] = {
    1: ("tunis", "تونس"), 2: ("ariana", "اريانة", "أريانة"), 3: ("ben arous", "بن عروس"),
    4: ("manouba", "la manouba", "منوبة"), 5: ("beja", "باجة"), 6: ("bizerte", "بنزرت"),
    7: ("gabes", "قابس"), 8: ("gafsa", "قفصة"), 9: ("jendouba", "جندوبة"),
    10: ("kairouan", "kairouen", "القيروان"), 11: ("kasserine", "القصرين"),
    12: ("kebili", "قبلي"), 13: ("kef", "le kef", "el kef", "الكاف"), 14: ("mahdia", "المهدية"),
    15: ("medenine", "mednine", "مدنين"), 16: ("monastir", "المنستير"), 17: ("nabeul", "نابل"),
    18: ("sidi bouzid", "سيدي بوزيد"), 19: ("siliana", "سليانة"), 20: ("sfax", "صفاقس"),
    21: ("sousse", "سوسة"), 22: ("tataouine", "تطاوين"), 23: ("tozeur", "توزر"),
    24: ("zaghouan", "زغوان"),
}


def normaliser(texte: str | None) -> str:
    """Minuscules, sans accents latins, espaces et ponctuation simplifiés (l'arabe est conservé)."""
    if not texte:
        return ""
    t = unicodedata.normalize("NFKD", texte)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.lower().replace("’", "'")
    t = re.sub(r"[-_'’`]", " ", t)
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_INDEX_GOUV = {normaliser(v): gid for gid, vs in _VARIANTES_GOUV.items() for v in vs}
_INDEX_GOUV.update({normaliser(nom): gid for gid, nom in GOUVERNORATS.items()})


def gouv_id_depuis_nom(nom: str | None) -> int | None:
    n = normaliser(nom)
    n = re.sub(r"^(gouvernorat de|gouvernorat du|gouvernorat|wilayet|wilaya|ولاية)\s+", "", n)
    return _INDEX_GOUV.get(n)


# ---------- Commodités (zone_commodites.com_id) ----------
# Source : /data/zone-commodites.php de la carte publique (COM_ID -> COM_LIB_FR), lu le 26/11/2026.

class TypeCommodite(str, Enum):
    aeroport = "aeroport"
    port = "port"
    gare = "gare"
    autoroute = "autoroute"
    route_gp = "route_gp"
    electricite = "electricite"
    eau_potable = "eau_potable"
    gaz_naturel = "gaz_naturel"
    maintenance_gmg = "maintenance_gmg"
    telephone = "telephone"
    otc = "otc"


# com_id -> (type, libellé officiel COM_LIB_FR, unités attendues dans zc_unite)
COMMODITES: dict[int, tuple[TypeCommodite, str, frozenset[str]]] = {
    1: (TypeCommodite.aeroport, "Aéroport", frozenset({"km"})),
    2: (TypeCommodite.port, "Port", frozenset({"km"})),
    3: (TypeCommodite.gare, "Gare Ferroviaire", frozenset({"km"})),
    4: (TypeCommodite.autoroute, "Autoroute", frozenset({"km"})),
    5: (TypeCommodite.route_gp, "GP", frozenset({"km"})),
    6: (TypeCommodite.electricite, "Electricité", frozenset({"Kva/Hec"})),
    7: (TypeCommodite.eau_potable, "Eau potable", frozenset({"m3/j/hec"})),
    8: (TypeCommodite.gaz_naturel, "Gaz Naturel", frozenset({"bar"})),
    10: (TypeCommodite.maintenance_gmg, "Maintenance", frozenset({"actif", "constitué"})),
    11: (TypeCommodite.telephone, "Réseau téléphonique", frozenset({"paires"})),
    12: (TypeCommodite.otc, "OTC", frozenset({"assainie", "Assainie", "partie", "abandonnée"})),
}
TYPES_DISTANCE = {TypeCommodite.aeroport, TypeCommodite.port, TypeCommodite.gare,
                  TypeCommodite.autoroute, TypeCommodite.route_gp}
COM_ID_PAR_TYPE = {t: cid for cid, (t, _, _) in COMMODITES.items()}


# ---------- Services de proximité (zone_services.categorie, source OpenStreetMap) ----------

class TypeServiceProximite(str, Enum):
    banque = "bank"
    clinique = "clinique"
    hopital = "hospital"
    ecole = "ecole"
    college = "college"
    lycee = "lycee"
    faculte = "faculte"
    hotel = "hotel"
    restaurant = "restaurant"
    parking = "parking"
    poste = "poste"


# ---------- Prix ----------
# Valeur aberrante constatée : prixunitaire = 2022 alors que liste.php affiche 100 Dt/m² (26/11/2026).
PRIX_ABERRANTS: dict[int, str] = {
    9302051: "prixunitaire=2022 dans le dump ; liste.php affiche 100 Dt/m² le 26/11/2026",
}
# Zones dont le prix du dump diffère du prix affiché par liste.php le 26/11/2026.
PRIX_ECART_SITE_PUBLIC: dict[int, int] = {
    88888: 50, 931804: 118, 932119: 90, 930606: 100, 930602: 100,
}

# ---------- Coordonnées ----------
LAT_TUNISIE = (30.0, 38.0)
LON_TUNISIE = (7.0, 12.0)


def coordonnees_valides(lat: str | float | None, lon: str | float | None) -> tuple[float, float] | None:
    """Coordonnées utilisables, ou None (vide, non numérique, égales, hors Tunisie)."""
    try:
        la, lo = float(str(lat).strip()), float(str(lon).strip())
    except (TypeError, ValueError):
        return None
    if la == lo:
        return None
    if LAT_TUNISIE[0] <= la <= LAT_TUNISIE[1] and LON_TUNISIE[0] <= lo <= LON_TUNISIE[1]:
        return la, lo
    return None
