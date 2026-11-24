from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class KnowledgeEntity(Base):
    """Medical entity extracted from a user's documents and linked per user."""

    __tablename__ = "kg_entities"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_name", "entity_type", name="uq_kg_entity"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(300), nullable=False)
    normalized_name = Column(String(300), nullable=False, index=True)
    entity_type = Column(String(40), nullable=False, index=True)
    description = Column(Text, nullable=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    page = Column(Integer, nullable=True)
    properties = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class KnowledgeRelation(Base):
    __tablename__ = "kg_relations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_entity_id = Column(
        String(36), ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_entity_id = Column(
        String(36), ForeignKey("kg_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type = Column(String(80), nullable=False)
    confidence = Column(Float, nullable=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    page = Column(Integer, nullable=True)
    evidence_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
