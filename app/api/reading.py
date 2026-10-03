from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.dependencies import Admin, DB, columns
from app.api.library import active_chapter
from app.db.models import Bookmark, Chapter, Paragraph, ReadingProgress

router = APIRouter(tags=["Private reading records"], dependencies=[Admin])


class Position(BaseModel):
    chapter_id: int = Field(gt=0)
    paragraph_number: int = Field(1, ge=1)
    completed: bool = False


class BookmarkInput(BaseModel):
    chapter_id: int = Field(gt=0)
    paragraph_number: int | None = Field(None, ge=1)
    note: str | None = Field(None, max_length=20000)


class NoteInput(BaseModel):
    note: str | None = Field(None, max_length=20000)


def paragraph_at(db, chapter_id, number):
    paragraph = db.scalar(select(Paragraph).where(Paragraph.chapter_id == chapter_id, Paragraph.paragraph_number == number))
    if not paragraph:
        raise HTTPException(422, "Paragraph is outside this chapter")
    return paragraph


def record_result(record, chapter):
    return dict(**columns(record), book_id=chapter.book_id, chapter_title=chapter.title,
                source_changed=record.source_sha != chapter.github_sha,
                chapter_active=chapter.is_active,
                reader_url=f'/?page=Reader&chapter={chapter.id}&paragraph={record.paragraph_number or 1}')


@router.get("/reading/progress")
def progress(db: DB, book_id: int | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    query = select(ReadingProgress, Chapter).join(Chapter, ReadingProgress.chapter_id == Chapter.id).where(ReadingProgress.user_id == "local")
    if book_id is not None:
        query = query.where(ReadingProgress.book_id == book_id)
    rows = db.execute(query.order_by(ReadingProgress.updated_at.desc(), ReadingProgress.id.desc()).offset(offset).limit(limit))
    results = []
    for record, chapter in rows:
        item = columns(record)
        item.update(chapter_title=chapter.title, source_changed=record.source_sha != chapter.github_sha,
                    chapter_active=chapter.is_active,
                    reader_url=f'/?page=Reader&chapter={chapter.id}&paragraph={record.paragraph_number}')
        results.append(item)
    return results


@router.put("/reading/progress")
def save_progress(body: Position, db: DB):
    chapter = active_chapter(db, body.chapter_id)
    paragraph_at(db, chapter.id, body.paragraph_number)
    record = db.scalar(select(ReadingProgress).where(ReadingProgress.user_id == "local", ReadingProgress.chapter_id == chapter.id))
    if record is None:
        record = ReadingProgress(chapter_id=chapter.id, book_id=chapter.book_id)
        db.add(record)
    record.paragraph_number, record.completed, record.source_sha = body.paragraph_number, body.completed, chapter.github_sha
    db.commit()
    return columns(record)


@router.get("/bookmarks")
def bookmarks(db: DB, book_id: int | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    query = select(Bookmark, Chapter).join(Chapter).where(Bookmark.user_id == "local")
    if book_id is not None:
        query = query.where(Chapter.book_id == book_id)
    return [record_result(record, chapter) for record, chapter in db.execute(query.order_by(Bookmark.updated_at.desc(), Bookmark.id.desc()).offset(offset).limit(limit))]


@router.post("/bookmarks", status_code=201)
def create_bookmark(body: BookmarkInput, db: DB):
    chapter = active_chapter(db, body.chapter_id)
    paragraph = paragraph_at(db, chapter.id, body.paragraph_number) if body.paragraph_number else None
    record = Bookmark(chapter_id=chapter.id, paragraph_id=paragraph.id if paragraph else None,
                      paragraph_number=body.paragraph_number, note=body.note, source_sha=chapter.github_sha)
    db.add(record)
    db.commit()
    return columns(record)


@router.patch("/bookmarks/{bookmark_id}")
def update_bookmark(bookmark_id: int, body: NoteInput, db: DB):
    record = db.get(Bookmark, bookmark_id)
    if not record or record.user_id != "local":
        raise HTTPException(404, "Bookmark not found")
    record.note = body.note
    db.commit()
    return columns(record)


@router.delete("/bookmarks/{bookmark_id}", status_code=204)
def delete_bookmark(bookmark_id: int, db: DB):
    record = db.get(Bookmark, bookmark_id)
    if not record or record.user_id != "local":
        raise HTTPException(404, "Bookmark not found")
    db.delete(record)
    db.commit()
