from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models.mixins import TimestampMixin


class Term(TimestampMixin, Base):
    __tablename__ = "terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int | None] = mapped_column(ForeignKey("books.id", ondelete="RESTRICT"), index=True)
    canonical: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(50), default="concept")
    description: Mapped[str | None] = mapped_column(Text)
    variants: Mapped[list["TermVariant"]] = relationship(cascade="all, delete-orphan", order_by="TermVariant.id")


Term.__table__.append_constraint(Index("uq_terms_scope_canonical", func.coalesce(Term.__table__.c.book_id, 0), Term.__table__.c.canonical, unique=True))


class TermVariant(Base):
    __tablename__ = "term_variants"
    __table_args__ = (UniqueConstraint("term_id", "variant", name="uq_term_variants_term_variant"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id", ondelete="CASCADE"))
    variant: Mapped[str] = mapped_column(String(255))


class QAIssue(Base):
    __tablename__ = "qa_issues"
    __table_args__ = (
        UniqueConstraint("chapter_id", "fingerprint", name="uq_qa_issues_chapter_fingerprint"),
        CheckConstraint("severity IN ('INFO', 'WARNING', 'ERROR')", name="valid_severity"),
        CheckConstraint("paragraph_number >= 1", name="positive_paragraph_number"),
        CheckConstraint("line_number >= 1", name="positive_line_number"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    source_sha: Mapped[str] = mapped_column(String(64))
    issue_type: Mapped[str] = mapped_column(String(50), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    message: Mapped[str] = mapped_column(Text)
    line_number: Mapped[int | None] = mapped_column(Integer)
    paragraph_number: Mapped[int | None] = mapped_column(Integer)
    detected_value: Mapped[str | None] = mapped_column(Text)
    expected_value: Mapped[str | None] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
