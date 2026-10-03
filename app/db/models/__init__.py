"""Import the complete core model registry for Alembic and application services."""

from app.db.models.book import Book
from app.db.models.volume import Volume
from app.db.models.chapter import Chapter
from app.db.models.paragraph import Paragraph
from app.db.models.sync_state import SyncState
from app.db.models.source import SourceDocument, SyncRun
from app.db.models.qa import Term, TermVariant, QAIssue
from app.db.models.reading import ReadingProgress, Bookmark

__all__ = ["Book", "Volume", "Chapter", "Paragraph", "SyncState", "SourceDocument", "SyncRun", "Term", "TermVariant", "QAIssue", "ReadingProgress", "Bookmark"]
