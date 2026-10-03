from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import ActiveMixin, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.book import Book
    from app.db.models.chapter import Chapter


class Volume(ActiveMixin, TimestampMixin, Base):
    __tablename__ = "volumes"
    __table_args__ = (
        UniqueConstraint("book_id", "slug", name="uq_volumes_book_slug"),
        UniqueConstraint("id", "book_id", name="uq_volumes_id_book"),
        CheckConstraint("volume_number >= 1", name="positive_volume_number"),
        CheckConstraint("sort_order >= 0", name="nonnegative_sort_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id", ondelete="RESTRICT"), index=True,
    )
    volume_number: Mapped[int | None] = mapped_column(Integer)
    slug: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500))
    original_title: Mapped[str | None] = mapped_column(String(500))
    github_path: Mapped[str] = mapped_column(String(1024), unique=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    book: Mapped[Book] = relationship(back_populates="volumes")
    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="volume",
        primaryjoin="and_(Volume.id == Chapter.volume_id, Volume.book_id == Chapter.book_id)",
        foreign_keys="[Chapter.volume_id]",
        order_by="Chapter.sort_order, Chapter.id",
        passive_deletes="all",
    )

