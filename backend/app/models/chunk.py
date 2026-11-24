from __future__ import annotations

import json
import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, TypeDecorator
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.config import get_settings
from app.database import Base

_content_types = {"text", "table", "chart", "image", "graph_fact"}


class EmbeddingVector(TypeDecorator):
    """Portable pgvector storage.

    Embeddings are written as pgvector literal strings (``[0.1,0.2,...]``).
    On PostgreSQL the ``chunks.embedding`` column is ``text`` and is cast to
    ``vector(n)`` inside similarity queries, with an HNSW expression index
    created by the Alembic migration.  This keeps one code path that also works
    on SQLite for tests, without pulling a database-specific Python package.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001 - SQLAlchemy hook
        if value is None:
            return None
        return "[" + ",".join(f"{float(v):.7f}" for v in value) + "]"

    def process_result_value(self, value, dialect):  # noqa: ANN001 - SQLAlchemy hook
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, str):
            return json.loads(value)
        return list(value)  # pragma: no cover - defensive


class DocumentChunk(Base):
    __tablename__ = "chunks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False, default=0)

    content = Column(Text, nullable=False)
    content_type = Column(String(20), nullable=False, default="text")
    page = Column(Integer, nullable=True)
    section = Column(String(512), nullable=True)
    table_id = Column(String(120), nullable=True)
    token_estimate = Column(Integer, nullable=False, default=0)
    chunk_metadata = Column(JSON, nullable=True)
    embedding = Column(EmbeddingVector, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document = relationship("Document", back_populates="chunks")

    @property
    def embedding_dimensions(self) -> int:
        return get_settings().embedding_dimensions
