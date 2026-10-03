from fastapi import APIRouter

from app.api import health, library, sync, search, qa, reading, analysis

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(library.router)
api_router.include_router(sync.router)
api_router.include_router(search.router)
api_router.include_router(qa.router)
api_router.include_router(reading.router)
api_router.include_router(analysis.router)

