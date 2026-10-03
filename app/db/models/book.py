from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import ActiveMixin, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.chapter import Chapter
    from app.db.models.volume import Volume


class Book(ActiveMixin, TimestampMixin, Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    original_title: Mapped[str | None] = mapped_column(String(500))
    author: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    github_path: Mapped[str] = mapped_column(String(1024), unique=True)
    book_type: Mapped[str] = mapped_column(
        String(50), default="book", server_default=text("'book'"),
    )
    status: Mapped[str] = mapped_column(
        String(50), default="unknown", server_default=text("'unknown'"),
    )

    volumes: Mapped[list[Volume]] = relationship(
        back_populates="book", order_by="Volume.sort_order, Volume.id",
        passive_deletes="all",
    )
    chapters: Mapped[list[Chapter]] = relationship(
        back_populates="book", order_by="Chapter.sort_order, Chapter.id",
        passive_deletes="all",
    )

