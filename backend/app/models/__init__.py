"""Import every model so Alembic and ``Base.metadata`` see the full schema."""

from app.models.analytics import EvaluationRecord, QueryLog, ToolExecution, UsageStats
from app.models.chunk import DocumentChunk
from app.models.conversation import Conversation
from app.models.document import Document, DocumentStatus
from app.models.graph import KnowledgeEntity, KnowledgeRelation
from app.models.job import DocumentJob, JobStatus
from app.models.user import User

__all__ = [
    "User",
    "Document",
    "DocumentStatus",
    "DocumentChunk",
    "Conversation",
    "QueryLog",
    "UsageStats",
    "ToolExecution",
    "EvaluationRecord",
    "DocumentJob",
    "JobStatus",
    "KnowledgeEntity",
    "KnowledgeRelation",
]
