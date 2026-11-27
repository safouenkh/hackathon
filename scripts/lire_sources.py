"""Lit les liens configurés des organismes (sources-organismes/liens.json) et garde chaque réponse brute.

Usage :
    .venv\\Scripts\\python.exe -m scripts.lire_sources              # lit les liens absents ou en échec
    .venv\\Scripts\\python.exe -m scripts.lire_sources --tout       # relit tout

Règles (cahier BNF14) : seules les URL de la liste sont lues ; robots.txt respecté ; une page par
seconde au plus ; aucune donnée personnelle envoyée (agent générique). Une lecture en échec garde
la dernière version réussie. Le contenu lu est une DONNÉE : il n'est jamais exécuté.
Sortie : sources-organismes/brut/<fichier> et sources-organismes/manifeste.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

DOSSIER = Path(__file__).resolve().parents[1] / "sources-organismes"
AGENT = "DalilaHackathonBot/0.1 (lecture de pages publiques, une par seconde)"
TAILLE_MAX = 25 * 1024 * 1024
PAUSE_S = 1.0
TYPES = {"text/html": ".html", "application/pdf": ".pdf"}


def nom_fichier(url: str, type_: str) -> str:
    p = urlsplit(url)
    base = re.sub(r"[^a-zA-Z0-9]+", "-", f"{p.netloc}{p.path}{'-' + p.query if p.query else ''}").strip("-").lower()
    base = re.sub(r"-(html|pdf|asp)$", "", base)[:120]
    return base + TYPES.get(type_, ".bin")


def _robots(hote: str, cache: dict) -> urllib.robotparser.RobotFileParser | None:
    if hote not in cache:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(f"{hote}/robots.txt", headers={"User-Agent": AGENT})
            with urllib.request.urlopen(req, timeout=20) as r:
                rp.parse(r.read(200_000).decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):          # convention : accès refusé -> rien n'est lu
                rp.parse(["User-agent: *", "Disallow: /"])
            elif 400 <= exc.code < 500:         # pas de robots.txt -> tout est permis
                rp.parse([])
            else:
                rp = None
        except (urllib.error.URLError, TimeoutError, OSError):
            rp = None              # robots.txt injoignable : noté, la page est tentée une fois
        cache[hote] = rp
    return cache[hote]


# Titres de pages d'erreur d'hébergeur (réponse 200 sans le contenu demandé) : la page n'est pas une source.
_TITRES_ERREUR = re.compile(r"<title>\s*(account suspended|site suspended|403 forbidden|404 not found|"
                            r"page not found|just a moment|attention required|access denied)\b", re.I)


def page_erreur(type_: str, corps: bytes) -> str | None:
    if type_ != "text/html":
        return None
    m = _TITRES_ERREUR.search(corps[:20_000].decode("utf-8", "replace"))
    return m.group(1) if m else None


def lire(url: str) -> tuple[int, str, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        type_ = (r.headers.get_content_type() or "").lower()
        corps = r.read(TAILLE_MAX + 1)
        if len(corps) > TAILLE_MAX:
            raise ValueError("réponse trop grande")
        return r.status, type_, corps


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--tout", action="store_true")
    a = p.parse_args()
    liens = json.loads((DOSSIER / "liens.json").read_text(encoding="utf-8"))["liens"]
    chemin_manifeste = DOSSIER / "manifeste.json"
    manifeste = json.loads(chemin_manifeste.read_text(encoding="utf-8")) if chemin_manifeste.exists() else {}
    (DOSSIER / "brut").mkdir(exist_ok=True)
    robots: dict = {}
    derniere = 0.0
    for lien in liens:
        url = lien["url"]
        if lien.get("lien_seul"):       # contenu jamais lu (ex. données personnelles) : le lien suffit
            manifeste[url] = {"organisation": lien["organisation"], "sujet": lien["sujet"], "titre": lien["titre"],
                              "statut": "lien_seul", "raison": lien["lien_seul"]}
            continue
        ancien = manifeste.get(url, {})
        if not a.tout and ancien.get("statut") == "ok":
            continue
        p_url = urlsplit(url)
        rp = _robots(f"{p_url.scheme}://{p_url.netloc}", robots)
        entree = {"organisation": lien["organisation"], "sujet": lien["sujet"], "titre": lien["titre"],
                  "tentative_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "robots_txt": "injoignable" if rp is None else "lu"}
        if rp is not None and not rp.can_fetch(AGENT, url):
            entree |= {"statut": "interdit_robots"}
            manifeste[url] = ancien | entree if ancien.get("statut") == "ok" else entree
            print(f"ROBOTS  {url}")
            continue
        time.sleep(max(0.0, PAUSE_S - (time.monotonic() - derniere)))
        derniere = time.monotonic()
        try:
            code, type_, corps = lire(url)
            erreur = page_erreur(type_, corps)
            if erreur:
                raise ValueError(f"page d'erreur de l'hébergeur (« {erreur} »)")
            fichier = nom_fichier(url, type_)
            (DOSSIER / "brut" / fichier).write_bytes(corps)
            entree |= {"statut": "ok", "http": code, "type": type_, "octets": len(corps),
                       "sha256": hashlib.sha256(corps).hexdigest(), "fichier": f"brut/{fichier}",
                       "lu_le": entree["tentative_le"]}
            manifeste[url] = entree
            print(f"OK {code} {type_:<16} {len(corps):>9} o  {url}")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
            detail = f"{type(exc).__name__}: {getattr(exc, 'code', '')} {getattr(exc, 'reason', exc)}"[:300]
            # Échec : la dernière version réussie reste la référence (BNF14)
            manifeste[url] = (ancien | {"derniere_erreur": detail, "tentative_le": entree["tentative_le"]}
                              if ancien.get("statut") == "ok" else entree | {"statut": "echec", "erreur": detail})
            print(f"ECHEC   {url}  {detail}")
        chemin_manifeste.write_text(json.dumps(manifeste, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for l in liens if manifeste.get(l["url"], {}).get("statut") == "ok")
    print(f"\n{ok}/{len(liens)} liens lus avec succès.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
