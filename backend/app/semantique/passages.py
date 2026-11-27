"""Index vectoriel des passages (Qdrant) et recherche hybride dense + lexicale (cahier BF17).

- Encodeur : BGE-M3 (FlagEmbedding, licence MIT) donne en un passage un vecteur dense (1024) et
  des poids lexicaux (vecteur creux) ; les deux sont fusionnés par Qdrant (RRF).
- Point Qdrant = UUID du passage (assistant.document_chunks.id) ; payload = identifiants et filtres
  seulement. Le texte est relu dans PostgreSQL (version de référence).
- La recherche est TOUJOURS filtrée par document : jamais les règles d'une autre zone.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Protocol

from app.config import get_settings

DENSE, LEXICAL = "dense", "lexical"


@dataclass(frozen=True)
class VecteurHybride:
    dense: list[float]
    creux: dict[int, float]          # identifiant de jeton -> poids


class Encodeur(Protocol):
    nom: str
    dimension: int

    def passages(self, textes: list[str]) -> list[VecteurHybride]: ...

    def requete(self, texte: str) -> VecteurHybride: ...


class EncodeurBGEM3:
    """BGE-M3 chargé une seule fois (≈ 2,3 Go téléchargés au premier usage, fp16 sur GPU)."""

    dimension = 1024

    def __init__(self, nom: str, appareil: str = "") -> None:
        self.nom = nom
        self._appareil = appareil
        self._modele = None

    def _charger(self):
        if self._modele is None:
            import torch
            from FlagEmbedding import BGEM3FlagModel

            appareil = self._appareil or ("cuda:0" if torch.cuda.is_available() else "cpu")
            self._modele = BGEM3FlagModel(self.nom, use_fp16=appareil.startswith("cuda"), devices=[appareil])
        return self._modele

    @staticmethod
    def _convertir(sortie, i: int) -> VecteurHybride:
        poids = sortie["lexical_weights"][i]
        return VecteurHybride(dense=[float(x) for x in sortie["dense_vecs"][i]],
                              creux={int(k): float(v) for k, v in poids.items() if float(v) > 0})

    def passages(self, textes: list[str]) -> list[VecteurHybride]:
        sortie = self._charger().encode_corpus(textes, batch_size=16, max_length=1024,
                                               return_dense=True, return_sparse=True, return_colbert_vecs=False)
        return [self._convertir(sortie, i) for i in range(len(textes))]

    def requete(self, texte: str) -> VecteurHybride:
        sortie = self._charger().encode_queries([texte], max_length=512,
                                                return_dense=True, return_sparse=True, return_colbert_vecs=False)
        return self._convertir(sortie, 0)


@lru_cache
def encodeur() -> Encodeur:
    s = get_settings()
    return EncodeurBGEM3(s.embedding_model, s.embedding_device)


@lru_cache
def client_qdrant():
    from qdrant_client import QdrantClient

    s = get_settings()
    return QdrantClient(url=s.qdrant_url, timeout=int(s.qdrant_timeout_seconds))


def texte_a_encoder(p: dict) -> str:
    """Contexte du passage (document > chapitres) devant son texte, comme dans le paquet GraphRAG."""
    chemin = " > ".join([p["titre"], *(p.get("section") or [])])
    return f"{chemin}\n\n{p['texte']}"


def _payload(p: dict) -> dict:
    return {"passage_id": p["passage_id"], "document_id": p["document_id"], "version_id": p["version_id"],
            "zone_id": p["zone_id"], "type_document": p["type_document"], "partie": p["partie"],
            "categorie_sol": p["categorie_sol"], "article": p["article"], "a_verifier": p["a_verifier"],
            "organisation": p.get("organisation")}


def creer_collection(client, collection: str, enc: Encodeur) -> None:
    """(Re)crée la collection : vecteurs nommés dense + lexical, index des champs filtrés."""
    from qdrant_client import models

    if client.collection_exists(collection):
        client.delete_collection(collection)
    client.create_collection(
        collection,
        vectors_config={DENSE: models.VectorParams(size=enc.dimension, distance=models.Distance.COSINE)},
        sparse_vectors_config={LEXICAL: models.SparseVectorParams()},
        metadata={"modele": enc.nom})
    for champ, schema in (("document_id", models.PayloadSchemaType.INTEGER),
                          ("partie", models.PayloadSchemaType.KEYWORD),
                          ("categorie_sol", models.PayloadSchemaType.KEYWORD),
                          ("type_document", models.PayloadSchemaType.KEYWORD),
                          ("organisation", models.PayloadSchemaType.KEYWORD)):
        client.create_payload_index(collection, champ, field_schema=schema)


def indexer(client, enc: Encodeur, passages: list[dict], collection: str, taille_lot: int = 64,
            progression=None) -> int:
    """Reconstruit l'index : collection recréée, puis tous les passages (les UUID sont stables)."""
    from qdrant_client import models

    creer_collection(client, collection, enc)
    n = 0
    for debut in range(0, len(passages), taille_lot):
        lot = passages[debut:debut + taille_lot]
        vecteurs = enc.passages([texte_a_encoder(p) for p in lot])
        client.upsert(collection, points=[
            models.PointStruct(id=p["passage_id"], payload=_payload(p), vector={
                DENSE: v.dense,
                LEXICAL: models.SparseVector(indices=list(v.creux), values=list(v.creux.values()))})
            for p, v in zip(lot, vecteurs)])
        n += len(lot)
        if progression:
            progression(n, len(passages))
    return n


