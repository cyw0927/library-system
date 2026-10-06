from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin


class ReaderSettings(TimestampMixin, Base):
    __tablename__ = "reader_settings"
    user_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    preferences: Mapped[dict] = mapped_column(JSON, nullable=False)
