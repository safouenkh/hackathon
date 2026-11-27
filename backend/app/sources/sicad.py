"""Fiches SICAD (démarches administratives) : analyse des extraits de afi.chatbot_sources et import.

SICAD (sicad.gov.tn) est le portail des démarches administratives tunisiennes. Le dump AFI en garde
127 extraits (collectés le 2026-10-23) : 67 fiches « Prestations » (conditions, pièces, étapes, lieu de
dépôt, délai, références) et 60 fiches « Cahiers des charges » d'activités (ministère, domaine, documents).
Le cahier des charges du hackathon (§IV.5) les donne comme point de départ de la famille « Démarche ».

Chaque fiche devient un document `fiche_sicad` (même URL = même document) dont le texte est remis en
forme par sections, SANS changer les phrases : titres de sections ajoutés, libellés « Adresse : » joints
à leur valeur, et cellules du tableau des étapes séparées par « — » (le dump les a collées). Les
métadonnées (type, organismes, secteur, domaine, documents joints) vont dans assistant.demarches_externes
(migration 0006) : le graphe RDF des démarches est construit depuis cette table.

Le texte vient d'une page web : c'est une donnée, jamais une instruction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.sources import organismes as org

TYPE_DOCUMENT = "fiche_sicad"
ORGANISATION = "SICAD"
ORIGINE = "sicad"

# En-têtes du corps d'une fiche « Prestations » -> (code, titre de section du Markdown)
_SECTIONS = {
    "conditions d'obtention de la prestation": ("conditions", "Conditions d'obtention"),
    "pièces à fournir": ("pieces", "Pièces à fournir"),
    "etapes intervenants délais": ("etapes", "Étapes (étape — intervenant — délai)"),
    "lieu de dépôt du dossier": ("lieu_depot", "Lieu de dépôt du dossier"),
    "lieu d'obtention de la prestation": ("lieu_obtention", "Lieu d'obtention"),
    "délai d'octroi de la prestation": ("delai", "Délai d'octroi"),
    "références législatives et / ou réglementaires": ("references", "Références législatives et réglementaires"),
}
TITRES_SECTIONS = {code: titre for code, titre in _SECTIONS.values()}
_FIN_CORPS = "ministères & organismes"
_DEBUT_CONTACTS = "secteurs & domaines"
_LIBELLES_CONTACT = {"adresse", "e-mail", "téléphone", "fax", "site web"}
_LIBELLES_DOCUMENTS = {"document", "imprimé"}
_LIENS = {"en savoir plus"}                             # texte d'un lien de la page, sans contenu
_CODE_POSTAL = re.compile(r"\b\d{4}\b")
_URL = re.compile(r"^(https?://|www\.)\S+$", re.I)
_MAIL = re.compile(r"^\S+@\S+\.\S+$")
_TEL = re.compile(r"^[\d\s./\-+()]+$")
# Cellules collées par le dump : « plansLe service… » -> « plans — Le service… » (minuscule puis majuscule)
_CELLULES = re.compile(r"(?<=[a-zàâçéèêëîïôûùüÿœ)\].])(?=[A-ZÀÂÇÉÈÊËÎÏÔÛÙÜŸŒ])")


def _cle(ligne: str) -> str:
    return re.sub(r"\s+", " ", ligne.strip().rstrip(":").strip()).lower()


def _valeur_contact(ligne: str) -> bool:
    l = ligne.strip()
    return bool(_URL.match(l) or _MAIL.match(l) or (_TEL.match(l) and sum(c.isdigit() for c in l) >= 6))


def _adresse(ligne: str) -> bool:
    """Ligne d'adresse : texte avec un code postal (ex. « 65, rue de Syrie 1002 Tunis »)."""
    return bool(_CODE_POSTAL.search(ligne)) and not _valeur_contact(ligne)


