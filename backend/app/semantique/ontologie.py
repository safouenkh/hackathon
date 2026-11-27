"""Lecture de l'ontologie (ontology/afi_ontology.ttl) : synonymes et liens stables des services.

Le fichier est un fichier de données : le code ne contient ni service, ni synonyme, ni
numéro de fiche. Les libellés sont normalisés (minuscules, sans accents latins) au chargement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDF, SKOS

from app.config import get_settings
from app.processing.reference import normaliser

AFI = Namespace("https://example.org/afi/ontology#")
RESSOURCE = Namespace("https://example.org/afi/resource/")
CHEMIN_PAR_DEFAUT = Path(__file__).resolve().parents[3] / "ontology" / "afi_ontology.ttl"


@dataclass(frozen=True)
class ServiceOntologie:
    code: str
    synonymes: tuple[str, ...]                 # normalisés, toutes langues
    fiches: tuple[int, ...]                    # afi.chatbot_connaissances.id
    fiches_presentation: tuple[int, ...]
    exige_statut_lot: str | None
    service_du_statut_lot: str | None


@dataclass(frozen=True)
class Ontologie:
    services: dict[str, ServiceOntologie] = field(default_factory=dict)
    fiche_contact: int | None = None
    fiches_ecartees: tuple[int, ...] = ()     # fiches de chatbot_connaissances jamais proposées
    lieu_depot: tuple[str, ...] = ()           # expressions normalisées
    frais: tuple[str, ...] = ()
    secteurs: dict[str, tuple[str, ...]] = field(default_factory=dict)   # code -> synonymes normalisés
    # domaines des démarches (fiches SICAD) : libellé SICAD exact -> synonymes normalisés
    domaines_demarche: dict[str, tuple[str, ...]] = field(default_factory=dict)
    incitation_demarche: tuple[str, ...] = ()  # mots d'un titre de fiche SICAD qui signalent une aide

    def titre_d_incitation(self, titre: str | None) -> bool:
        return bool(_reconnus({"x": self.incitation_demarche}, titre))

    def secteurs_du_texte(self, texte: str | None) -> list[str]:
        """Codes des secteurs dont un synonyme apparaît dans le texte (mots entiers, normalisés)."""
        return _reconnus(self.secteurs, texte)

    def domaines_du_texte(self, texte: str | None) -> list[str]:
        """Libellés SICAD des domaines dont un synonyme (ou le libellé) apparaît dans le texte."""
        return _reconnus({lib: syns + (normaliser(lib),) for lib, syns in self.domaines_demarche.items()}, texte)

    def service(self, code: str) -> ServiceOntologie:
        return self.services.get(code) or ServiceOntologie(code, (), (), (), None, None)

    def service_du_statut(self, statut: str) -> str | None:
        return next((s.code for s in self.services.values() if s.service_du_statut_lot == statut), None)


def _reconnus(vocabulaire: dict[str, tuple[str, ...]], texte: str | None) -> list[str]:
    t = f" {normaliser(texte or '')} "
    return sorted(cle for cle, syns in vocabulaire.items() if any(s and f" {s} " in t for s in syns))


def _libelles(g: Graph, sujet) -> tuple[str, ...]:
    vus = dict.fromkeys(normaliser(str(o)) for o in g.objects(sujet, SKOS.altLabel) if isinstance(o, Literal))
    return tuple(v for v in vus if v)


def _entiers(g: Graph, sujet, predicat) -> tuple[int, ...]:
    return tuple(sorted(int(o) for o in g.objects(sujet, predicat)))


def _texte(g: Graph, sujet, predicat) -> str | None:
    valeur = g.value(sujet, predicat)
    return str(valeur) if valeur is not None else None


def lire(chemin: Path) -> Ontologie:
    g = Graph()
    g.parse(chemin, format="turtle")
    services = {}
    for s in g.subjects(RDF.type, AFI.ServiceAFI):
        code = _texte(g, s, AFI.code)
        if not code:
            raise ValueError(f"ontologie : service sans afi:code ({s})")
        if code in services:
            raise ValueError(f"ontologie : code de service en double ({code})")
        services[code] = ServiceOntologie(
            code=code, synonymes=_libelles(g, s), fiches=_entiers(g, s, AFI.ficheConnaissance),
            fiches_presentation=_entiers(g, s, AFI.fichePresentation),
            exige_statut_lot=_texte(g, s, AFI.exigeStatutLot),
            service_du_statut_lot=_texte(g, s, AFI.serviceDuStatutLot))
    secteurs = {}
    for s in g.subjects(RDF.type, AFI.Secteur):
        code = _texte(g, s, AFI.codeSecteur)
        if not code or code in secteurs:
            raise ValueError(f"ontologie : secteur sans code ou en double ({s})")
        secteurs[code] = _libelles(g, s)
    domaines = {}
    for s in g.subjects(RDF.type, AFI.DomaineDemarche):
        libelle = _texte(g, s, AFI.libelleSicad)
        if not libelle or libelle in domaines:
            raise ValueError(f"ontologie : domaine de démarche sans libellé SICAD ou en double ({s})")
        domaines[libelle] = _libelles(g, s)
    contact = g.value(RESSOURCE.afi, AFI.ficheContact)
    return Ontologie(services=services, fiche_contact=int(contact) if contact is not None else None,
                     fiches_ecartees=_entiers(g, RESSOURCE.afi, AFI.ficheEcartee),
                     lieu_depot=_libelles(g, RESSOURCE["lieu-depot"]), frais=_libelles(g, RESSOURCE.frais),
                     secteurs=secteurs, domaines_demarche=domaines,
                     incitation_demarche=_libelles(g, RESSOURCE["incitation-demarche"]))


@lru_cache
def _charger(chemin: str) -> Ontologie:
    return lire(Path(chemin))


def ontologie() -> Ontologie:
    """Ontologie chargée une fois par processus (chemin : ONTOLOGIE_PATH, sinon ontology/afi_ontology.ttl)."""
    return _charger(get_settings().ontologie_path or str(CHEMIN_PAR_DEFAUT))
