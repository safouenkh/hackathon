"""Extrait le texte des pages lues (sources-organismes/brut/) en Markdown, une source par fichier.

Usage :
    .venv\\Scripts\\python.exe -m scripts.extraire_sources

- HTML : texte principal avec trafilatura (Apache-2.0), sans menus ni pied de page ; tableaux gardés.
- PDF : texte de chaque page avec pypdf, repères « <!-- page N --> ». Un PDF sans texte (image) est signalé.
- En-tête : organisme, titre, lien, date de lecture, SHA-256 de la réponse brute.
Le contenu est une DONNÉE non fiable : jamais exécuté, jamais pris pour une instruction.
Sortie : sources-organismes/md/*.md et sources-organismes/extraction.json (bilan).
"""
from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

DOSSIER = Path(__file__).resolve().parents[1] / "sources-organismes"
MIN_CARACTERES = 200            # en dessous : extraction jugée vide (page JavaScript, image…)


_CHARSET = re.compile(rb"""charset=["']?([\w-]+)""", re.I)


def decoder(octets: bytes) -> str:
    """Décode selon le jeu de caractères déclaré par la page (APII : iso-8859-1, lu en cp1252 qui contient
    les apostrophes typographiques 0x92) ; sans déclaration : UTF-8 s'il est valide, sinon cp1252
    (pages APII pepinieres.asp et idee.asp, sans balise charset : leur lecture en UTF-8 donnait des « � »)."""
    m = _CHARSET.search(octets[:4000])
    if not m:
        try:
            return octets.decode("utf-8")
        except UnicodeDecodeError:
            return octets.decode("cp1252", "replace")
    declare = m.group(1).decode("ascii", "ignore").lower()
    codec = "cp1252" if declare in ("iso-8859-1", "latin-1", "latin1", "windows-1252") else declare
    try:
        return octets.decode(codec, "replace")
    except LookupError:
        return octets.decode("utf-8", "replace")


_IGNORER = {"script", "style", "noscript", "form", "button", "img", "iframe", "svg", "input", "select", "nav"}
_BLOCS = {"p", "div", "section", "article", "blockquote", "center", "dl", "dd", "dt", "address", "main"}


def _texte(el) -> str:
    return re.sub(r"\s+", " ", el.text_content() or "").strip()


def _cellule(el) -> str:
    return _texte(el).replace("|", "\\|")


def _vers_markdown(el, sortie: list[str], niveau_liste: int = 0) -> None:
    """Conversion simple et prévisible : titres, paragraphes, listes, tableaux (texte seulement)."""
    tag = el.tag if isinstance(el.tag, str) else ""
    if tag in _IGNORER:
        return
    if re.fullmatch(r"h[1-6]", tag):
        # HTML mal formé (APII) : un <h2> non fermé peut contenir des listes ou des paragraphes.
        # Le titre = son texte propre ; les blocs inclus sont convertis à part.
        blocs = el.xpath("./ul|./ol|./table|./div|./p")
        if not blocs:
            t = _texte(el)
            if t:
                sortie.append(f"\n{'#' * int(tag[1])} {t}\n")
            return
        titre = re.sub(r"\s+", " ", "".join(
            [el.text or ""] + [_texte(c) + (c.tail or "") for c in el if c not in blocs])).strip()
        if titre:
            sortie.append(f"\n{'#' * int(tag[1])} {titre}\n")
        for b in blocs:
            _vers_markdown(b, sortie, niveau_liste)
            if b.tail and b.tail.strip():
                sortie.append(re.sub(r"\s+", " ", b.tail).strip())
        return
    if tag == "table":
        lignes = [[_cellule(c) for c in tr.xpath("./th|./td")] for tr in el.xpath(".//tr")]
        lignes = [l for l in lignes if any(l)]
        if lignes:
            n = max(len(l) for l in lignes)
            lignes = [l + [""] * (n - len(l)) for l in lignes]
            sortie.append("\n| " + " | ".join(lignes[0]) + " |\n|" + "---|" * n)
            sortie += ["| " + " | ".join(l) + " |" for l in lignes[1:]]
            sortie.append("")
        return
    if tag in ("ul", "ol"):
        # Tous les enfants, et le texte placé hors <li> (l'APII met des <ul> et du texte après des <br>
        # directement dans un <ul>).
        if el.text and el.text.strip():
            sortie.append(re.sub(r"\s+", " ", el.text).strip())
        for enfant in el:
            _vers_markdown(enfant, sortie, niveau_liste + 1 if getattr(enfant, "tag", "") in ("li", "ul", "ol")
                           else niveau_liste)
            if enfant.tail and enfant.tail.strip():
                sortie.append(re.sub(r"\s+", " ", enfant.tail).strip())
        return
    if tag == "li":
        enfants_blocs = el.xpath("./ul|./ol|./table")
        for b in enfants_blocs:
            b.getparent().remove(b)
        t = _texte(el)
        if t:
            sortie.append(f"{'  ' * (niveau_liste - 1)}- {t}")
        for b in enfants_blocs:
            _vers_markdown(b, sortie, niveau_liste)
        return
    if tag in _BLOCS and not el.xpath(".//h1|.//h2|.//h3|.//h4|.//h5|.//h6|.//table|.//ul|.//ol|.//p|.//div"):
        t = _texte(el)
        if t:
            sortie.append(f"\n{t}\n")
        return
    if el.text and el.text.strip():
        sortie.append(re.sub(r"\s+", " ", el.text).strip())
    for enfant in el:
        _vers_markdown(enfant, sortie, niveau_liste)
        if enfant.tail and enfant.tail.strip():
            sortie.append(re.sub(r"\s+", " ", enfant.tail).strip())


