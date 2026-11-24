from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.middlewares.auth_middleware import get_current_user
from app.models.analytics import QueryLog
from app.models.conversation import Conversation
from app.models.document import Document, DocumentStatus
from app.models.user import User
from app.providers.base import ProviderError, ProviderNotConfigured
from app.schemas.chat import (
    ChatHistoryResponse,
    ChatQuery,
    ChatResponse,
    ConversationDetail,
    ConversationListResponse,
    ConversationMessage,
    ConversationSummary,
    ConversationUpdate,
)
from app.services.agentic_rag import RagResult, domain_rejection_result, run_rag
from app.services.analytics import log_query
from app.services.conversation_titles import generate_conversation_title
from app.services.domain_validation import validate_query
from app.services.observability import RequestTrace, safe_log
from app.services.translation import process_multilingual_query, translate_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])

AI_UNAVAILABLE_MESSAGE = (
    "The AI services for this deployment are not configured or are temporarily "
    "unavailable. Please try again later."
)

INSUFFICIENT_STATUSES = {"insufficient", "rejected_domain"}


def _ensure_documents(db: Session, user: User, document_ids: Optional[list]) -> None:
    query = db.query(Document).filter(Document.user_id == user.id)
    if document_ids:
        query = query.filter(Document.id.in_(document_ids))
    if query.count() == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No documents found. Please upload medical documents first.",
        )
    if document_ids:
        found = {doc.id for doc in query.all()}
        missing = set(document_ids) - found
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more documents were not found.",
            )


def _to_response(result: RagResult, conversation: Optional[Conversation] = None) -> ChatResponse:
    return ChatResponse(
        answer=result.answer,
        sources=result.sources,
        response_time=round(result.metadata.latency_ms.get("total_ms", 0.0) / 1000, 3),
        language="en",
        mode=result.mode,
        evidence_status=result.evidence_status,
        insufficient_evidence=result.insufficient,
        agent_metadata=result.metadata,
        conversation_id=conversation.id if conversation is not None else None,
        conversation_title=conversation.title if conversation is not None else None,
    )


def _persist(
    db: Session,
    user: User,
    question: str,
    result: RagResult,
    trace: RequestTrace,
    *,
    language: str = "en",
    mode: str = "agentic",
    conversation: Optional[Conversation] = None,
) -> Optional[Conversation]:
    """Store the answer as a conversation message (and analytics record).

    The conversation is committed before the log is written so a failed
    log write can never leave a response pointing at a rolled-back thread.
    """
    if conversation is None:
        conversation = Conversation(
            user_id=user.id, title=generate_conversation_title(question)
        )
        db.add(conversation)
        try:
            db.commit()
            db.refresh(conversation)
        except Exception as exc:  # noqa: BLE001 - chat must still answer
            logger.error("Could not create conversation: %s", exc)
            db.rollback()
            return None

    try:
        conversation.updated_at = datetime.now(timezone.utc)
        log_query(
            db=db,
            user_id=user.id,
            question=question,
            answer=result.answer,
            response_time=trace.elapsed_ms / 1000,
            token_count=trace.total_tokens,
            language=language,
            request_id=trace.request_id,
            prompt_tokens=trace.prompt_tokens,
            completion_tokens=trace.completion_tokens,
            mode=mode,
            retrieval_attempts=result.metadata.retrieval_attempts,
            web_search_used=result.web_search_used,
            evidence_status=result.evidence_status,
            graph_rag_used=result.metadata.graph_rag_used,
            estimated_cost_usd=trace.estimated_cost_usd(),
            sources=[citation.model_dump() for citation in result.sources],
            latency_breakdown=trace.latency_breakdown(),
            error="; ".join(trace.errors) if trace.errors else None,
            conversation_id=conversation.id,
        )
    except Exception as exc:  # noqa: BLE001 - logging must not fail the request
        logger.error("Could not persist query log: %s", exc)
        db.rollback()
    return conversation


def _resolve_conversation(
    db: Session, user: User, conversation_id: Optional[int]
) -> Optional[Conversation]:
    """Return the caller's conversation or reject the request (404, no leak)."""
    if conversation_id is None:
        return None
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .first()
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        )
    return conversation


async def _answer(
    db: Session,
    user: User,
    query: ChatQuery,
    *,
    question: str,
    multilang: bool = False,
    detected_language: str = "en",
) -> ChatResponse:
    """Shared RAG + persistence path for both query endpoints."""
    trace = RequestTrace(user_id=user.id)
    settings = get_settings()
    language = detected_language if multilang else (query.language or "en")

    validation = await validate_query(question)
    if not validation.is_medical:
        result = domain_rejection_result(query.question, validation.reason, trace)
        conversation = _persist(
            db,
            user,
            query.question,
            result,
            trace,
            language=language,
            mode="standard" if multilang else (query.mode or "agentic"),
            conversation=_resolve_conversation(db, user, query.conversation_id),
        )
        response = _to_response(result, conversation)
        response.language = language
        return response

    _ensure_documents(db, user, query.document_ids)
    completed = (
        db.query(Document)
        .filter(Document.user_id == user.id, Document.status == DocumentStatus.COMPLETED.value)
        .count()
    )
    if completed == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your documents are still processing. Please retry once ingestion completes.",
        )

    mode = "agentic" if multilang else (query.mode if query.mode in {"standard", "agentic"} else "agentic")
    try:
        result = await run_rag(
            db,
            user_id=user.id,
            question=question,
            document_ids=query.document_ids,
            allow_web_search=query.allow_web_search,
            mode=mode,
            trace=trace,
        )
    except ProviderNotConfigured as exc:
        logger.error("AI provider not configured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=AI_UNAVAILABLE_MESSAGE
        )
    except ProviderError as exc:
        logger.error("AI provider error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=AI_UNAVAILABLE_MESSAGE
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Unexpected RAG failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The question could not be processed. Please retry.",
        )

    if multilang and detected_language != "en" and not result.insufficient:
        result.answer = await translate_response(result.answer, detected_language)

    result.metadata.web_search_enabled = settings.web_search_enabled
    conversation = _persist(
        db,
        user,
        query.question,
        result,
        trace,
        language=language,
        mode=mode,
        conversation=_resolve_conversation(db, user, query.conversation_id),
    )
    response = _to_response(result, conversation)
    response.language = language
    return response


