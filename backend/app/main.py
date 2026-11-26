"""Application FastAPI de Dalila (backend).

Lancement : .venv\\Scripts\\python.exe -m uvicorn app.main:app --app-dir backend --port 8000
"""
from fastapi import FastAPI

from app.api.outils import router as outils_router
from app.config import get_settings

app = FastAPI(title="Dalila (AFI) — backend", version="0.1.0")
app.include_router(outils_router)

# Banc de test LLM : outil de développement, activé seulement par BANC_LLM_ACTIF=true
if get_settings().banc_llm_actif:
    from app.api.banc import router as banc_router

    app.include_router(banc_router)


@app.get("/sante")
def sante() -> dict[str, str]:
    return {"statut": "ok"}
