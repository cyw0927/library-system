from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.middleware.trustedhost import TrustedHostMiddleware
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


def create_app():
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name, debug=settings.debug, version="0.2.0", lifespan=lifespan,
        docs_url=None if settings.app_env == "production" else "/docs",
        redoc_url=None if settings.app_env == "production" else "/redoc",
        openapi_url=None if settings.app_env == "production" else "/openapi.json",
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.include_router(api_router)
    app.add_exception_handler(SQLAlchemyError, database_error)
    app.add_exception_handler(RequestValidationError, validation_error)

    @app.middleware("http")
    async def private_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
    return app


async def database_error(request, exc):
    # Never expose SQL statements, credentials, or a partial success on DB errors.
    logging.getLogger(__name__).error("Database operation failed: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "Database is unavailable"})


async def validation_error(request, exc):
    # FastAPI's default error includes submitted values (including passwords).
    errors = [{key: error[key] for key in ("loc", "msg", "type")} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


app = create_app()
