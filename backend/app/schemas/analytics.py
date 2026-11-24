from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class UsageOverview(BaseModel):
    total_documents: int
    total_queries: int
    total_tokens: int
    avg_response_time: float
    completed_documents: int = 0
    processing_documents: int = 0
    rejected_documents: int = 0
    failed_documents: int = 0
    insufficient_evidence_queries: int = 0
    web_fallback_queries: int = 0
    estimated_cost_usd: float = 0.0


class UsageDataPoint(BaseModel):
    date: str
    queries: int
    documents: int


class UsageGraphData(BaseModel):
    data_points: List[UsageDataPoint]
    period: str


class TopicData(BaseModel):
    topic: str
    count: int


class TopTopics(BaseModel):
    topics: List[TopicData]


class LatencyBreakdown(BaseModel):
    embedding_ms: float = 0.0
    retrieval_ms: float = 0.0
    rerank_ms: float = 0.0
    llm_ms: float = 0.0
    web_search_ms: float = 0.0
    verification_ms: float = 0.0
    total_ms: float = 0.0


class ObservabilityOverview(BaseModel):
    total_requests: int = 0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    avg_retrieval_attempts: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float = 0.0
    abstention_rate: float = 0.0
    web_fallback_rate: float = 0.0
    error_count: int = 0
    latency: LatencyBreakdown = Field(default_factory=LatencyBreakdown)


class ProcessingStatusResponse(BaseModel):
    status_counts: Dict[str, int] = Field(default_factory=dict)
    active_jobs: int = 0
    failed_jobs: int = 0
    recent_errors: List[Dict[str, Optional[str]]] = Field(default_factory=list)