@router.post("/query", response_model=ChatResponse)
async def ask_question(
    query: ChatQuery,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ask a medical question using the self-correcting hybrid RAG pipeline."""
    safe_log(
        "chat_query_received",
        user_id=user.id,
        mode=query.mode,
        conversation_id=query.conversation_id,
        question_length=len(query.question),
    )
    return await _answer(db, user, query, question=query.question)


@router.post("/query-multilang", response_model=ChatResponse)
async def ask_question_multilang(
    query: ChatQuery,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Detect, translate to English, answer with RAG, then translate back."""
    english_question, detected_language = await process_multilingual_query(query.question)
    return await _answer(
        db,
        user,
        query,
        question=english_question,
        multilang=True,
        detected_language=detected_language or "en",
    )


# --------------------------------------------------------------- conversations


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive timestamps; they are stored as UTC."""
    if value is None:
        return value
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _message_counts(db: Session, user_id: int) -> Dict[int, int]:
    rows = (
        db.query(QueryLog.conversation_id, func.count(QueryLog.id))
        .filter(QueryLog.user_id == user_id, QueryLog.conversation_id.isnot(None))
        .group_by(QueryLog.conversation_id)
        .all()
    )
    return {int(conversation_id): int(count) for conversation_id, count in rows if conversation_id}


def _summary(conversation: Conversation, message_count: int = 0) -> ConversationSummary:
    return ConversationSummary(
        id=conversation.id,
        title=conversation.title,
        is_pinned=bool(conversation.is_pinned),
        created_at=_as_utc(conversation.created_at),
        updated_at=_as_utc(conversation.updated_at),
        message_count=message_count,
    )


def _owned_conversation(db: Session, user: User, conversation_id: int) -> Conversation:
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user.id)
        .first()
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        )
    return conversation


@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    q: Optional[str] = Query(default=None, max_length=120),
    limit: int = Query(default=200, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List the signed-in user's conversations, pinned first then newest."""
    counts = _message_counts(db, user.id)
    query = db.query(Conversation).filter(Conversation.user_id == user.id)
    term = (q or "").strip()
    if term:
        query = query.filter(Conversation.title.ilike(f"%{term}%"))
    rows: List[Conversation] = (
        query.order_by(
            Conversation.is_pinned.desc(),
            Conversation.updated_at.desc(),
            Conversation.id.desc(),
        )
        .limit(limit)
        .all()
    )
    conversations = [_summary(row, counts.get(row.id, 0)) for row in rows]
    return {"conversations": conversations, "total": len(conversations)}


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = _owned_conversation(db, user, conversation_id)
    logs = (
        db.query(QueryLog)
        .filter(
            QueryLog.user_id == user.id,
            QueryLog.conversation_id == conversation.id,
        )
        .order_by(QueryLog.id.asc())
        .all()
    )
    messages = [
        ConversationMessage(
            id=log.id,
            question=log.question,
            answer=log.answer,
            timestamp=_as_utc(log.timestamp),
            language=log.language or "en",
            mode=log.mode,
            sources=log.sources,
            evidence_status=log.evidence_status,
            insufficient_evidence=(log.evidence_status in INSUFFICIENT_STATUSES),
        )
        for log in logs
    ]
    summary = _summary(conversation, len(messages))
    return ConversationDetail(**summary.model_dump(), messages=messages)


@router.patch("/conversations/{conversation_id}", response_model=ConversationSummary)
def update_conversation(
    conversation_id: int,
    payload: ConversationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Rename and/or pin a conversation.

    ``updated_at`` is intentionally untouched: renaming or pinning must not
    reshuffle the chronological history.
    """
    conversation = _owned_conversation(db, user, conversation_id)
    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Title cannot be empty.",
            )
        conversation.title = title
    if payload.is_pinned is not None:
        conversation.is_pinned = payload.is_pinned
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return _summary(conversation, _message_counts(db, user.id).get(conversation.id, 0))


@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = _owned_conversation(db, user, conversation_id)
    deleted_messages = (
        db.query(QueryLog)
        .filter(
            QueryLog.user_id == user.id,
            QueryLog.conversation_id == conversation.id,
        )
        .delete(synchronize_session=False)
    )
    db.delete(conversation)
    db.commit()
    return {
        "message": "Conversation deleted",
        "deleted": conversation_id,
        "deleted_messages": int(deleted_messages),
    }


# ------------------------------------------------------- legacy flat history


@router.get("/history", response_model=ChatHistoryResponse)
def get_chat_history(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    history = (
        db.query(QueryLog)
        .filter(QueryLog.user_id == user.id)
        .order_by(QueryLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return {"history": history, "total": len(history)}


@router.delete("/history")
def clear_chat_history(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    deleted = db.query(QueryLog).filter(QueryLog.user_id == user.id).delete()
    db.query(Conversation).filter(Conversation.user_id == user.id).delete()
    db.commit()
    return {"message": "Chat history cleared successfully", "deleted": int(deleted)}
