"""Voix de Dalila (BF7, BF8, BF9) : relais vers le service « langues et voix » (app.langue.client).

- POST /voix/transcrire : corps = audio brut (webm, ogg, wav…) ; renvoie le texte reconnu, à afficher
  AVANT de l'envoyer comme question (BF7). L'audio n'est jamais enregistré (BNF8).
- POST /voix/lire : texte d'une réponse -> audio WAV en base64 dans la langue du texte (BF8) ;
  un dialecte sans voix dédiée est lu en arabe et le signale.
- GET /voix/etat : modèles réellement prêts.
Service absent ou en panne : 503 avec un code court, jamais de trace (BNF4) ; l'écrit continue.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.langue import client

router = APIRouter(prefix="/voix", tags=["voix"])
LANGUES = ("auto", "aeb", "ar", "arq", "ayl", "fr", "en", "de", "tr")


class Lecture(BaseModel):
    model_config = ConfigDict(extra="forbid")
    texte: str = Field(min_length=1, max_length=4000)
    langue: str = Field(default="auto", pattern="^(" + "|".join(LANGUES) + ")$")


def _indisponible(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail={"code": "voix_indisponible", "raison": str(exc)[:80]})


@router.get("/etat")
def etat() -> dict:
    return client.etat()


@router.post("/transcrire")
async def transcrire(request: Request, langue: str = "auto") -> dict:
    if langue not in LANGUES:
        raise HTTPException(status_code=422, detail={"code": "langue_inconnue"})
    longueur = int(request.headers.get("content-length") or 0)
    if longueur > client.TAILLE_AUDIO_MAX:
        raise HTTPException(status_code=413, detail={"code": "audio_trop_long"})
    audio = await request.body()
    try:
        return client.transcrire(audio, request.headers.get("content-type", ""), langue)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "audio_invalide", "raison": str(exc)})
    except client.ServiceLangueIndisponible as exc:
        raise _indisponible(exc)


@router.post("/lire")
def lire(l: Lecture) -> dict:
    try:
        return client.lire(l.texte, None if l.langue == "auto" else l.langue)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "texte_vide", "raison": str(exc)})
    except client.ServiceLangueIndisponible as exc:
        raise _indisponible(exc)
