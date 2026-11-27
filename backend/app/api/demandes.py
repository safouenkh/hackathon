"""Pages formulaire (front React) : lecture du formulaire prérempli et envoi d'une demande.

- GET  /api/formulaires/{parcours} : structure officielle + valeurs préremplies (projet seulement).
- POST /api/demandes               : enregistre la demande relue et le contact consenti, pour l'AFI.
  Ce n'est pas le dépôt officiel ; rien n'est envoyé à un service externe.

Pas de `from __future__ import annotations` : FastAPI lit les types réels des paramètres.
"""
import logging
from typing import Annotated

import psycopg
from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.db import EcritureIndisponible
from app.processing.formulaire import DemandeRefusee, FormulaireIntrouvable, envoyer_demande, page_formulaire
from app.processing.schemas import EnvoiDemande, Projet

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["formulaires"])

_CODE = r"^[a-z][a-z0-9_-]*$"
_LANGUE = r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$"


@router.get("/formulaires/{parcours}", response_model=None)
def lire_formulaire(
    parcours: Annotated[str, Path(max_length=100, pattern=_CODE)],
    langue: Annotated[str | None, Query(max_length=10, pattern=_LANGUE)] = None,
    aide: Annotated[str | None, Query(max_length=10, pattern=_LANGUE)] = None,
    lots: Annotated[list[int], Query(max_length=10)] = [],  # noqa: B006 (FastAPI copie la valeur)
    activite: Annotated[str | None, Query(max_length=200)] = None,
    nombre_emplois: Annotated[int | None, Query(ge=0)] = None,
    investissement_dt: Annotated[int | None, Query(ge=0)] = None,
    surface_souhaitee_m2: Annotated[int | None, Query(ge=0)] = None,
    gouvernorat: Annotated[str | None, Query(max_length=50)] = None,
) -> JSONResponse:
    projet = Projet(activite=activite, nombre_emplois=nombre_emplois, investissement_dt=investissement_dt,
                    surface_souhaitee_m2=surface_souhaitee_m2, gouvernorat=gouvernorat)
    try:
        page = page_formulaire(parcours, langue, aide, lots, projet)
    except FormulaireIntrouvable as exc:
        raise HTTPException(status_code=404, detail={"code": exc.code})
    except SQLAlchemyError:
        log.exception("formulaire %s : erreur base de données", parcours)
        raise HTTPException(status_code=503, detail={"code": "donnees_indisponibles"})
    return JSONResponse(page.model_dump(mode="json"))


@router.post("/demandes", status_code=201, response_model=None)
def envoyer(demande: EnvoiDemande) -> JSONResponse:
    try:
        envoyee = envoyer_demande(demande)
    except DemandeRefusee as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "champ": exc.champ})
    except EcritureIndisponible:
        raise HTTPException(status_code=503, detail={"code": "envoi_indisponible"})
    except DBAPIError as exc:
        if isinstance(exc.orig, psycopg.errors.RaiseException):     # refus du déclencheur de contrôle
            log.warning("demande refusée par la base : %s", type(exc.orig).__name__)
            raise HTTPException(status_code=422, detail={"code": "champ_refuse", "champ": None})
        log.exception("envoi d'une demande : erreur base de données")
        raise HTTPException(status_code=503, detail={"code": "donnees_indisponibles"})
    except SQLAlchemyError:
        log.exception("envoi d'une demande : erreur base de données")
        raise HTTPException(status_code=503, detail={"code": "donnees_indisponibles"})
    return JSONResponse(envoyee.model_dump(mode="json"), status_code=201)
