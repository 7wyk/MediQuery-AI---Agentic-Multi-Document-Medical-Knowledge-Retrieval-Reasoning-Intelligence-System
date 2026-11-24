"""Hybrid retrieval: pgvector similarity + PostgreSQL full-text search with RRF.

On SQLite (tests/local development only) the same interface is served with
in-process cosine scoring and lexical overlap so behaviour stays testable.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import engine, is_postgres
from app.models.chunk import DocumentChunk
from app.models.document import Document
from app.providers.base import ProviderError
from app.providers.registry import get_embedding_provider
from app.schemas.chat import SourceCitation
from app.services.observability import RequestTrace

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{1,}", re.IGNORECASE)


@dataclass
class SearchHit:
    chunk_id: str
    document_id: str
    user_id: int
    filename: str
    content: str
    content_type: str = "text"
    page: Optional[int] = None
    section: Optional[str] = None
    table_id: Optional[str] = None
    score: float = 0.0
    metadata: dict = field(default_factory=dict)
    vector_score: Optional[float] = None
    keyword_score: Optional[float] = None
    rerank_score: Optional[float] = None
    source_kind: str = "document"

    def as_citation(self, index: int) -> SourceCitation:
        return SourceCitation(
            index=index,
            kind=self.source_kind,
            document_id=self.document_id,
            filename=self.filename,
            page=self.page,
            content_type=self.content_type,
            table_id=self.table_id,
            section=self.section,
            snippet=self.content[:600],
            score=round(self.rerank_score if self.rerank_score is not None else self.score, 4),
        )


@dataclass
class HybridSearchResult:
    hits: List[SearchHit]
    vector_used: bool = True
    keyword_used: bool = True
    errors: List[str] = field(default_factory=list)


def _tokens(text_value: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text_value)]


_TSQUERY_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "have",
    "has", "had", "not", "but", "you", "your", "what", "which", "who", "how", "why",
    "when", "where", "does", "did", "can", "could", "should", "would", "about", "into",
    "than", "then", "there", "their", "they", "its", "of", "in", "on", "to", "is", "it",
}


def content_terms(value: str) -> set:
    """Lowercase content words (no stopwords) used for aspect matching."""
    return {
        term
        for term in re.findall(r"[a-z0-9][a-z0-9\-]{1,}", (value or "").lower())
        if len(term) > 2 and term not in _TSQUERY_STOPWORDS
    }


def build_or_tsquery(query: str, *, max_terms: int = 24) -> str:
    """Build an OR ``to_tsquery`` string from a natural-language query.

    ``plainto_tsquery`` ANDs every term, so a multi-part question such as
    "what is hypertension and what causes it" matches almost nothing. Full-text
    search is a recall channel fused with vector search by RRF, so OR semantics
    (ranked by ts_rank_cd) is the correct behaviour here. Terms are reduced to
    alphanumerics so no tsquery operators can be injected.
    """
    terms: List[str] = []
    for raw in re.findall(r"[a-z0-9]+", (query or "").lower()):
        if len(raw) < 2 or raw in _TSQUERY_STOPWORDS or raw in terms:
            continue
        terms.append(raw)
    return " | ".join(terms[:max_terms])


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    na = math.sqrt(sum(float(x) * float(x) for x in a))
    nb = math.sqrt(sum(float(y) * float(y) for y in b))
    if na <= 1e-12 or nb <= 1e-12:
        return 0.0
    return dot / (na * nb)


def _rows_to_hits(rows: Iterable) -> List[SearchHit]:
    hits: List[SearchHit] = []
    for row in rows:
        mapping = row._mapping
        metadata = mapping.get("chunk_metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        hits.append(
            SearchHit(
                chunk_id=mapping["id"],
                document_id=mapping["document_id"],
                user_id=mapping["user_id"],
                filename=mapping.get("filename") or "document",
                content=mapping.get("content") or "",
                content_type=mapping.get("content_type") or "text",
                page=mapping.get("page"),
                section=mapping.get("section"),
                table_id=mapping.get("table_id"),
                score=float(mapping.get("score") or 0.0),
                metadata=metadata,
            )
        )
    return hits


async def vector_search(
    db: Session,
    user_id: int,
    query_embedding: Sequence[float],
    *,
    top_k: int = 30,
    document_ids: Optional[List[str]] = None,
) -> List[SearchHit]:
    settings = get_settings()
    dim = int(settings.embedding_dimensions)
    vector_literal = "[" + ",".join(f"{float(v):.7f}" for v in query_embedding) + "]"

    if is_postgres():
        sql = f"""
            SELECT c.id, c.document_id, c.user_id, c.content, c.content_type, c.page,
                   c.section, c.table_id, c.chunk_metadata, d.filename,
                   1 - ((c.embedding::vector({dim})) <=> CAST(:qv AS vector({dim}))) AS score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.user_id = :user_id
              AND c.embedding IS NOT NULL
              AND (:filter_docs = 0 OR c.document_id IN :doc_ids)
            ORDER BY (c.embedding::vector({dim})) <=> CAST(:qv AS vector({dim}))
            LIMIT :limit
        """
        stmt = text(sql).bindparams(bindparam("doc_ids", expanding=True))
        rows = db.execute(
            stmt,
            {
                "qv": vector_literal,
                "user_id": int(user_id),
                "filter_docs": 1 if document_ids else 0,
                "doc_ids": list(document_ids or []),
                "limit": int(top_k),
            },
        ).fetchall()
        return _rows_to_hits(rows)

    # Development/test fallback: exact cosine over the user's chunks.
    query = db.query(DocumentChunk).filter(
        DocumentChunk.user_id == user_id, DocumentChunk.embedding.isnot(None)
    )
    if document_ids:
        query = query.filter(DocumentChunk.document_id.in_(document_ids))
    chunks = query.limit(5000).all()
    documents = {
        doc.id: doc
        for doc in db.query(Document).filter(Document.user_id == user_id).all()
    }
    scored: List[SearchHit] = []
    for chunk in chunks:
        embedding = chunk.embedding or []
        score = cosine_similarity(query_embedding, embedding)
        document = documents.get(chunk.document_id)
        scored.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                user_id=chunk.user_id,
                filename=document.filename if document else "document",
                content=chunk.content,
                content_type=chunk.content_type,
                page=chunk.page,
                section=chunk.section,
                table_id=chunk.table_id,
                score=score,
                metadata=chunk.chunk_metadata or {},
            )
        )
    scored.sort(key=lambda hit: hit.score, reverse=True)
    return scored[:top_k]


async def keyword_search(
    db: Session,
    user_id: int,
    query: str,
    *,
    top_k: int = 30,
    document_ids: Optional[List[str]] = None,
) -> List[SearchHit]:
    if not query.strip():
        return []

    if is_postgres():
        tsquery = build_or_tsquery(query)
        if not tsquery:
            return []
        sql = """
            SELECT c.id, c.document_id, c.user_id, c.content, c.content_type, c.page,
                   c.section, c.table_id, c.chunk_metadata, d.filename,
                   ts_rank_cd(to_tsvector('english', c.content),
                              to_tsquery('english', :q)) AS score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.user_id = :user_id
              AND (:filter_docs = 0 OR c.document_id IN :doc_ids)
              AND to_tsvector('english', c.content) @@ to_tsquery('english', :q)
            ORDER BY score DESC
            LIMIT :limit
        """
        stmt = text(sql).bindparams(bindparam("doc_ids", expanding=True))
        try:
            rows = db.execute(
                stmt,
                {
                    "q": query,
                    "user_id": int(user_id),
                    "filter_docs": 1 if document_ids else 0,
                    "doc_ids": list(document_ids or []),
                    "limit": int(top_k),
                },
            ).fetchall()
        except Exception as exc:  # noqa: BLE001 - malformed tsquery etc.
            logger.warning("Full-text query failed: %s", exc)
            db.rollback()
            return []
        return _rows_to_hits(rows)

    query_terms = set(_tokens(query))
    if not query_terms:
        return []
    chunks_query = db.query(DocumentChunk).filter(DocumentChunk.user_id == user_id)
    if document_ids:
        chunks_query = chunks_query.filter(DocumentChunk.document_id.in_(document_ids))
    chunks = chunks_query.limit(5000).all()
    documents = {
        doc.id: doc for doc in db.query(Document).filter(Document.user_id == user_id).all()
    }
    hits: List[SearchHit] = []
    for chunk in chunks:
        content_terms = _tokens(chunk.content)
        if not content_terms:
            continue
        overlaps = sum(1 for term in content_terms if term in query_terms)
        if overlaps == 0:
            continue
        score = overlaps / (len(content_terms) ** 0.5 + 1)
        document = documents.get(chunk.document_id)
        hits.append(
            SearchHit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                user_id=chunk.user_id,
                filename=document.filename if document else "document",
                content=chunk.content,
                content_type=chunk.content_type,
                page=chunk.page,
                section=chunk.section,
                table_id=chunk.table_id,
                score=score,
                metadata=chunk.chunk_metadata or {},
            )
        )
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:top_k]


def reciprocal_rank_fusion(
    result_lists: Sequence[Sequence[SearchHit]], *, k: int = 60
) -> List[SearchHit]:
    fused: dict[str, SearchHit] = {}
    scores: dict[str, float] = {}
    for results in result_lists:
        for rank, hit in enumerate(results, start=1):
            existing = fused.get(hit.chunk_id)
            if existing is None:
                fused[hit.chunk_id] = hit
                scores[hit.chunk_id] = 0.0
            scores[hit.chunk_id] += 1.0 / (k + rank)
    for chunk_id, hit in fused.items():
        hit.score = round(scores[chunk_id], 6)
    return sorted(fused.values(), key=lambda hit: hit.score, reverse=True)


def select_evidence(
    hits: Sequence[SearchHit],
    aspects: Sequence[str],
    top_k: int,
    *,
    per_page_limit: int = 3,
    duplicate_jaccard: float = 0.9,
) -> List[SearchHit]:
    """Select passages for generation with aspect coverage and diversity.

    Reranking alone orders passages by relevance to the *whole* question, which
    under-serves multi-part questions (a definition passage can be pushed out by
    several symptom passages). This selection first guarantees the best passage
    for each question aspect, then fills the remaining slots by score while
    avoiding near-duplicate text and over-representing a single page.
    """
    if not hits or top_k <= 0:
        return []

    selected: List[SearchHit] = []
    selected_ids: set[str] = set()
    seen_pages: Dict[tuple, int] = {}
    seen_token_sets: List[set[str]] = []

    def _score(hit: SearchHit) -> float:
        return float(hit.rerank_score if hit.rerank_score is not None else hit.score or 0.0)

    def _can_add(hit: SearchHit) -> bool:
        # The per-page cap only applies to real PDF pages; chunks without a page
        # (graph/web evidence) must not all collapse onto one bucket.
        if hit.page is not None:
            page_key = (hit.document_id, hit.page)
            if seen_pages.get(page_key, 0) >= per_page_limit:
                return False
        tokens = set(_tokens(hit.content))
        if tokens:
            for existing in seen_token_sets:
                union = tokens | existing
                if union and len(tokens & existing) / len(union) >= duplicate_jaccard:
                    return False
        return True

    def _add(hit: SearchHit) -> None:
        selected.append(hit)
        selected_ids.add(hit.chunk_id)
        page_key = (hit.document_id, hit.page)
        seen_pages[page_key] = seen_pages.get(page_key, 0) + 1
        seen_token_sets.append(set(_tokens(hit.content)))

    for aspect in aspects or []:
        aspect_terms = content_terms(aspect)
        if not aspect_terms or len(selected) >= top_k:
            continue
        ranked_for_aspect: List[tuple] = []
        for hit in hits:
            if hit.chunk_id in selected_ids or not _can_add(hit):
                continue
            overlap = len(aspect_terms & content_terms(hit.content)) / len(aspect_terms)
            if overlap < 0.34:
                continue
            ranked_for_aspect.append((overlap, _score(hit), hit))
        ranked_for_aspect.sort(key=lambda item: (item[0], item[1]), reverse=True)
        # Two passages per aspect: the strongest match plus a second candidate that
        # may be the definition/overview passage rather than a same-topic detail.
        for _, _, hit in ranked_for_aspect[:2]:
            if len(selected) >= top_k:
                break
            if hit.chunk_id in selected_ids or not _can_add(hit):
                continue
            _add(hit)

    for hit in hits:
        if len(selected) >= top_k:
            break
        if hit.chunk_id in selected_ids or not _can_add(hit):
            continue
        _add(hit)

    return selected[:top_k]


def deduplicate(hits: Sequence[SearchHit], limit: Optional[int] = None) -> List[SearchHit]:
    seen: set[str] = set()
    unique: List[SearchHit] = []
    for hit in hits:
        if hit.chunk_id in seen:
            continue
        seen.add(hit.chunk_id)
        unique.append(hit)
        if limit and len(unique) >= limit:
            break
    return unique


async def hybrid_search(
    db: Session,
    user_id: int,
    query: str,
    *,
    top_k: int,
    candidates: Optional[int] = None,
    keyword_candidates: Optional[int] = None,
    document_ids: Optional[List[str]] = None,
    trace: Optional[RequestTrace] = None,
) -> HybridSearchResult:
    settings = get_settings()
    candidate_count = candidates or settings.retrieval_candidates
    keyword_count = keyword_candidates or settings.keyword_candidates
    errors: List[str] = []
    result_lists: List[List[SearchHit]] = []
    vector_used = False

    try:
        with (trace.stage("embedding") if trace else _nullcontext()):
            if trace:
                trace.add_embedding_text(query)
            embedding = await get_embedding_provider().embed_query(query)
        with (trace.stage("retrieval") if trace else _nullcontext()):
            vector_hits = await vector_search(
                db, user_id, embedding, top_k=candidate_count, document_ids=document_ids
            )
        for hit in vector_hits:
            hit.vector_score = hit.score
        result_lists.append(vector_hits)
        vector_used = True
    except ProviderError as exc:
        logger.warning("Embedding provider unavailable: %s", exc)
        errors.append("Semantic search is temporarily unavailable (embedding provider error).")

    try:
        with (trace.stage("keyword_search") if trace else _nullcontext()):
            keyword_hits = await keyword_search(
                db, user_id, query, top_k=keyword_count, document_ids=document_ids
            )
        for hit in keyword_hits:
            hit.keyword_score = hit.score
        result_lists.append(keyword_hits)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Keyword search failed: %s", exc)
        errors.append("Keyword search failed for this query.")
        keyword_hits = []

    if not result_lists:
        return HybridSearchResult(hits=[], vector_used=False, keyword_used=False, errors=errors)

    with (trace.stage("fusion") if trace else _nullcontext()):
        fused = reciprocal_rank_fusion(result_lists, k=settings.rrf_k)
    return HybridSearchResult(
        hits=fused[: max(top_k, candidate_count)],
        vector_used=vector_used,
        keyword_used=bool(keyword_hits),
        errors=errors,
    )


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *args) -> bool:
        return False
