from sqlalchemy import Boolean, CheckConstraint, ForeignKey, ForeignKeyConstraint, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin


class ReadingProgress(TimestampMixin, Base):
    __tablename__ = "reading_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "chapter_id", name="uq_reading_progress_user_chapter"),
        ForeignKeyConstraint(["chapter_id", "book_id"], ["chapters.id", "chapters.book_id"], ondelete="RESTRICT"),
        CheckConstraint("paragraph_number >= 1", name="positive_paragraph_number"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), default="local", server_default="local")
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="RESTRICT"), index=True)
    chapter_id: Mapped[int] = mapped_column(Integer, index=True)
    paragraph_number: Mapped[int] = mapped_column(Integer)
    source_sha: Mapped[str] = mapped_column(String(64))
    completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class Bookmark(TimestampMixin, Base):
    __tablename__ = "bookmarks"
    __table_args__ = (CheckConstraint("paragraph_number >= 1", name="positive_paragraph_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(100), default="local", server_default="local")
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="RESTRICT"), index=True)
    paragraph_id: Mapped[int | None] = mapped_column(ForeignKey("paragraphs.id", ondelete="SET NULL"))
    paragraph_number: Mapped[int | None] = mapped_column(Integer)
    source_sha: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(Text)
