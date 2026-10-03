from urllib.parse import quote

from sqlalchemy import func, literal_column, or_, select

from app.core.config import get_settings
from app.db.models import Book, Chapter, Paragraph, Volume


def search_query(q, book_id=None, volume_id=None, chapter_id=None, pov=None, mode="substring", dialect="postgresql"):
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    metadata = or_(*(column.ilike(pattern, escape="\\") for column in
                     (Book.title, Book.original_title, Volume.title, Volume.original_title, Chapter.title, Chapter.pov)))
    query = (select(Paragraph, Chapter, Book, Volume).join(Chapter, Paragraph.chapter_id == Chapter.id)
             .join(Book, Chapter.book_id == Book.id).outerjoin(Volume, Chapter.volume_id == Volume.id)
             .where(Chapter.is_active, Book.is_active, or_(Chapter.volume_id.is_(None), Volume.is_active)))
    if mode == "fts":
        vector = func.to_tsvector(literal_column("'simple'::regconfig"), Paragraph.plain_text)
        terms = func.plainto_tsquery(literal_column("'simple'::regconfig"), q)
        query = query.where(or_(metadata, vector.op("@@")(terms)))
        query = query.order_by(func.ts_rank_cd(vector, terms).desc())
    else:
        query = query.where(or_(metadata, Paragraph.plain_text.ilike(pattern, escape="\\")))
    for column, value in [(Chapter.book_id, book_id), (Chapter.volume_id, volume_id),
                          (Chapter.id, chapter_id), (Chapter.pov, pov)]:
        if value is not None:
            query = query.where(column == value)
    return query.order_by(Book.id, Chapter.sort_order, Chapter.id, Paragraph.paragraph_number)


def source_result(paragraph, chapter, book, volume, q=""):
    index = paragraph.plain_text.casefold().find(q.casefold()) if q else 0
    start = max(0, index - 80)
    excerpt = paragraph.plain_text[start:start + 350]
    if start:
        excerpt = "…" + excerpt
    if start + 350 < len(paragraph.plain_text):
        excerpt += "…"
    settings = get_settings()
    return dict(paragraph_id=paragraph.id, paragraph_number=paragraph.paragraph_number,
                chapter_id=chapter.id, chapter_title=chapter.title, chapter_code=chapter.chapter_code,
                book_id=book.id, book_title=book.title, volume_id=chapter.volume_id,
                volume_title=volume.title if volume else None, pov=chapter.pov, excerpt=excerpt,
                source_path=chapter.github_path, source_sha=chapter.github_sha,
                source_url=f"https://github.com/{settings.github_repository}/blob/{chapter.source_commit or settings.github_branch}/{quote(chapter.github_path, safe='/')}",
                reader_url=f"/?page=Reader&chapter={chapter.id}&paragraph={paragraph.paragraph_number}")


def search(session, q, limit=20, offset=0, **filters):
    query = search_query(q, dialect=session.get_bind().dialect.name, **filters)
    total = session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    results = [source_result(*row, q=q) for row in session.execute(query.offset(offset).limit(limit))]
    return dict(query=q, total=total, offset=offset, limit=limit, results=results)
