from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, false, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (CheckConstraint("role IN ('admin', 'reader')", name="valid_account_role"),)
    id: Mapped[str] = mapped_column(String(100), primary_key=True, default=lambda: uuid4().hex)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="reader", server_default="reader")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginSession(Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
