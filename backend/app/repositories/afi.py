"""Accès SQL en lecture seule aux tables AFI (schéma `afi`).

Règles : requêtes fixes et paramétrées (jamais de SQL venu du LLM), LIMIT sur chaque requête,
aucune colonne personnelle ou contractuelle (le rôle de connexion ne peut de toute façon pas les lire).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import Connection, text

from app.db import get_engine

LIMITE_REFERENTIEL = 10_000


@dataclass(frozen=True)
class LigneLot:
    lot_id: int
    zone_id_brut: str            # lots.zone_id (texte), conservé même pour un lot orphelin
    numero: str | None
    surface: int | None
    etape: int | None
    code_zone: int | None        # null si orphelin
    prix_total: int | None       # calculé en SQL : surface × prixunitaire, si les deux sont valides
    distance_km: float | None = None  # distance de la zone à l'équipement demandé (chercher_lots)


# ---------- Référentiels (petits, stables : mis en cache pour la durée du processus) ----------

@lru_cache
def zones() -> tuple[dict, ...]:
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT code_zone, zone_libelle_francais, zone_libelle_arabe, gouv_id, prixunitaire, "
            "zone_lat, zone_long, zone_show, zone_devreg FROM afi.zones ORDER BY code_zone LIMIT :n"
        ), {"n": LIMITE_REFERENTIEL}).mappings().all()
    return tuple(dict(r) for r in rows)


@lru_cache
def commodites() -> tuple[dict, ...]:
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT id, code_zone, com_id, zc_libelle_francais, zc_unite, value "
            "FROM afi.zone_commodites ORDER BY code_zone, com_id, id LIMIT :n"
        ), {"n": LIMITE_REFERENTIEL}).mappings().all()
    return tuple(dict(r) for r in rows)


@lru_cache
def services_proximite() -> tuple[dict, ...]:
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT id, code_zone, categorie, nom, distance_km, source "
            "FROM afi.zone_services ORDER BY code_zone, categorie LIMIT :n"
        ), {"n": LIMITE_REFERENTIEL}).mappings().all()
    return tuple(dict(r) for r in rows)


@lru_cache
def comptes_lots_par_zone_etape() -> dict[tuple[int, int | None], int]:
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT z.code_zone, l.lot_etape, count(*) AS n FROM afi.lots l "
            "JOIN afi.zones z ON z.code_zone::text = l.zone_id GROUP BY 1, 2 LIMIT :n"
        ), {"n": LIMITE_REFERENTIEL}).all()
    return {(r.code_zone, r.lot_etape): r.n for r in rows}


@lru_cache
def commodites_par_zone() -> dict[int, tuple[dict, ...]]:
    idx: dict[int, list[dict]] = {}
    for r in commodites():
        idx.setdefault(r["code_zone"], []).append(r)
    return {k: tuple(v) for k, v in idx.items()}


@lru_cache
def services_par_zone() -> dict[int, tuple[dict, ...]]:
    idx: dict[int, list[dict]] = {}
    for r in services_proximite():
        idx.setdefault(r["code_zone"], []).append(r)
    return {k: tuple(v) for k, v in idx.items()}


@lru_cache
def complements_par_zone() -> dict[int, dict[str, dict]]:
    """Valeurs absentes de la base AFI, prises d'une autre source (migration 0003), avec cette source.
    code_zone -> champ (« prixunitaire », « com_N ») -> {valeur, cle_source, source}."""
    with get_engine().connect() as c:
        rows = c.execute(text(
            "SELECT zc.code_zone, zc.champ, zc.valeur, zc.cle_source, s.title AS source "
            "FROM assistant.zone_complements zc "
            "JOIN assistant.document_versions v ON v.id = zc.version_id "
            "JOIN assistant.documents d ON d.id = v.document_id "
            "JOIN assistant.sources s ON s.id = d.source_id "
            "ORDER BY zc.code_zone, zc.champ LIMIT :n"), {"n": LIMITE_REFERENTIEL}).mappings().all()
    idx: dict[int, dict[str, dict]] = {}
    for r in rows:
        idx.setdefault(r["code_zone"], {})[r["champ"]] = {"valeur": r["valeur"], "cle_source": r["cle_source"],
                                                          "source": r["source"]}
    return idx


def vider_caches() -> None:
    for f in (zones, commodites, services_proximite, comptes_lots_par_zone_etape,
              commodites_par_zone, services_par_zone, complements_par_zone):
        f.cache_clear()


# ---------- Lots ----------

_SELECT_LOT = """
    SELECT l.lot_id, l.zone_id AS zone_id_brut, l.lot_num AS numero, l.lot_sup_lotis AS surface,
           l.lot_etape AS etape, z.code_zone,
           CASE WHEN l.lot_sup_lotis > 0 AND pu.prix > 0
                     AND NOT (z.code_zone = ANY(CAST(:prix_exclus AS integer[])))
                THEN l.lot_sup_lotis::bigint * pu.prix END AS prix_total
    FROM afi.lots l
    LEFT JOIN afi.zones z ON z.code_zone::text = l.zone_id
    -- Prix AFI ; s'il est vide (null ou 0), complément entier sourcé (migration 0003)
    LEFT JOIN assistant.zone_complements zp
           ON zp.code_zone = z.code_zone AND zp.champ = 'prixunitaire' AND zp.valeur = trunc(zp.valeur)
    CROSS JOIN LATERAL (SELECT CASE WHEN z.prixunitaire > 0 THEN z.prixunitaire ELSE zp.valeur END AS prix) pu
