from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, func, literal_column, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import to_tsvector

from app.db.base import Base
from app.db.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.db.models.chapter import Chapter


class Paragraph(TimestampMixin, Base):
    __tablename__ = "paragraphs"
    __table_args__ = (
        UniqueConstraint("chapter_id", "paragraph_number", name="uq_paragraphs_chapter_number"),
        CheckConstraint("paragraph_number >= 1", name="positive_paragraph_number"),
        CheckConstraint("char_count >= 0", name="nonnegative_char_count"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"))
    paragraph_number: Mapped[int] = mapped_column(Integer)
    markdown_content: Mapped[str] = mapped_column(Text)
    plain_text: Mapped[str] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    chapter: Mapped[Chapter] = relationship(back_populates="paragraphs")


Paragraph.__table__.append_constraint(
    Index("ix_paragraphs_search_fts", to_tsvector(literal_column("'simple'::regconfig"), Paragraph.__table__.c.plain_text),
          postgresql_using="gin").ddl_if(dialect="postgresql")
)
