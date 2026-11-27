"""Interface web du banc de test LLM (outil de développement, désactivé par défaut).

Activée seulement si BANC_LLM_ACTIF=true dans .env. Ne pas activer en production :
les conversations sont gardées en mémoire, sans authentification.
"""
import time
from collections import OrderedDict
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from app.banc.gemini import Banc, creer_banc
from app.banc.sources import sources_du_tour
from app.config import get_settings

router = APIRouter(prefix="/banc", tags=["banc de test"], include_in_schema=False)
_PAGE = Path(__file__).resolve().parents[1] / "banc" / "page.html"
_MAX_SESSIONS = 20
_sessions: "OrderedDict[str, Banc]" = OrderedDict()
_verrou = Lock()


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(min_length=1, max_length=500)       # F01 : 500 caractères au plus


class Reset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


def _banc(session: str) -> Banc:
    s = get_settings()
    cle = s.gemini_api_key.get_secret_value()
    if not cle:
        raise HTTPException(status_code=503, detail={"code": "cle_gemini_absente"})
    with _verrou:
        if session in _sessions:
            _sessions.move_to_end(session)
            return _sessions[session]
        b = creer_banc(s, journal=lambda _ligne: None)
        b.verrou = Lock()          # une question à la fois par conversation
        _sessions[session] = b
        while len(_sessions) > _MAX_SESSIONS:
            _sessions.popitem(last=False)
        return b


@router.get("", response_class=HTMLResponse)
def page() -> HTMLResponse:
    return HTMLResponse(_PAGE.read_text(encoding="utf-8"))


@router.get("/info")
def info() -> dict:
    s = get_settings()
    return {"modele": s.gemini_model, "cle_presente": bool(s.gemini_api_key.get_secret_value()),
            "repli": [m.strip() for m in s.gemini_fallback_models.split(",") if m.strip()],
            "delai_s": s.llm_timeout_seconds}


@router.post("/message")
def message(m: Message) -> dict:
    b = _banc(m.session)
    with b.verrou:
        entree_avant, sortie_avant = b.jetons["entree"], b.jetons["sortie"]
        debut = time.perf_counter()
        reponse = b.poser(m.message)
        duree = time.perf_counter() - debut
        appels = list(b.dernier_tour)
        controle = b.controler(b.question_masquee, reponse)
        masquees = list(b.donnees_masquees)
    return {
        "reponse": reponse,
        "appels": appels,
        "sources": sources_du_tour(appels),    # affichées par la page, jamais lues à voix haute
        "controle": controle,
        "donnees_masquees": masquees,       # types de données personnelles retirées avant l'envoi au LLM
        "duree_s": round(duree, 1),
        "jetons": {"entree": b.jetons["entree"] - entree_avant, "sortie": b.jetons["sortie"] - sortie_avant},
        "modele": b.modele_utilise or b.modele,
        "repli": bool(b.modele_utilise and b.modele_utilise != b.modele),
    }


@router.post("/reset")
def reset(r: Reset) -> dict:
    with _verrou:
        _sessions.pop(r.session, None)
    return {"ok": True}