"""


def _ligne(r) -> LigneLot:
    km = getattr(r, "km", None)
    return LigneLot(r.lot_id, r.zone_id_brut, r.numero, r.surface, r.etape, r.code_zone,
                    int(r.prix_total) if r.prix_total is not None else None,
                    float(km) if km is not None else None)


def lots_par_ids(conn: Connection, lot_ids: list[int], prix_exclus: list[int]) -> list[LigneLot]:
    rows = conn.execute(text(
        _SELECT_LOT + " WHERE l.lot_id = ANY(CAST(:ids AS integer[])) ORDER BY l.lot_id LIMIT 50"
    ), {"ids": lot_ids, "prix_exclus": prix_exclus}).all()
    return [_ligne(r) for r in rows]


def chercher_lots(
    conn: Connection,
    *,
    etapes: list[int],
    inclure_etapes_inconnues: bool,
    etapes_connues: list[int],
    gouv_id: int | None,
    zone_ids: list[int] | None,
    surface_min: int | None,
    surface_max: int | None,
    budget_max: int | None,
    prix_exclus: list[int],
    limite: int,
    distances_zones: dict[int, float] | None = None,
    tri_par_distance: bool = False,
) -> tuple[list[LigneLot], int, int]:
    """Retourne (lots triés et limités, total correspondant, nb de lots exclus faute de prix).

    `distances_zones` (code_zone -> km), calculé en Python à partir des données AFI/OSM, est joint
    en SQL pour renvoyer la distance de chaque lot et, si demandé, trier dessus.
    """
    dz = distances_zones or {}
    params = {
        "etapes": etapes, "inconnues": inclure_etapes_inconnues, "connues": etapes_connues,
        "gouv": gouv_id, "zones": zone_ids, "smin": surface_min, "smax": surface_max,
        "budget": budget_max, "prix_exclus": prix_exclus, "limite": min(limite, 50),
        "dz": list(dz), "dd": [float(v) for v in dz.values()],
    }
    base = _SELECT_LOT + """
    WHERE (l.lot_etape = ANY(CAST(:etapes AS integer[]))
           OR (CAST(:inconnues AS boolean)
               AND (l.lot_etape IS NULL OR NOT (l.lot_etape = ANY(CAST(:connues AS integer[]))))))
      AND (CAST(:gouv AS integer) IS NULL OR z.gouv_id = CAST(:gouv AS integer))
      AND (CAST(:zones AS integer[]) IS NULL OR z.code_zone = ANY(CAST(:zones AS integer[])))
      AND (CAST(:smin AS integer) IS NULL OR l.lot_sup_lotis >= CAST(:smin AS integer))
      AND (CAST(:smax AS integer) IS NULL OR (l.lot_sup_lotis <= CAST(:smax AS integer) AND l.lot_sup_lotis > 0))
    """
    budget_ok = "(CAST(:budget AS bigint) IS NULL OR c.prix_total <= CAST(:budget AS bigint))"
    ordre = ("d.km ASC NULLS LAST, c.prix_total ASC NULLS LAST, c.lot_id" if tri_par_distance
             else "c.prix_total ASC NULLS LAST, c.surface ASC NULLS LAST, c.lot_id")
    rows = conn.execute(text(
        f"WITH c AS ({base}) SELECT c.*, d.km FROM c "
        "LEFT JOIN unnest(CAST(:dz AS integer[]), CAST(:dd AS float8[])) AS d(code, km) ON d.code = c.code_zone "
        f"WHERE {budget_ok} ORDER BY {ordre} LIMIT :limite"
    ), params).all()
    total, sans_prix = conn.execute(text(
        f"WITH c AS ({base}) SELECT count(*) FILTER (WHERE {budget_ok}), "
        "count(*) FILTER (WHERE c.prix_total IS NULL) FROM c"
    ), params).one()
    return [_ligne(r) for r in rows], int(total), int(sans_prix)


def lot_a_un_polygone(conn: Connection, zone_id_brut: str, numero: str | None) -> bool:
    if numero is None:
        return False
    return conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM afi.lots_kml WHERE zone_id = :z AND lot_num = :n LIMIT 1)"
    ), {"z": zone_id_brut, "n": numero}).scalar_one()


def documents_zone(conn: Connection, code_zone: int) -> list[dict]:
    rows = conn.execute(text(
        "SELECT id, type, fichier, nom_original FROM afi.zone_documents "
        "WHERE zone_id = :z ORDER BY type, id LIMIT 50"
    ), {"z": code_zone}).mappings().all()
    return [dict(r) for r in rows]


# ---------- Base de connaissances ----------

def connaissances(conn: Connection, ids: list[int]) -> dict[int, dict]:
    rows = conn.execute(text(
        "SELECT id, question, reponse, mots_cles, actif, updated_at FROM afi.chatbot_connaissances "
        "WHERE id = ANY(CAST(:ids AS bigint[])) ORDER BY id LIMIT 50"
    ), {"ids": ids}).mappings().all()
    return {r["id"]: dict(r) for r in rows}
