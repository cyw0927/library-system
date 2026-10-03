from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from app.api.dependencies import DB
from app.services.search_service import search

router = APIRouter(tags=["Search"])


@router.get("/search")
def search_api(db: DB, q: str = Query(..., min_length=1, max_length=200),
               book_id: int | None = None, volume_id: int | None = None, chapter_id: int | None = None,
               pov: str | None = None, mode: Literal["substring", "fts"] = "substring",
               limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    if not q.strip():
        raise HTTPException(422, "Query cannot be blank")
    if mode == "fts" and db.get_bind().dialect.name != "postgresql":
        raise HTTPException(422, "FTS requires PostgreSQL")
    return search(db, q.strip(), limit, offset, book_id=book_id, volume_id=volume_id,
                  chapter_id=chapter_id, pov=pov, mode=mode)
