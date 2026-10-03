from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, String,
    Text, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import ActiveMixin, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.book import Book
    from app.db.models.paragraph import Paragraph
    from app.db.models.volume import Volume


class Chapter(ActiveMixin, TimestampMixin, Base):
    __tablename__ = "chapters"
    __table_args__ = (
        ForeignKeyConstraint(
            ["volume_id", "book_id"], ["volumes.id", "volumes.book_id"],
            name="fk_chapters_volume_book", ondelete="RESTRICT",
        ),
        CheckConstraint("chapter_number >= 0", name="nonnegative_chapter_number"),
        CheckConstraint("paragraph_count >= 0", name="nonnegative_paragraph_count"),
        CheckConstraint("sort_order >= 0", name="nonnegative_sort_order"),
        Index("ix_chapters_book_order", "book_id", "is_active", "sort_order", "id"),
        Index("ix_chapters_volume_order", "volume_id", "is_active", "sort_order", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="RESTRICT"))
    volume_id: Mapped[int | None] = mapped_column(Integer)
    chapter_number: Mapped[int | None] = mapped_column(Integer)
    chapter_code: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500))
    original_title: Mapped[str | None] = mapped_column(String(500))
    pov: Mapped[str | None] = mapped_column(String(255))
    github_path: Mapped[str] = mapped_column(String(1024), unique=True)
    github_sha: Mapped[str] = mapped_column(String(64))
    source_commit: Mapped[str | None] = mapped_column(String(64))
    markdown_content: Mapped[str] = mapped_column(Text)
    paragraph_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    book: Mapped[Book] = relationship(back_populates="chapters", foreign_keys=[book_id])
    volume: Mapped[Volume | None] = relationship(
        back_populates="chapters",
        primaryjoin="and_(Chapter.volume_id == Volume.id, Chapter.book_id == Volume.book_id)",
        foreign_keys=[volume_id],
    )
    paragraphs: Mapped[list[Paragraph]] = relationship(
        back_populates="chapter", order_by="Paragraph.paragraph_number",
        cascade="all, delete-orphan", passive_deletes=True,
    )