@dataclass
class FicheSicad:
    id_source: int
    url: str
    titre: str
    type_fiche: str                                     # prestation | cahier_des_charges
    sections: dict[str, list[str]] = field(default_factory=dict)
    contacts: list[str] = field(default_factory=list)   # lignes du bloc des organismes (contacts publics)
    organismes: list[str] = field(default_factory=list)
    secteur: str | None = None
    domaine: str | None = None                          # tel qu'affiché (ex. « Assainissement / Prestations… »)
    documents: list[str] = field(default_factory=list)  # titres des documents joints sur SICAD
    recupere_le: date | None = None

    @property
    def domaines(self) -> list[str]:
        """Catégories SICAD du domaine (« A / B » -> [A, B])."""
        return [d.strip() for d in (self.domaine or "").split("/") if d.strip()]

    def markdown(self) -> str:
        blocs = [f"# {self.titre}"]
        for code, lignes in self.sections.items():
            if lignes:
                blocs.append(f"## {TITRES_SECTIONS[code]}\n\n" + "\n".join(lignes))
        if self.contacts:
            blocs.append("## Ministères et organismes\n\n" + "\n".join(self.contacts))
        dom = [f"Secteur : {self.secteur}" if self.secteur else "", f"Domaine : {self.domaine}" if self.domaine else ""]
        if any(dom):
            blocs.append("## Secteur et domaine (SICAD)\n\n" + "\n".join(d for d in dom if d))
        if self.documents:
            blocs.append("## Documents joints sur SICAD\n\n" + "\n".join(self.documents))
        return "\n\n".join(blocs) + "\n"


def type_de_fiche(url: str) -> str:
    return "cahier_des_charges" if "/Cahiers-des-charges_" in url else "prestation"


def _joindre_libelles(lignes: list[str]) -> list[str]:
    """« Adresse : » seul sur sa ligne, suivi de sa valeur -> « Adresse : valeur »."""
    res: list[str] = []
    for l in lignes:
        if res and res[-1].endswith(":") and _cle(res[-1]) not in _SECTIONS and len(res[-1]) <= 40:
            res[-1] = f"{res[-1]} {l}"
        else:
            res.append(l)
    return res


def _contacts(lignes: list[str]) -> tuple[list[str], list[str], str | None, str | None, list[str]]:
    """Bloc après « Secteurs & Domaines » : (lignes de contact, organismes, secteur, domaine, documents).

    Valeurs de contact : site, e-mail, téléphone, adresse (code postal à 4 chiffres). Un organisme est
    une ligne de texte suivie du libellé « Adresse » ou d'une adresse ; quand la page ne donne qu'une
    adresse et un site (sans nom), aucun nom n'est déduit. Après la dernière valeur de contact
    viennent le secteur, le domaine, puis les titres des documents joints.
    """
    lignes = [l.strip() for l in lignes if _cle(l) not in _LIENS]
    valeurs = [i for i, l in enumerate(lignes) if _valeur_contact(l) or _adresse(l)]
    fin = valeurs[-1] + 1 if valeurs else min(1, len(lignes))
    zone, reste = lignes[:fin], lignes[fin:]
    organismes = [l for i, l in enumerate(zone)
                  if _cle(l) not in _LIBELLES_CONTACT and not _valeur_contact(l) and not _adresse(l)
                  and (i + 1 == len(zone) and not valeurs or i + 1 < len(zone)
                       and (_cle(zone[i + 1]) == "adresse" or _adresse(zone[i + 1])))]
    contacts: list[str] = []
    i = 0
    while i < len(zone):                 # « Téléphone » puis « 71… » -> « Téléphone : 71… »
        if _cle(zone[i]) in _LIBELLES_CONTACT and i + 1 < len(zone) and _cle(zone[i + 1]) not in _LIBELLES_CONTACT:
            contacts.append(f"{zone[i].rstrip(' :')} : {zone[i + 1]}")
            i += 2
        else:
            contacts.append(zone[i])
            i += 1
    sans_libelles = [l for l in reste if _cle(l) not in _LIBELLES_DOCUMENTS]
    secteur = sans_libelles[0] if sans_libelles else None
    domaine = sans_libelles[1] if len(sans_libelles) > 1 else None
    return contacts, organismes, secteur, domaine, sans_libelles[2:]