def modele_de_l_index(client, collection: str) -> str | None:
    """Modèle utilisé pour construire l'index (None si la collection n'existe pas)."""
    if not client.collection_exists(collection):
        return None
    meta = client.get_collection(collection).config.metadata or {}
    return meta.get("modele")


@dataclass(frozen=True)
class Trouve:
    passage_id: str
    score: float


def rechercher(client, enc: Encodeur, question: str, *, collection: str, document_ids: Iterable[int] | None = None,
               organisations: Iterable[str] | None = None, types_document: Iterable[str] | None = None,
               parties: Iterable[str] = ("reglement",), categorie: str | None = None,
               limite: int = 5) -> list[Trouve]:
    """Passages les plus proches de la question (fusion RRF dense + lexical), TOUJOURS filtrés :
    par documents (cahiers d'une zone) ou par organismes et types de document (pages des organismes).

    Avec `categorie` : passages de cette catégorie OU sans catégorie (règles communes à la zone).
    """
    from qdrant_client import models

    conditions = [models.FieldCondition(key="partie", match=models.MatchAny(any=list(parties)))]
    if document_ids is not None:
        docs = sorted({int(d) for d in document_ids})
        if not docs:
            return []
        conditions.append(models.FieldCondition(key="document_id", match=models.MatchAny(any=docs)))
    if organisations is not None:
        orgs = sorted(set(organisations))
        if not orgs:
            return []
        conditions.append(models.FieldCondition(key="organisation", match=models.MatchAny(any=orgs)))
    if types_document is not None:
        conditions.append(models.FieldCondition(key="type_document", match=models.MatchAny(any=list(types_document))))
    if len(conditions) == 1:
        raise ValueError("recherche sans filtre de document ou d'organisme refusée")
    if categorie:
        conditions.append(models.Filter(should=[
            models.FieldCondition(key="categorie_sol", match=models.MatchValue(value=categorie)),
            models.IsNullCondition(is_null=models.PayloadField(key="categorie_sol"))]))
    filtre = models.Filter(must=conditions)
    q = enc.requete(question)
    reponse = client.query_points(
        collection,
        prefetch=[models.Prefetch(query=q.dense, using=DENSE, limit=max(20, limite * 4), filter=filtre),
                  models.Prefetch(query=models.SparseVector(indices=list(q.creux), values=list(q.creux.values())),
                                  using=LEXICAL, limit=max(20, limite * 4), filter=filtre)],
        query=models.FusionQuery(fusion=models.Fusion.RRF), limit=limite, with_payload=False)
    return [Trouve(str(p.id), float(p.score)) for p in reponse.points]
