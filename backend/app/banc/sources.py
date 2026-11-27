"""Bloc « Sources » affiché sous chaque réponse (BF14 : réponse avec le lien de la source).

Construit par le code à partir des résultats des outils du tour, jamais rédigé par le modèle : la réponse
reste courte et lisible (à l'écran et à voix haute), et les liens, dates et textes exacts sont ici.
"""
from __future__ import annotations

from typing import Any

MAX_SOURCES = 12
_ROLES = {"octroi_avantages": "avantages", "premier_contact": "premier contact", "accompagnement": "accompagnement"}


def _ajouter(liste: list[dict], vus: set, **s: Any) -> None:
    cle = (s.get("titre"), s.get("url"), (s.get("extrait") or "")[:60])
    if cle not in vus and len(liste) < MAX_SOURCES:
        vus.add(cle)
        liste.append({k: v for k, v in s.items() if v not in (None, "", [])})


def sources_du_tour(appels: list[dict]) -> list[dict]:
    """[{titre, url?, date?, extrait?, a_verifier?}] à partir des appels d'outils (`Banc.dernier_tour`)."""
    res: list[dict] = []
    vus: set = set()
    base_afi = None
    for a in appels:
        r = a.get("resultat") or {}
        d = r.get("donnees") or {}
        if a.get("outil") == "avantages":
            for o in d.get("orientation", []):
                _ajouter(res, vus, titre=f"{o['organisation']} ({_ROLES.get(o['role'], o['role'])})", url=o.get("url"),
                         date=o.get("date_source"), extrait=o.get("citation"))
            for i in d.get("incitations", []):
                _ajouter(res, vus, titre=" — ".join(x for x in (i.get("organisme"), i.get("intitule")) if x)[:160],
                         url=i.get("url"), date=i.get("date_source"), extrait=i.get("extrait"),
                         a_verifier="ancien code d'incitation (loi 93-120)" if i.get("regime_ancien") else None)
            continue
        if a.get("outil") == "demarches_administratives":
            for f in d.get("fiches", []):
                extrait = "\n".join(f.get("conditions", []) + f.get("pieces", []) + f.get("etapes", []))
                _ajouter(res, vus, titre=f"SICAD — {f['titre']}"[:160], url=f.get("url"), date=f.get("date_source"),
                         extrait=extrait or None,
                         a_verifier="fiche du dump AFI, à vérifier sur SICAD" +
                                    (" ; ancien code d'incitation (loi 93-120)" if f.get("regime_ancien") else ""))
            continue
        if a.get("outil") == "connaissances_afi":
            for f in d.get("fiches", []):
                _ajouter(res, vus, titre=f"AFI — fiche validée n° {f['fiche']} : {f['question']}"[:160],
                         date=next((p.get("date_donnees") for p in r.get("provenance", [])), None),
                         extrait=f.get("reponse"))
            continue
        if a.get("outil") == "regles_zone" and d.get("cahier"):
            c = d["cahier"]
            for p in d.get("passages", []):
                lieu = ", ".join(x for x in (f"article {p['article']}" if p.get("article") else None,
                                             f"page {p['pages'][0]}" if p.get("pages") else None,
                                             f"catégorie {p['categorie_sol']}" if p.get("categorie_sol") else None) if x)
                _ajouter(res, vus, titre=f"{c['titre']}" + (f" — {lieu}" if lieu else ""), date=c.get("date_collecte"),
                         extrait=p.get("texte"), a_verifier="texte extrait du PDF, non relu")
            continue
        for p in r.get("provenance", []):
            if p.get("url"):
                _ajouter(res, vus, titre=p["url"].split("/")[2], url=p["url"], date=p.get("date_donnees"))
            elif (p.get("table") or "").startswith("afi.") and base_afi is None:
                base_afi = p.get("date_donnees")
                _ajouter(res, vus, titre="Base de données de l'AFI (instantané)", date=base_afi)
    return res
