from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_database

settings = get_settings()
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        dispose_database()


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(api_router)


@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    # Never expose SQL statements, credentials, or a partial success on DB errors.
    return JSONResponse(status_code=503, content={"detail": "Database is unavailable"})
