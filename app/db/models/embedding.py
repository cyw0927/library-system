from sqlalchemy import CheckConstraint, ForeignKey, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.mixins import TimestampMixin


class Embedding(TimestampMixin, Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint("paragraph_id", "provider", "model", name="uq_embeddings_paragraph_provider_model"),
        CheckConstraint("dimensions >= 1 AND dimensions <= 3072", name="valid_dimensions"),
        CheckConstraint("input_characters >= 1", name="positive_input_characters"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    paragraph_id: Mapped[int] = mapped_column(ForeignKey("paragraphs.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    dimensions: Mapped[int] = mapped_column(Integer)
    input_characters: Mapped[int] = mapped_column(Integer)
    # Portable storage; PostgreSQL casts to pgvector for exact SQL nearest-neighbor search.
    # Native vector columns/HNSW can be added when bulk indexing volume warrants it.
    vector_data: Mapped[list[float]] = mapped_column(JSON)
