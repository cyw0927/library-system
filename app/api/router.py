from fastapi import APIRouter

from app.api import health, library, sync

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(library.router)
api_router.include_router(sync.router)

