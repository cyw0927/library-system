from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.api.dependencies import Admin, DB, Private
from app.api.library import active_book
from app.core.config import get_settings
from app.db.models import Embedding
from app.services.openai_provider import ProviderError
from app.services.rag_service import ask, has_pgvector, index_paragraphs

router = APIRouter(tags=["Grounded RAG"])


class Question(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    mode: Literal["extractive", "openai"] = "extractive"
    book_id: int | None = None
    volume_id: int | None = None

    @field_validator("question")
    @classmethod
    def not_blank(cls, value):
        if len(value.strip()) < 2:
            raise ValueError("Question is too short")
        return value.strip()


class IndexRequest(BaseModel):
    provider: Literal["local", "openai"] = "local"
    book_id: int | None = None
    limit: int = Field(1000, ge=1, le=2000)
    confirm_cost: bool = False


@router.get("/rag/status")
def rag_status(db: DB, identity: Private):
    settings = get_settings()
    return dict(openai_configured=bool(settings.paid_ai_enabled and settings.openai_api_key and settings.openai_model),
                paid_ai_enabled=settings.paid_ai_enabled, pgvector=has_pgvector(db),
                embeddings=db.scalar(select(func.count(Embedding.id))),
                default_mode="extractive", maximum_sources=settings.rag_max_sources,
                local_embedding="lexical token hashing, not semantic AI")


@router.post("/rag/index", dependencies=[Admin])
def index(body: IndexRequest, db: DB):
    if body.provider == "openai" and not get_settings().paid_ai_enabled:
        raise HTTPException(403, "Paid AI is disabled")
    if body.book_id:
        active_book(db, body.book_id)
    if body.provider == "openai" and not body.confirm_cost:
        raise HTTPException(403, "OpenAI indexing incurs API charges; confirm_cost=true is required")
    try:
        return index_paragraphs(db, body.provider, body.book_id, body.limit)
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None


@router.post("/ask")
def ask_question(body: Question, db: DB, identity: Private):
    if body.mode == "openai" and not get_settings().paid_ai_enabled:
        raise HTTPException(403, "Paid AI is disabled")
    if body.mode == "openai" and identity.role != "admin":
        raise HTTPException(403, "Administrator permission required for paid AI calls")
    if body.book_id:
        active_book(db, body.book_id)
    try:
        return ask(db, **body.model_dump())
    except ProviderError as exc:
        raise HTTPException(503, str(exc)) from None
