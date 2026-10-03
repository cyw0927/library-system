from datetime import datetime

from sqlalchemy import Boolean, DateTime, JSON, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    github_path: Mapped[str] = mapped_column(String(1024), unique=True)
    github_sha: Mapped[str] = mapped_column(String(64))
    source_commit: Mapped[str] = mapped_column(String(64))
    markdown_content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_commit: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="running")
    report: Mapped[dict | None] = mapped_column(JSON)
