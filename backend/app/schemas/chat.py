from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatQuery(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    language: Optional[str] = "en"
    mode: Optional[str] = Field(default="agentic", description="'agentic' (default) or 'standard'")
    allow_web_search: Optional[bool] = None
    document_ids: Optional[List[str]] = None
    # Optional for backward compatibility: omitting it creates a conversation.
    conversation_id: Optional[int] = Field(default=None, ge=1)


class SourceCitation(BaseModel):
    """A single piece of evidence backing the answer."""

    index: int
    kind: str = "document"  # document | web
    document_id: Optional[str] = None
    filename: Optional[str] = None
    page: Optional[int] = None
    content_type: Optional[str] = None
    table_id: Optional[str] = None
    section: Optional[str] = None
    snippet: str = ""
    title: Optional[str] = None
    url: Optional[str] = None
    publisher: Optional[str] = None
    score: Optional[float] = None


class ClaimVerification(BaseModel):
    claim: str
    evidence_indexes: List[int] = Field(default_factory=list)
    supported: bool = False


class AgentMetadata(BaseModel):
    request_id: Optional[str] = None
    original_question: Optional[str] = None
    transformed_query: Optional[str] = None
    query_transform_status: str = "disabled"  # llm | fallback | disabled
    query_transform_error: Optional[str] = None
    retrieval_attempts: int = 1
    retrieval_refined: bool = False
    retrieval_improved: Optional[bool] = None
    documents_retrieved: int = 0
    passages_retained: int = 0
    relevance_score: float = 0.0
    evidence_coverage: float = 0.0
    evidence_threshold: float = 0.0
    evidence_outcome: str = ""  # sufficient | partial | insufficient
    abstention_reason: Optional[str] = None
    verification_status: str = "skipped"  # verified | unverified | skipped | disabled
    steps: List[str] = Field(default_factory=list)
    fallback_to_standard: bool = False
    subqueries: List[str] = Field(default_factory=list)
    evidence_status: str = "sufficient"
    web_search_used: bool = False
    web_search_enabled: bool = False
    graph_rag_used: bool = False
    claims: List[ClaimVerification] = Field(default_factory=list)
    latency_ms: Dict[str, float] = Field(default_factory=dict)
    token_usage: Dict[str, int] = Field(default_factory=dict)
    estimated_cost_usd: float = 0.0
    reranker: Optional[str] = None
    errors: List[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceCitation]
    response_time: float
    language: str = "en"
    mode: Optional[str] = "agentic"
    evidence_status: str = "sufficient"
    insufficient_evidence: bool = False
    agent_metadata: Optional[AgentMetadata] = None
    conversation_id: Optional[int] = None
    conversation_title: Optional[str] = None


class ChatHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    answer: Optional[str] = None
    timestamp: datetime
    language: str = "en"
    sources: Optional[List[Dict[str, Any]]] = None


class ChatHistoryResponse(BaseModel):
    history: List[ChatHistoryItem]
    total: int


# ----------------------------------------------------------------- conversations


class ConversationSummary(BaseModel):
    id: int
    title: str
    is_pinned: bool = False
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary]
    total: int


class ConversationUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    is_pinned: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def _normalise_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return " ".join(value.split())


class ConversationMessage(BaseModel):
    id: int
    question: str
    answer: Optional[str] = None
    timestamp: datetime
    language: str = "en"
    mode: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None
    evidence_status: Optional[str] = None
    insufficient_evidence: bool = False


class ConversationDetail(ConversationSummary):
    messages: List[ConversationMessage] = Field(default_factory=list)
