"""Endpoints REST des outils du rôle 3 (consommés par l'agent du rôle 1 et, pour la démo, par le front).

Pas de `from __future__ import annotations` ici : FastAPI doit lire le type réel du corps de chaque route.
"""
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.processing.registre import OUTILS, catalogue

log = logging.getLogger(__name__)
router = APIRouter(prefix="/outils", tags=["outils"])


@router.get("")
def lister_outils() -> list[dict[str, Any]]:
    return catalogue()


def _route(nom: str):
    outil = OUTILS[nom]

    def endpoint(arguments: outil.entree):  # type: ignore[valid-type]
        try:
            return JSONResponse(outil.fonction(arguments).model_dump(mode="json"))
        except SQLAlchemyError:
            # Jamais de message d'erreur brut vers l'extérieur (BNF4) ; le détail reste dans les logs.
            log.exception("outil %s : erreur base de données", nom)
            raise HTTPException(status_code=503, detail={"code": "donnees_indisponibles", "outil": nom})
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors(
                include_url=False, include_input=False, include_context=False))

    endpoint.__name__ = nom
    router.add_api_route(f"/{nom}", endpoint, methods=["POST"], summary=outil.description,
                         response_model=None, name=nom)


for _nom in OUTILS:
    _route(_nom)
