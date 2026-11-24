"""Production analytics and RAG observability queries."""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.analytics import QueryLog
from app.models.document import Document, DocumentStatus
from app.models.job import DocumentJob

logger = logging.getLogger(__name__)

_STOPWORDS = {
    "about", "after", "again", "against", "because", "before", "being", "between",
    "could", "does", "during", "every", "first", "found", "from", "further", "have",
    "having", "here", "into", "their", "there", "these", "they", "this", "those",
    "through", "under", "until", "what", "when", "where", "which", "while", "with",
    "would", "your", "patient", "patients", "medical", "medicine", "clinical",
}


def log_query(
    db: Session,
    user_id: int,
    question: str,
    answer: Optional[str],
    response_time: float,
    token_count: Optional[int] = None,
    language: str = "en",
    *,
    request_id: Optional[str] = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    mode: str = "agentic",
    retrieval_attempts: int = 0,
    web_search_used: bool = False,
    evidence_status: Optional[str] = None,
    graph_rag_used: bool = False,
    estimated_cost_usd: float = 0.0,
    sources: Optional[list] = None,
    latency_breakdown: Optional[dict] = None,
    error: Optional[str] = None,
    conversation_id: Optional[int] = None,
) -> QueryLog:
    entry = QueryLog(
        request_id=request_id,
        user_id=user_id,
        conversation_id=conversation_id,
        question=question,
        answer=answer,
        response_time=response_time,
        token_count=token_count if token_count is not None else (prompt_tokens + completion_tokens),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=estimated_cost_usd,
        language=language,
        mode=mode,
        retrieval_attempts=retrieval_attempts,
        web_search_used=web_search_used,
        evidence_status=evidence_status,
        graph_rag_used=graph_rag_used,
        sources=sources,
        latency_breakdown=latency_breakdown,
        error=error,
    )
    db.add(entry)
    db.commit()
    return entry


def get_usage_overview(db: Session, user_id: int) -> Dict:
    document_counts = dict(
        db.query(Document.status, func.count(Document.id))
        .filter(Document.user_id == user_id)
        .group_by(Document.status)
        .all()
    )
    total_documents = sum(document_counts.values())
    total_queries = db.query(QueryLog).filter(QueryLog.user_id == user_id).count()
    totals = (
        db.query(
            func.sum(QueryLog.token_count),
            func.avg(QueryLog.response_time),
            func.sum(QueryLog.estimated_cost_usd),
        )
        .filter(QueryLog.user_id == user_id)
        .first()
    )
    evidence_counts = dict(
        db.query(QueryLog.evidence_status, func.count(QueryLog.id))
        .filter(QueryLog.user_id == user_id)
        .group_by(QueryLog.evidence_status)
        .all()
    )
    web_fallback = (
        db.query(func.count(QueryLog.id))
        .filter(QueryLog.user_id == user_id, QueryLog.web_search_used.is_(True))
        .scalar()
        or 0
    )
    return {
        "total_documents": total_documents,
        "total_queries": total_queries,
        "total_tokens": int(totals[0] or 0),
        "avg_response_time": float(totals[1] or 0.0),
        "estimated_cost_usd": float(totals[2] or 0.0),
        "completed_documents": int(document_counts.get(DocumentStatus.COMPLETED.value, 0)),
        "processing_documents": int(
            document_counts.get(DocumentStatus.PROCESSING.value, 0)
            + document_counts.get(DocumentStatus.QUEUED.value, 0)
        ),
        "rejected_documents": int(document_counts.get(DocumentStatus.REJECTED.value, 0)),
        "failed_documents": int(document_counts.get(DocumentStatus.FAILED.value, 0)),
        "insufficient_evidence_queries": int(
            evidence_counts.get("insufficient", 0) + evidence_counts.get("rejected_domain", 0)
        ),
        "web_fallback_queries": int(web_fallback),
    }


def get_usage_graph_data(db: Session, user_id: int, period: str = "daily") -> List[Dict]:
    if period == "weekly":
        days = 30
    else:
        days = 7
    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    query_rows = (
        db.query(
            func.date(QueryLog.timestamp).label("date"),
            func.count(QueryLog.id).label("queries"),
        )
        .filter(QueryLog.user_id == user_id, QueryLog.timestamp >= start_date)
        .group_by(func.date(QueryLog.timestamp))
        .all()
    )
    document_rows = (
        db.query(
            func.date(Document.upload_date).label("date"),
            func.count(Document.id).label("documents"),
        )
        .filter(Document.user_id == user_id, Document.upload_date >= start_date)
        .group_by(func.date(Document.upload_date))
        .all()
    )
    documents_by_date = {
        (row.date if isinstance(row.date, str) else row.date.strftime("%Y-%m-%d")): int(row.documents)
        for row in document_rows
    }
    data_points = []
    for row in query_rows:
        date_key = row.date if isinstance(row.date, str) else row.date.strftime("%Y-%m-%d")
        data_points.append(
            {
                "date": date_key,
                "queries": int(row.queries),
                "documents": documents_by_date.get(date_key, 0),
            }
        )
    return sorted(data_points, key=lambda point: point["date"])


