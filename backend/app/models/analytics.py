from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class QueryLog(Base):
    """Chat history plus per-request RAG observability.

    This is production analytics, not evaluation; see ``EvaluationRecord`` for
    offline quality measurement.
    """

    __tablename__ = "query_logs"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(64), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(
        Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    response_time = Column(Float, nullable=True)
    prompt_tokens = Column(Integer, nullable=True, default=0)
    completion_tokens = Column(Integer, nullable=True, default=0)
    token_count = Column(Integer, nullable=True)
    estimated_cost_usd = Column(Float, nullable=True, default=0.0)
    language = Column(String(12), default="en")
    mode = Column(String(20), default="agentic")
    retrieval_attempts = Column(Integer, nullable=True, default=0)
    web_search_used = Column(Boolean, nullable=False, default=False)
    evidence_status = Column(String(20), nullable=True)
    graph_rag_used = Column(Boolean, nullable=False, default=False)
    cached = Column(Boolean, nullable=False, default=False)
    error = Column(Text, nullable=True)
    sources = Column(JSON, nullable=True)
    latency_breakdown = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    conversation = relationship("Conversation", back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<QueryLog user={self.user_id} at={self.timestamp}>"


class UsageStats(Base):
    """Aggregate counters (kept for compatibility with existing analytics)."""

    __tablename__ = "usage_stats"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    date = Column(DateTime(timezone=True), server_default=func.now())
    total_queries = Column(Integer, default=0)
    total_documents = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)


class ToolExecution(Base):
    """Trace of every controlled tool/MCP invocation."""

    __tablename__ = "tool_executions"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(64), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_name = Column(String(80), nullable=False)
    status = Column(String(20), nullable=False, default="success")
    latency_ms = Column(Integer, nullable=True)
    input_summary = Column(JSON, nullable=True)
    output_summary = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EvaluationRecord(Base):
    """Stored result of an offline RAG evaluation item."""

    __tablename__ = "evaluation_records"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    category = Column(String(40), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    metrics = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
