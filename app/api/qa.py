from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import Admin, DB, columns
from app.api.library import active_book, active_chapter, chapter_query
from app.db.models import Chapter, QAIssue, Term, TermVariant
from app.services.qa_service import run_qa

router = APIRouter(tags=["QA and terminology"])


class Scope(BaseModel):
    chapter_id: int | None = None
    book_id: int | None = None


class Resolution(BaseModel):
    resolved: bool


class TermInput(BaseModel):
    book_id: int | None = None
    canonical: str = Field(min_length=1, max_length=255)
    category: Literal["person", "place", "organization", "title", "ship", "concept", "house", "event"] = "concept"
    description: str | None = Field(None, max_length=5000)
    variants: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("canonical")
    @classmethod
    def canonical_text(cls, value):
        if not value.strip():
            raise ValueError("Canonical term cannot be blank")
        return value.strip()

    @field_validator("variants")
    @classmethod
    def variant_text(cls, values):
        if any(not value.strip() or len(value.strip()) > 255 for value in values):
            raise ValueError("Variants must contain 1 to 255 characters")
        return list(dict.fromkeys(value.strip() for value in values))


@router.post("/qa/run", dependencies=[Admin])
def qa_run(body: Scope, db: DB):
    if body.chapter_id:
        active_chapter(db, body.chapter_id)
    if body.book_id:
        active_book(db, body.book_id)
    return run_qa(db, body.chapter_id, body.book_id)


@router.get("/qa/issues")
def issues(db: DB, book_id: int | None = None, chapter_id: int | None = None,
           severity: Literal["INFO", "WARNING", "ERROR"] | None = None,
           issue_type: str | None = None, resolved: bool | None = False,
           limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    query = (select(QAIssue, Chapter).join(Chapter).where(QAIssue.is_current, QAIssue.source_sha == Chapter.github_sha,
             Chapter.id.in_(chapter_query().with_only_columns(Chapter.id))))
    for column, value in [(Chapter.book_id, book_id), (QAIssue.chapter_id, chapter_id),
                          (QAIssue.severity, severity), (QAIssue.issue_type, issue_type), (QAIssue.resolved, resolved)]:
        if value is not None:
            query = query.where(column == value)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(QAIssue.id).offset(offset).limit(limit))
    return {"total": total, "results": [dict(**columns(issue), chapter_title=chapter.title, source_path=chapter.github_path) for issue, chapter in rows]}


@router.patch("/qa/issues/{issue_id}", dependencies=[Admin])
def resolve(issue_id: int, body: Resolution, db: DB):
    issue = db.get(QAIssue, issue_id)
    if not issue:
        raise HTTPException(404, "Issue not found")
    issue.resolved = body.resolved
    db.commit()
    return columns(issue)


def term_result(term):
    return dict(**columns(term), variants=[v.variant for v in term.variants])


@router.get("/terms")
def terms(db: DB, book_id: int | None = None):
    query = select(Term)
    if book_id is not None:
        query = query.where((Term.book_id == book_id) | Term.book_id.is_(None))
    return [term_result(t) for t in db.scalars(query.order_by(Term.canonical))]


def save_term(db, body, term=None):
    if body.book_id is not None:
        active_book(db, body.book_id)
    if term is None:
        term = Term()
        db.add(term)
    for key in ("book_id", "canonical", "category", "description"):
        setattr(term, key, getattr(body, key))
    desired = {value for value in body.variants if value != body.canonical}
    current = {v.variant: v for v in term.variants}
    for value in desired - current.keys():
        term.variants.append(TermVariant(variant=value))
    for value in current.keys() - desired:
        term.variants.remove(current[value])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This canonical term already exists in the same scope") from None
    return term_result(term)


@router.post("/terms", dependencies=[Admin], status_code=201)
def create_term(body: TermInput, db: DB):
    return save_term(db, body)


@router.put("/terms/{term_id}", dependencies=[Admin])
def update_term(term_id: int, body: TermInput, db: DB):
    term = db.get(Term, term_id)
    if not term:
        raise HTTPException(404, "Term not found")
    return save_term(db, body, term)


@router.delete("/terms/{term_id}", dependencies=[Admin], status_code=204)
def delete_term(term_id: int, db: DB):
    term = db.get(Term, term_id)
    if not term:
        raise HTTPException(404, "Term not found")
    db.delete(term)
    db.commit()