def get_top_topics(db: Session, user_id: int, limit: int = 5) -> List[Dict]:
    queries = (
        db.query(QueryLog.question)
        .filter(QueryLog.user_id == user_id)
        .order_by(QueryLog.timestamp.desc())
        .limit(500)
        .all()
    )
    words: List[str] = []
    for row in queries:
        words.extend(
            word
            for word in re.findall(r"\b[a-z]{5,}\b", (row.question or "").lower())
            if word not in _STOPWORDS
        )
    return [{"topic": word, "count": count} for word, count in Counter(words).most_common(limit)]


def get_observability_overview(db: Session, user_id: int) -> Dict:
    rows = (
        db.query(QueryLog)
        .filter(QueryLog.user_id == user_id)
        .order_by(QueryLog.timestamp.desc())
        .limit(500)
        .all()
    )
    if not rows:
        return {
            "total_requests": 0,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "avg_retrieval_attempts": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "estimated_cost_usd": 0.0,
            "abstention_rate": 0.0,
            "web_fallback_rate": 0.0,
            "error_count": 0,
            "latency": {},
        }

    latencies = sorted((row.response_time or 0.0) * 1000 for row in rows)
    p95_index = max(0, int(len(latencies) * 0.95) - 1)
    breakdown_totals: Dict[str, float] = {}
    for row in rows:
        for key, value in (row.latency_breakdown or {}).items():
            breakdown_totals[key] = breakdown_totals.get(key, 0.0) + float(value or 0)
    count = len(rows)
    insufficient = sum(1 for row in rows if row.evidence_status == "insufficient")
    web_used = sum(1 for row in rows if row.web_search_used)
    return {
        "total_requests": count,
        "avg_latency_ms": round(sum(latencies) / count, 2),
        "p95_latency_ms": round(latencies[p95_index], 2),
        "avg_retrieval_attempts": round(
            sum(row.retrieval_attempts or 0 for row in rows) / count, 2
        ),
        "prompt_tokens": int(sum(row.prompt_tokens or 0 for row in rows)),
        "completion_tokens": int(sum(row.completion_tokens or 0 for row in rows)),
        "estimated_cost_usd": round(sum(row.estimated_cost_usd or 0.0 for row in rows), 6),
        "abstention_rate": round(insufficient / count, 4),
        "web_fallback_rate": round(web_used / count, 4),
        "error_count": sum(1 for row in rows if row.error),
        "latency": {
            key: round(value / count, 2) for key, value in breakdown_totals.items()
        },
    }


def get_processing_status(db: Session, user_id: int) -> Dict:
    status_counts = dict(
        db.query(Document.status, func.count(Document.id))
        .filter(Document.user_id == user_id)
        .group_by(Document.status)
        .all()
    )
    active_jobs = (
        db.query(func.count(DocumentJob.id))
        .filter(
            DocumentJob.user_id == user_id,
            DocumentJob.status.in_(["queued", "running"]),
        )
        .scalar()
        or 0
    )
    failed_jobs = (
        db.query(func.count(DocumentJob.id))
        .filter(DocumentJob.user_id == user_id, DocumentJob.status == "failed")
        .scalar()
        or 0
    )
    recent = (
        db.query(Document)
        .filter(
            Document.user_id == user_id,
            Document.status.in_([DocumentStatus.FAILED.value, DocumentStatus.REJECTED.value]),
        )
        .order_by(Document.upload_date.desc())
        .limit(5)
        .all()
    )
    return {
        "status_counts": {str(key): int(value) for key, value in status_counts.items()},
        "active_jobs": int(active_jobs),
        "failed_jobs": int(failed_jobs),
        "recent_errors": [
            {
                "id": doc.id,
                "filename": doc.filename,
                "status": doc.status,
                "message": doc.rejection_reason or doc.error_message,
            }
            for doc in recent
        ],
    }


def estimate_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)
