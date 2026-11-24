from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class JobStatus(str):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DocumentJob(Base):
    """Durable, database-backed processing job.

    The unique constraint makes enqueueing idempotent so a retried upload or a
    duplicate re-index request cannot start parallel work for one document.
    """

    __tablename__ = "document_jobs"
    __table_args__ = (UniqueConstraint("document_id", "job_type", name="uq_document_job"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    job_type = Column(String(40), nullable=False, default="ingest")
    status = Column(String(20), nullable=False, default=JobStatus.QUEUED, index=True)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    progress = Column(Integer, nullable=False, default=0)
    stage = Column(String(120), nullable=True)
    payload = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    worker_id = Column(String(80), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
