"""Application FastAPI de Dalila (backend).

Lancement : .venv\\Scripts\\python.exe -m uvicorn app.main:app --app-dir backend --port 8000
Si le front est construit (frontend/dist, `npm run build`), il est servi sur /formulaire/... (même origine).
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.demandes import router as demandes_router
from app.api.outils import router as outils_router
from app.api.voix import router as voix_router
from app.config import get_settings

app = FastAPI(title="Dalila (AFI) — backend", version="0.1.0")
app.include_router(outils_router)
app.include_router(demandes_router)
app.include_router(voix_router)

# Banc de test LLM : outil de développement, activé seulement par BANC_LLM_ACTIF=true
if get_settings().banc_llm_actif:
    from app.api.banc import router as banc_router

    app.include_router(banc_router)


@app.get("/sante")
def sante() -> dict[str, str]:
    return {"statut": "ok"}


# ---------- Front construit (pages formulaire) ----------
FRONT = Path(__file__).resolve().parents[2] / "frontend" / "dist"
# Pas de script ni de style externe ; pas de Referer vers d'autres sites (le lien porte les données du projet).
_ENTETES_PAGE = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; "
                               "form-action 'none'",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

if (FRONT / "index.html").is_file():
    app.mount("/assets", StaticFiles(directory=FRONT / "assets"), name="assets")

    @app.get("/formulaire/{parcours}", include_in_schema=False)
    def page_formulaire(parcours: str) -> FileResponse:
        return FileResponse(FRONT / "index.html", headers=_ENTETES_PAGE)
