from fastapi import APIRouter

from app.api import health, library, sync, search, qa, reading, analysis, rag, auth
from app.api.dependencies import Reader

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
for router in (library.router, sync.router, search.router, qa.router, reading.router, analysis.router, rag.router):
    api_router.include_router(router, dependencies=[Reader])

