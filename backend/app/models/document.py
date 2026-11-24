from __future__ import annotations

import enum
import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class DocumentStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class Document(Base):
    """Metadata for an uploaded medical document.

    The binary object lives in Supabase Storage; only this metadata row and the
    extracted chunks are persisted in PostgreSQL.  ``id`` is a stable UUID used
    for chunk ownership and deletion filters (never the filename).
    """

    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(512), nullable=False)
    storage_path = Column(String(1024), nullable=False)
    mime_type = Column(String(128), nullable=True)
    file_size = Column(Integer, nullable=False, default=0)
    file_hash = Column(String(64), nullable=True, index=True)

    status = Column(String(20), nullable=False, default=DocumentStatus.QUEUED.value, index=True)
    progress = Column(Integer, nullable=False, default=0)
    stage = Column(String(120), nullable=True)
    error_message = Column(Text, nullable=True)
    rejection_reason = Column(Text, nullable=True)

    page_count = Column(Integer, nullable=False, default=0)
    chunk_count = Column(Integer, nullable=False, default=0)
    document_metadata = Column(JSON, nullable=True)
    is_medical = Column(Integer, nullable=True)  # 1/0 classification outcome
    domain_confidence = Column(Integer, nullable=True)  # 0-100

    upload_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    chunks = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Document {self.id} {self.filename} ({self.status})>"