def analyser(id_source: int, url: str, titre: str, contenu: str, recupere_le: date | None = None) -> FicheSicad:
    lignes = [l.strip() for l in contenu.splitlines() if l.strip()]
    titre = re.sub(r"\s+", " ", (titre or (lignes[0] if lignes else url))).strip()
    f = FicheSicad(id_source=id_source, url=url, titre=titre, type_fiche=type_de_fiche(url), recupere_le=recupere_le)
    cles = [_cle(l) for l in lignes]
    fin = cles.index(_FIN_CORPS) if _FIN_CORPS in cles else len(lignes)
    corps = lignes[1:fin] if lignes and _cle(lignes[0]) == _cle(titre) else lignes[:fin]
    courant: str | None = None
    hors_section: list[str] = []
    for l in corps:
        cle = _cle(l)
        if cle in _SECTIONS:
            courant = _SECTIONS[cle][0]
            f.sections.setdefault(courant, [])
        elif cle == "service" and courant == "lieu_depot":
            continue                     # sous-libellé « Service : » du lieu de dépôt
        elif courant is None:
            hors_section.append(l)
        else:
            f.sections[courant].append(_CELLULES.sub(" — ", l) if courant == "etapes" else l)
    if hors_section:                     # texte avant la première section : gardé en tête des conditions
        f.sections = {"conditions": hors_section + f.sections.pop("conditions", []), **f.sections}
    f.sections = {k: _joindre_libelles(v) for k, v in f.sections.items()}
    if _DEBUT_CONTACTS in cles:
        f.contacts, f.organismes, f.secteur, f.domaine, f.documents = _contacts(lignes[cles.index(_DEBUT_CONTACTS) + 1:])
    return f


# ---------------------------------------------------------------------
# Import (dans la transaction de scripts.importer_organismes)
# ---------------------------------------------------------------------

def lire_fiches(conn) -> list[FicheSicad]:
    return [analyser(i, u, t, c, d) for i, u, t, c, d in conn.execute(
        "SELECT id, url, titre, contenu, created_at::date FROM afi.chatbot_sources "
        "WHERE lower(source) = 'sicad' AND url IS NOT NULL AND coalesce(contenu, '') <> '' ORDER BY id LIMIT 1000"
    ).fetchall()]


def ecrire(conn, r: "org.Rapport") -> int:
    """Fiches SICAD -> documents `fiche_sicad` + métadonnées. Renvoie le nombre de fiches."""
    fiches = lire_fiches(conn)
    for f in fiches:
        sid = org._un(conn, "SELECT id FROM assistant.sources WHERE url = %s", (f.url,))
        if sid is None:     # page connue seulement par le dump : jamais lue par nous
            sid = org._un(conn, "INSERT INTO assistant.sources (organisation, title, url, ingestion_mode, last_status) "
                                "VALUES (%s, %s, %s, 'manuel', 'dump_afi') RETURNING id", (ORGANISATION, f.titre, f.url))
        vid = org._version(
            conn, r, source_id=sid, url=f.url, titre=f.titre, texte=f.markdown(), chemin=None,
            provenance=(f"Extrait afi.chatbot_sources id={f.id_source} (dump AFI, fiche SICAD), collecté le "
                        f"{f.recupere_le} ; remis en forme par sections (phrases inchangées, cellules du tableau "
                        "des étapes séparées par « — ») ; non relu."),
            recupere_le=f.recupere_le, etiquette=f"sicad:{f.id_source}", type_document=TYPE_DOCUMENT)
        conn.execute(
            "INSERT INTO assistant.demarches_externes (version_id, origine, id_source, type_fiche, titre, organismes, "
            "secteur, domaines, documents_joints) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (version_id) DO UPDATE SET id_source = EXCLUDED.id_source, type_fiche = EXCLUDED.type_fiche, "
            "titre = EXCLUDED.titre, organismes = EXCLUDED.organismes, secteur = EXCLUDED.secteur, "
            "domaines = EXCLUDED.domaines, documents_joints = EXCLUDED.documents_joints",
            (vid, ORIGINE, f.id_source, f.type_fiche, f.titre, f.organismes, f.secteur, f.domaines, f.documents))
    return len(fiches)