def conteneur_markdown(doc, regle: dict) -> str | None:
    """Markdown du bloc principal désigné par la configuration ; None si le bloc est absent."""
    blocs = doc.xpath(regle["bloc"])
    # Tous les blocs, dans l'ordre de la page (APII : un bloc par question dépliable), sans ceux inclus
    # dans un autre bloc retenu.
    blocs = [b for b in blocs if not any(a is not b and b in a.iterdescendants() for a in blocs)]
    if not blocs:
        return None
    sortie: list[str] = []
    for bloc in blocs:
        for xp in regle.get("retirer", []):
            for e in bloc.xpath("." + xp if xp.startswith("//") else xp):
                e.getparent().remove(e)
        _vers_markdown(bloc, sortie)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(sortie)).strip()


def _html_en_markdown(octets: bytes, regle: dict | None = None) -> tuple[str, str]:
    """(texte, méthode). Bloc configuré -> conversion avec titres ; sinon trafilatura."""
    import lxml.html
    import trafilatura

    # Réparation : certaines pages (APII) n'ont ni <html> ni <body> et laissent des <li> ouverts ;
    # sans cela trafilatura ne trouve aucun contenu (0 caractère, cas signalé par l'équipe).
    doc = lxml.html.document_fromstring(decoder(octets))
    html = lxml.html.tostring(doc, encoding="unicode")
    auto = (trafilatura.extract(html, output_format="markdown", include_tables=True, include_links=False,
                                include_images=False, include_comments=False, favor_recall=True,
                                deduplicate=True) or "").strip()
    bloc = conteneur_markdown(doc, regle) if regle else None
    # Le bloc configuré garde les titres ; s'il manque le contenu (page construite autrement), trafilatura.
    if bloc and len(bloc) >= 0.5 * len(auto):
        return bloc, "bloc_configure"
    return auto, "trafilatura"


def _pdf_en_markdown(octets: bytes) -> tuple[str, int]:
    from pypdf import PdfReader

    lecteur = PdfReader(io.BytesIO(octets))
    parties = []
    for n, page in enumerate(lecteur.pages, 1):
        texte = (page.extract_text() or "").strip()
        parties.append(f"<!-- page {n} -->\n\n{texte}")
    return "\n\n".join(parties).strip(), len(lecteur.pages)


def _yaml(valeur) -> str:
    return json.dumps(valeur, ensure_ascii=False)        # chaîne JSON = scalaire YAML valide


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    manifeste = json.loads((DOSSIER / "manifeste.json").read_text(encoding="utf-8"))
    conteneurs = {k: v for k, v in json.loads((DOSSIER / "liens.json").read_text(encoding="utf-8"))
                  .get("conteneurs", {}).items() if not k.startswith("_")}
    (DOSSIER / "md").mkdir(exist_ok=True)
    bilan = {}
    for url, e in manifeste.items():
        if e.get("statut") != "ok":
            bilan[url] = {"statut": "non_lu", "raison": e.get("erreur") or e.get("statut")}
            continue
        brut = (DOSSIER / e["fichier"]).read_bytes()
        pages = None
        try:
            if e["type"] == "application/pdf":
                texte, pages = _pdf_en_markdown(brut)
                methode = "pypdf"
            else:
                from urllib.parse import urlsplit
                texte, methode = _html_en_markdown(brut, conteneurs.get(urlsplit(url).netloc))
        except Exception as exc:       # fichier abîmé : signalé, les autres continuent
            bilan[url] = {"statut": "echec_extraction", "raison": f"{type(exc).__name__}: {exc}"[:300]}
            print(f"ECHEC  {url}  {bilan[url]['raison']}")
            continue
        nb = len(re.sub(r"<!-- page \d+ -->|\s", "", texte))
        statut = "ok" if nb >= MIN_CARACTERES else "texte_insuffisant"
        nom = Path(e["fichier"]).stem + ".md"
        entete = ["---", f"organisation: {_yaml(e['organisation'])}", f"titre: {_yaml(e['titre'])}",
                  f"sujet: {_yaml(e['sujet'])}", f"source_url: {_yaml(url)}",
                  f"type_document: {_yaml('pdf' if pages else 'page_web')}",
                  f"date_collecte: {_yaml(e['lu_le'][:10])}", f"sha256_brut: {_yaml(e['sha256'])}",
                  f"extraction: {_yaml(methode)}", f"statut_extraction: {_yaml(statut)}",
                  "avertissement: \"Texte extrait automatiquement, non relu ; donnée non fiable.\"", "---", ""]
        (DOSSIER / "md" / nom).write_text("\n".join(entete) + texte + "\n", encoding="utf-8")
        bilan[url] = {"statut": statut, "fichier": f"md/{nom}", "caracteres": nb, "methode": methode,
                      **({"pages": pages} if pages else {})}
        print(f"{statut:<18} {nb:>7} car.  {methode:<15} {url}")
    (DOSSIER / "extraction.json").write_text(json.dumps(bilan, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for b in bilan.values() if b["statut"] == "ok")
    print(f"\n{ok}/{len(bilan)} sources extraites avec du texte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
