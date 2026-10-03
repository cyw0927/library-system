from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, or_, select

from app.api.dependencies import DB, columns
from app.core.config import get_settings
from app.db.models import Book, Chapter, Paragraph, SourceDocument, Volume
from app.services.parser_service import without_navigation

router = APIRouter(tags=["Library"])


def chapter_query():
    return (select(Chapter).join(Book).outerjoin(Volume, Chapter.volume_id == Volume.id)
            .where(Chapter.is_active, Book.is_active, or_(Chapter.volume_id.is_(None), Volume.is_active)))


def active_book(db, book_id):
    entity = db.get(Book, book_id)
    if not entity or not entity.is_active:
        raise HTTPException(404, "Book not found")
    return entity


def active_chapter(db, chapter_id):
    entity = db.scalar(chapter_query().where(Chapter.id == chapter_id))
    if not entity:
        raise HTTPException(404, "Chapter not found")
    return entity


def chapter_summary(chapter):
    return columns(chapter, exclude=("markdown_content",))


def book_summary(db, book):
    result = columns(book)
    result["chapter_count"] = db.scalar(select(func.count()).select_from(chapter_query().where(Chapter.book_id == book.id).subquery()))
    result["volume_count"] = db.scalar(select(func.count(Volume.id)).where(Volume.book_id == book.id, Volume.is_active))
    doc = db.scalar(select(SourceDocument).where(SourceDocument.github_path == f"{book.github_path}/README.md", SourceDocument.is_active))
    expected = doc.metadata_json.get("expected_chapters") if doc else None
    result["expected_chapters"] = expected
    # README can count only main chapters, while actual files include appendices.
    result["translation_progress"] = result["chapter_count"] / expected if expected and result["chapter_count"] <= expected else None
    return result


@router.get("/books")
def books(db: DB):
    return [book_summary(db, b) for b in db.scalars(select(Book).where(Book.is_active).order_by(Book.title, Book.id))]


@router.get("/books/{book_id}")
def book_detail(book_id: int, db: DB):
    return book_summary(db, active_book(db, book_id))


@router.get("/volumes")
def volumes(db: DB, book_id: int | None = None):
    query = select(Volume).join(Book).where(Volume.is_active, Book.is_active)
    if book_id is not None:
        active_book(db, book_id)
        query = query.where(Volume.book_id == book_id)
    return [columns(v) for v in db.scalars(query.order_by(Volume.book_id, Volume.sort_order, Volume.id))]


@router.get("/books/{book_id}/volumes")
def book_volumes(book_id: int, db: DB):
    return volumes(db, book_id)


@router.get("/chapters")
def chapters(db: DB, book_id: int | None = None, volume_id: int | None = None,
             offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=1000)):
    query = chapter_query()
    if book_id is not None:
        active_book(db, book_id)
        query = query.where(Chapter.book_id == book_id)
    if volume_id is not None:
        volume = db.get(Volume, volume_id)
        if not volume or not volume.is_active or not volume.book.is_active:
            raise HTTPException(404, "Volume not found")
        query = query.where(Chapter.volume_id == volume_id)
    return [chapter_summary(c) for c in db.scalars(query.order_by(Chapter.book_id, Chapter.sort_order, Chapter.id).offset(offset).limit(limit))]


@router.get("/books/{book_id}/chapters")
def book_chapters(book_id: int, db: DB, volume_id: int | None = None, offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=1000)):
    return chapters(db, book_id, volume_id, offset, limit)


@router.get("/volumes/{volume_id}/chapters")
def volume_chapters(volume_id: int, db: DB, offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=1000)):
    return chapters(db, None, volume_id, offset, limit)


@router.get("/chapters/{chapter_id}")
def chapter_detail(chapter_id: int, db: DB):
    chapter = active_chapter(db, chapter_id)
    ordered = list(db.scalars(chapter_query().where(Chapter.book_id == chapter.book_id).order_by(Chapter.sort_order, Chapter.id)))
    index = next(i for i, c in enumerate(ordered) if c.id == chapter.id)
    result = chapter_summary(chapter)
    result.update(book=columns(chapter.book), volume=columns(chapter.volume) if chapter.volume else None,
                  markdown_content=without_navigation(chapter.markdown_content),
                  previous=chapter_summary(ordered[index - 1]) if index > 0 else None,
                  next=chapter_summary(ordered[index + 1]) if index + 1 < len(ordered) else None,
                  paragraphs=[columns(p) for p in chapter.paragraphs])
    settings = get_settings()
    result["source_url"] = f"https://github.com/{settings.github_repository}/blob/{chapter.source_commit or settings.github_branch}/{quote(chapter.github_path, safe='/')}"
    return result
