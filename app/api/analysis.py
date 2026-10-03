from fastapi import APIRouter

from app.api.dependencies import DB
from app.api.library import active_book
from app.services.analysis_service import analyze_book, overview

router = APIRouter(tags=["Analysis"])


@router.get("/analysis/overview")
def statistics(db: DB):
    return overview(db)


@router.get("/analysis/books/{book_id}")
def book_analysis(book_id: int, db: DB):
    return analyze_book(db, active_book(db, book_id))
