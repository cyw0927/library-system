from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SyncState(Base):
    __tablename__ = "sync_state"
    __table_args__ = (
        CheckConstraint(
            "sync_status IN ('pending', 'synced', 'error', 'deactivated')",
            name="valid_sync_status",
        ),
        CheckConstraint("entity_id > 0", name="positive_entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    github_path: Mapped[str] = mapped_column(String(1024), unique=True)
    github_sha: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(50))
    # Polymorphic reference; the sync service will validate type and target together.
    entity_id: Mapped[int | None] = mapped_column()
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default=text("'pending'"), index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text)

