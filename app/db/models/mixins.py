from datetime import datetime

from sqlalchemy import Boolean, DateTime, func, true
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
        nullable=False,
    )


class ActiveMixin:
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False,
    )

