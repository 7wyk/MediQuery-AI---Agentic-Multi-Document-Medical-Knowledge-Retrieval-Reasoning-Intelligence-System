"""Self-correcting (CRAG + Self-RAG) medical RAG orchestration.

Pipeline per request:
  query validation (route) -> query rewriting/multi-query (with a deterministic
  fallback) -> hybrid retrieval -> reranking -> aspect-aware evidence grading
  -> corrective retry with genuinely different queries -> optional trusted web
  fallback -> grounded generation with numbered citations (partial answers are
  allowed and labelled) -> claim-level verification -> bounded regeneration ->
  abstention.

All retries are bounded by configuration and every stage is traced.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas.chat import AgentMetadata, ClaimVerification, SourceCitation
from app.providers.base import ProviderError
from app.providers.llm import parse_json_object
from app.providers.registry import get_llm_provider, get_rerank_provider
from app.services.graph_rag import graph_evidence_hits, retrieve_graph_context
from app.services.observability import RequestTrace
from app.services.query_transform import (
    QueryTransformResult,
    clean_question,
    refine_queries,
    transform_query,
)
from app.services.retrieval import (
    SearchHit,
    deduplicate,
    hybrid_search,
    select_evidence,
)
from app.services.web_search import WebEvidence, search_medical_web

logger = logging.getLogger(__name__)

ABSTAIN_ANSWER = "Sorry, I don't know."
INSUFFICIENT_ANSWER = (
    "I couldn't find enough evidence in your uploaded documents to answer this "
    "question reliably. Sorry, I don't know."
)
UNVERIFIED_NOTE = (
    "\n\n_Note: automated claim verification was unavailable for this answer. "
    "Please check the cited sources before relying on it._"
)
MAX_GENERATION_ATTEMPTS = 2

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{2,}", re.IGNORECASE)
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "have",
    "has", "had", "not", "but", "you", "your", "what", "which", "who", "how", "why",
    "when", "where", "does", "did", "can", "could", "should", "would", "about", "into",
    "than", "then", "there", "their", "they", "its", "of", "in", "on", "to", "is", "it",
}


@dataclass
class EvidenceItem:
    kind: str  # document | web
    content: str
    citation: SourceCitation


@dataclass
class EvidenceGrade:
    """Outcome of evidence grading, derived from the retrieved passages."""

    outcome: str  # sufficient | partial | insufficient
    score: float
    coverage: float
    reason: str
    supported_aspects: List[str] = field(default_factory=list)
    missing_aspects: List[str] = field(default_factory=list)
    source: str = "model"  # model | heuristic | retrieval | web

    @property
    def sufficient(self) -> bool:
        return self.outcome in {"sufficient", "partial"}


@dataclass
class RagResult:
    answer: str
    sources: List[SourceCitation]
    evidence_status: str
    insufficient: bool
    metadata: AgentMetadata
    mode: str = "agentic"
    web_search_used: bool = False


def _tokens(value: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(value or "") if t.lower() not in _STOPWORDS]


def lexical_overlap(question: str, text: str) -> float:
    question_tokens = set(_tokens(question))
    if not question_tokens:
        return 0.0
    text_tokens = set(_tokens(text))
    return len(question_tokens & text_tokens) / len(question_tokens)


def _jaccard(a: str, b: str) -> float:
    left, right = set(_tokens(a)), set(_tokens(b))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _unit_float(value: object) -> Optional[float]:
    """Coerce a model-supplied number into 0..1, or None when unusable."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return max(0.0, min(1.0, number))


def _nullcontext():
    class _Ctx:
        def __enter__(self):
            return None

        def __exit__(self, *args) -> bool:
            return False

    return _Ctx()


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------


async def _rerank_hits(
    question: str, hits: Sequence[SearchHit], trace: RequestTrace
) -> List[SearchHit]:
    settings = get_settings()
    if not hits:
        return []
    provider = get_rerank_provider()
    trace.reranker = provider.name
    documents = [hit.content[:2000] for hit in hits]
    trace.rerank_documents += len(documents)
    try:
        with trace.stage("rerank"):
            rankings = await provider.rerank(
                question,
                documents,
                top_n=min(
                    len(documents),
                    max(settings.rerank_top_n, settings.retrieval_top_k * 2),
                ),
            )
    except ProviderError as exc:
        logger.warning("Reranker unavailable, using fused rank order: %s", exc)
        trace.add_error("Reranking was unavailable; fused retrieval order was used.")
        for hit in hits:
            hit.rerank_score = hit.score
        return list(hits)

    ranked: List[SearchHit] = []
    for ranking in rankings:
        if 0 <= ranking.index < len(hits):
            hit = hits[ranking.index]
            hit.rerank_score = float(ranking.score)
            ranked.append(hit)
    ranked.sort(key=lambda hit: hit.rerank_score or 0.0, reverse=True)

    if provider.name not in {"lexical", "none"}:
        filtered = [
            hit
            for hit in ranked
            if (hit.rerank_score or 0.0) >= settings.min_rerank_score
        ]
        if filtered:
            return filtered
        return ranked[:1]
    return ranked


async def _rerank_web(
    question: str, items: Sequence[WebEvidence], trace: RequestTrace
) -> List[Tuple[WebEvidence, float]]:
    if not items:
        return []
    provider = get_rerank_provider()
    texts = [f"{item.title}. {item.content}"[:2000] for item in items]
    try:
        rankings = await provider.rerank(
            question, texts, top_n=min(len(texts), len(items))
        )
        scored = [
            (items[ranking.index], float(ranking.score))
            for ranking in rankings
            if 0 <= ranking.index < len(items)
        ]
    except ProviderError as exc:
        logger.warning("Web reranking failed: %s", exc)
        scored = [(item, lexical_overlap(question, f"{item.title} {item.content}")) for item in items]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    threshold = 0.05 if provider.name in {"lexical", "none"} else 0.15
    return [pair for pair in scored if pair[1] >= threshold]


# ---------------------------------------------------------------------------
# Evidence grading
# ---------------------------------------------------------------------------


def _max_score(hits: Sequence[SearchHit]) -> float:
    return max(
        ((hit.rerank_score if hit.rerank_score is not None else hit.score) for hit in hits),
        default=0.0,
    )


def _best_aspect_overlap(aspect: str, hits: Sequence[SearchHit]) -> float:
    terms = set(_tokens(aspect))
    if not terms:
        return 0.0
    best = 0.0
    for hit in hits:
        overlap = len(terms & set(_tokens(hit.content))) / len(terms)
        best = max(best, overlap)
    return best


def _aspect_lexical_coverage(
    aspects: Sequence[str], hits: Sequence[SearchHit], *, threshold: float = 0.34
) -> Tuple[float, List[str], List[str]]:
    if not aspects:
        return 0.0, [], []
    supported = [a for a in aspects if _best_aspect_overlap(a, hits) >= threshold]
    missing = [a for a in aspects if a not in supported]
    return len(supported) / len(aspects), supported, missing


def _interpret_grade(
    payload: dict,
    aspects: Sequence[str],
    hits: Sequence[SearchHit],
    settings,
) -> EvidenceGrade:
    """Turn the grader's JSON into a decision that is actually derived from passages."""
    supported: List[str] = []
    missing: List[str] = []
    raw_aspects = payload.get("aspects")
    if isinstance(raw_aspects, list):
        for item in raw_aspects:
            if not isinstance(item, dict):
                continue
            text = str(item.get("aspect") or "").strip()[:200]
            if not text:
                continue
            if bool(item.get("supported")):
                supported.append(text)
            else:
                missing.append(text)

    model_coverage = _unit_float(payload.get("coverage"))
    direct_support = bool(payload.get("direct_support", bool(supported)))
    threshold = float(settings.evidence_min_coverage)
    if supported or missing:
        # A concrete per-aspect breakdown beats a self-reported summary number.
        coverage = len(supported) / (len(supported) + len(missing))
    elif direct_support and model_coverage is not None:
        # Grader omitted the per-aspect breakdown; trust its summary only when it
        # also claims direct support.
        coverage = model_coverage
        if model_coverage >= threshold:
            supported = list(aspects[:1]) or ["question"]
    else:
        coverage = model_coverage if model_coverage is not None else 0.0
    model_score = _unit_float(payload.get("score"))
    best = _max_score(hits)
    score = (
        model_score
        if model_score is not None
        else round(0.7 * coverage + 0.3 * min(1.0, max(best, 0.0)), 4)
    )
    reason = str(payload.get("reason") or "").strip()[:300] or (
        f"{len(supported)} of {max(1, len(supported) + len(missing))} question aspects have direct support."
    )

    if not direct_support or not supported:
        outcome = "insufficient"
    elif coverage >= 0.999:
        outcome = "sufficient"
    elif coverage >= threshold:
        outcome = "partial"
    else:
        outcome = "insufficient"

    if outcome != "insufficient" and coverage < 0.999 and best < settings.min_rerank_score:
        # Nothing retrieval found was relevant enough to justify answering.
        outcome = "insufficient"
        reason = reason or "The retrieved passages have very low relevance to the question."

    return EvidenceGrade(
        outcome=outcome,
        score=round(score, 4),
        coverage=round(coverage, 4),
        reason=reason,
        supported_aspects=supported,
        missing_aspects=missing,
        source="model",
    )


def _heuristic_grade(
    aspects: Sequence[str], hits: Sequence[SearchHit], settings
) -> EvidenceGrade:
    best = _max_score(hits)
    coverage, supported, missing = _aspect_lexical_coverage(aspects, hits)
    score = round(0.6 * coverage + 0.4 * min(1.0, max(best, 0.0)), 4)
    threshold = float(settings.evidence_min_coverage)
    if not hits or (best <= 0.0 and coverage <= 0.0):
        outcome = "insufficient"
    elif coverage >= 0.999:
        outcome = "sufficient"
    elif coverage >= threshold:
        outcome = "partial"
    else:
        outcome = "insufficient"
    return EvidenceGrade(
        outcome=outcome,
        score=score,
        coverage=round(coverage, 4),
        reason=(
            "Evidence grading was unavailable; retrieval scores and lexical aspect "
            "coverage were used instead."
        ),
        supported_aspects=supported,
        missing_aspects=missing,
        source="heuristic",
    )


async def _grade_evidence(
    question: str,
    aspects: Sequence[str],
    hits: Sequence[SearchHit],
    trace: RequestTrace,
) -> EvidenceGrade:
    settings = get_settings()
    aspects = [a for a in aspects if a.strip()] or [question]
    if not hits:
        return EvidenceGrade(
            outcome="insufficient",
            score=0.0,
            coverage=0.0,
            reason="No relevant passages were retrieved.",
            missing_aspects=list(aspects),
            source="retrieval",
        )

    evidence_block = "\n\n".join(
        f"[{index}] {hit.content[:1100]}" for index, hit in enumerate(hits[:8], start=1)
    )
    aspect_block = "\n".join(f"- {aspect}" for aspect in aspects[:4])
    prompt = (
        "You grade retrieval quality for a medical question-answering system.\n"
        "Split the question into its distinct parts (aspects) and decide, for each aspect, "
        "whether the retrieved passages contain information that directly answers it. "
        "Do not answer the question and do not use outside knowledge.\n\n"
        "Return ONE JSON object with exactly these fields:\n"
        '{"aspects": [{"aspect": "string", "supported": true|false, "evidence": [1,2]}],\n'
        ' "coverage": 0.0-1.0, "direct_support": true|false, "score": 0.0-1.0,\n'
        ' "reason": "<=30 words"}\n\n'
        "Rules: one entry per question aspect; 'supported' is true only when a listed "
        "passage explicitly answers that aspect; 'evidence' contains passage numbers; "
        "'coverage' is the fraction of aspects with direct support; JSON only, no fences.\n\n"
        f"Question: {question}\n\nQuestion aspects:\n{aspect_block}\n\n"
        f"Retrieved passages:\n{evidence_block}"
    )
    try:
        with trace.stage("grading"):
            result = await get_llm_provider().complete(
                [
                    {
                        "role": "system",
                        "content": (
                            "You are an evidence grader. You return a single valid JSON "
                            "object and nothing else."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=settings.llm_json_max_tokens,
                json_mode=True,
            )
        trace.add_llm_usage(result)
        payload = parse_json_object(result.text)
        grade = _interpret_grade(payload, aspects, hits, settings)
        logger.info(
            "Evidence graded outcome=%s coverage=%.2f score=%.2f source=model reason=%r",
            grade.outcome,
            grade.coverage,
            grade.score,
            grade.reason,
        )
        return grade
    except (ProviderError, ValueError) as exc:
        logger.warning(
            "Evidence grading failed (%s); falling back to retrieval-derived heuristic",
            exc,
        )
        trace.add_error("Evidence grading used a retrieval-derived heuristic fallback.")
        grade = _heuristic_grade(aspects, hits, settings)
        logger.info(
            "Evidence graded outcome=%s coverage=%.2f score=%.2f source=heuristic",
            grade.outcome,
            grade.coverage,
            grade.score,
        )
        return grade


# ---------------------------------------------------------------------------
# Generation and verification
# ---------------------------------------------------------------------------


def _format_evidence(items: Sequence[EvidenceItem]) -> str:
    parts = []
    for item in items:
        citation = item.citation
        if item.kind == "web":
            label = (
                f"[{citation.index}] EXTERNAL SOURCE: {citation.title} — "
                f"{citation.publisher} ({citation.url})"
            )
        else:
            label = (
                f"[{citation.index}] UPLOADED DOCUMENT: {citation.filename}"
                f", page {citation.page if citation.page is not None else 'n/a'}"
            )
            if citation.content_type and citation.content_type != "text":
                label += f", {citation.content_type}"
            if citation.table_id:
                label += f" ({citation.table_id})"
        parts.append(f"{label}\n{item.content[:1800]}")
    return "\n\n".join(parts)


def _generation_messages(
    question: str,
    items: Sequence[EvidenceItem],
    graph_facts: Sequence[str],
    *,
    missing_aspects: Sequence[str] = (),
    partial: bool = False,
) -> List[dict]:
    graph_section = ""
    if graph_facts:
        graph_section = (
            "\n\nKnowledge-graph relationships derived from the user's uploaded documents "
            "(supporting context only, not independent evidence):\n- "
            + "\n- ".join(graph_facts[:20])
        )
    system = (
        "You are MediQuery AI, an assistant for medical professionals. Answer only from the "
        "numbered EVIDENCE provided. Rules:\n"
        "- Answer the question that was asked, including every part of a multi-part question. "
        "Use short headings or bullet points when there are several parts.\n"
        "- Cite supporting evidence inline with its number, e.g. [1] or [2][3].\n"
        "- Evidence labelled EXTERNAL SOURCE is not from the user's documents; say so when "
        "you rely on it.\n"
        "- Never invent facts, numbers, causes, citations, page numbers or quotations.\n"
        "- Do not diagnose or prescribe; present information and note uncertainty.\n"
        "- If the evidence does not answer the question, reply exactly: Sorry, I don't know.\n"
        "- Be concise (max ~250 words) unless the question requires a comparison.\n"
    )
    if partial:
        system += (
            "- The evidence supports only part of this question. Answer the supported parts "
            "with citations and state plainly which parts the uploaded documents do not "
            "cover. Do not fill gaps with general medical knowledge and do not refuse the "
            "parts that are supported.\n"
        )
    if missing_aspects:
        system += (
            "- No direct evidence was found for these parts: "
            + "; ".join(str(a)[:120] for a in missing_aspects[:3])
            + ". Say the uploaded documents do not provide enough information about them.\n"
        )
    user = (
        f"Question: {question}\n\nEVIDENCE:\n{_format_evidence(items)}{graph_section}\n\n"
        "Answer the question using only this evidence, with inline citations."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def _verify_answer(
    question: str,
    answer: str,
    items: Sequence[EvidenceItem],
    trace: RequestTrace,
) -> Optional[dict]:
    settings = get_settings()
    prompt = (
        "You verify medical answers against evidence. Split the ANSWER into atomic factual "
        "claims. For each claim list the evidence numbers that state it, and mark it "
        "supported only if an evidence item explicitly supports it. Also decide whether the "
        "answer actually addresses the question.\n\n"
        'Respond ONLY with JSON: {"addresses_question": true|false, "grounded": true|false, '
        '"claims": [{"claim": "...", "evidence": [1], "supported": true|false}]}\n\n'
        f"Question: {question}\n\nANSWER:\n{answer}\n\nEVIDENCE:\n{_format_evidence(items)}"
    )
    try:
        with trace.stage("verification"):
            result = await get_llm_provider().complete(
                [
                    {"role": "system", "content": "You output only valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=settings.llm_json_max_tokens,
                json_mode=True,
            )
        trace.add_llm_usage(result)
        payload = parse_json_object(result.text)
    except (ProviderError, ValueError) as exc:
        logger.warning("Claim verification unavailable: %s", exc)
        trace.add_error("Claim verification was unavailable.")
        return None

    raw_claims = payload.get("claims")
    claims: List[ClaimVerification] = []
    if isinstance(raw_claims, list):
        for item in raw_claims[:40]:
            if not isinstance(item, dict):
                continue
            indexes = item.get("evidence") or []
            if not isinstance(indexes, list):
                indexes = []
            valid_indexes = sorted(
                {
                    int(value)
                    for value in indexes
                    if isinstance(value, (int, float, str)) and str(value).isdigit()
                    and 1 <= int(value) <= len(items)
                }
            )
            claim_text = str(item.get("claim") or "").strip()
            if not claim_text:
                continue
            claims.append(
                ClaimVerification(
                    claim=claim_text[:800],
                    evidence_indexes=valid_indexes,
                    supported=bool(item.get("supported")),
                )
            )
    return {
        "addresses_question": bool(payload.get("addresses_question", True)),
        "grounded": bool(payload.get("grounded", False)),
        "claims": claims,
    }


def _strip_unsupported(
    answer: str, claims: Sequence[ClaimVerification]
) -> Tuple[str, List[ClaimVerification], int]:
    unsupported = [claim for claim in claims if not claim.supported]
    supported = [claim for claim in claims if claim.supported]
    if not unsupported:
        return answer, list(claims), 0

    sentences = re.split(r"(?<=[.!?])\s+", answer.strip())
    kept: List[str] = []
    removed = 0
    for sentence in sentences:
        if any(_jaccard(sentence, claim.claim) >= 0.45 for claim in unsupported):
            removed += 1
            continue
        kept.append(sentence)
    cleaned = " ".join(kept).strip()
    return cleaned, supported, removed


def _cited_indexes(answer: str, claim_list: Sequence[ClaimVerification]) -> set:
    indexes = {int(match) for match in re.findall(r"\[(\d+)\]", answer)}
    for claim in claim_list:
        indexes.update(claim.evidence_indexes)
    return indexes


def _citations_from_claims(
    answer: str, claims: Sequence[ClaimVerification], items: Sequence[EvidenceItem]
) -> set:
    """Citation indexes that really exist in the retrieved evidence.

    Only inline numbers and verification-supported claim mappings are used; the
    previous "attach the first three passages" fallback fabricated citations and is
    replaced by a deterministic claim -> passage mapping.
    """
    cited = _cited_indexes(answer, claims)
    valid = {index for index in cited if 1 <= index <= len(items)}
    if valid:
        return valid

    mapped: set = set()
    for claim in claims:
        if not claim.supported:
            continue
        best_index, best_score = None, 0.0
        for index, item in enumerate(items, start=1):
            score = _jaccard(claim.claim, item.content)
            if score > best_score:
                best_index, best_score = index, score
        if best_index is not None and best_score >= 0.25:
            mapped.add(best_index)
    return mapped


# ---------------------------------------------------------------------------
# Metadata and abstention
# ---------------------------------------------------------------------------


def _metadata(
    trace: RequestTrace,
    *,
    question: str,
    attempts: int,
    transform: QueryTransformResult,
    documents_retrieved: int,
    passages_retained: int,
    grade: EvidenceGrade,
    graph_used: bool,
    web_used: bool,
    evidence_status: str,
    steps: List[str],
    claims: Optional[Sequence[ClaimVerification]] = None,
    abstention_reason: Optional[str] = None,
    retrieval_improved: Optional[bool] = None,
    verification_status: str = "skipped",
    errors: Optional[List[str]] = None,
) -> AgentMetadata:
    settings = get_settings()
    return AgentMetadata(
        request_id=trace.request_id,
        original_question=question,
        transformed_query=transform.rewritten,
        query_transform_status=transform.status,
        query_transform_error=transform.error,
        retrieval_attempts=attempts,
        retrieval_refined=attempts > 1,
        retrieval_improved=retrieval_improved,
        documents_retrieved=documents_retrieved,
        passages_retained=passages_retained,
        relevance_score=round(grade.score, 3),
        evidence_coverage=round(grade.coverage, 3),
        evidence_threshold=settings.evidence_min_coverage,
        evidence_outcome=grade.outcome,
        abstention_reason=abstention_reason,
        verification_status=verification_status,
        steps=steps,
        subqueries=transform.search_queries,
        evidence_status=evidence_status,
        web_search_used=web_used,
        web_search_enabled=settings.web_search_enabled,
        graph_rag_used=graph_used,
        claims=list(claims or []),
        latency_ms=trace.latency_breakdown(),
        token_usage={
            "prompt": trace.prompt_tokens,
            "completion": trace.completion_tokens,
            "total": trace.total_tokens,
        },
        estimated_cost_usd=trace.estimated_cost_usd(),
        reranker=trace.reranker,
        errors=errors if errors is not None else trace.errors,
    )


def _abstain(
    trace: RequestTrace,
    *,
    question: str,
    attempts: int,
    steps: List[str],
    grade: EvidenceGrade,
    transform: QueryTransformResult,
    web_used: bool,
    graph_used: bool,
    documents_retrieved: int,
    passages_retained: int,
    abstention_reason: str,
    retrieval_improved: Optional[bool] = None,
    verification_status: str = "skipped",
    answer: str = INSUFFICIENT_ANSWER,
) -> RagResult:
    metadata = _metadata(
        trace,
        question=question,
        attempts=attempts,
        transform=transform,
        documents_retrieved=documents_retrieved,
        passages_retained=passages_retained,
        grade=grade,
        graph_used=graph_used,
        web_used=web_used,
        evidence_status="insufficient",
        steps=steps,
        abstention_reason=abstention_reason,
        retrieval_improved=retrieval_improved,
        verification_status=verification_status,
    )
    return RagResult(
        answer=answer,
        sources=[],
        evidence_status="insufficient",
        insufficient=True,
        metadata=metadata,
        web_search_used=web_used,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_rag(
    db: Session,
    *,
    user_id: int,
    question: str,
    document_ids: Optional[List[str]] = None,
    allow_web_search: Optional[bool] = None,
    mode: str = "agentic",
    trace: Optional[RequestTrace] = None,
) -> RagResult:
    settings = get_settings()
    trace = trace or RequestTrace(user_id=user_id)
    trace.user_id = user_id
    steps: List[str] = ["Question accepted for medical retrieval"]

    transform = await transform_query(question, trace=trace)
    aspects = [aspect for aspect in transform.aspects if aspect.strip()] or [
        clean_question(question) or question
    ]
    if transform.status == "llm":
        steps.append("Query rewritten and expanded for retrieval")
    elif transform.status == "fallback":
        steps.append(
            "Query transformation unavailable; deterministic multi-aspect queries used"
        )
    else:
        steps.append("Query rewriting disabled; original question used")
    if transform.error:
        trace.add_error(transform.error)

    graph_context = retrieve_graph_context(db, user_id, question)
    if graph_context.used:
        steps.append(
            f"Knowledge graph matched {len(graph_context.entity_names)} related entities"
        )

    web_allowed = (
        settings.web_search_enabled
        if allow_web_search is None
        else bool(allow_web_search and settings.web_search_enabled)
    )
    attempts_allowed = max(1, settings.agent_max_attempts if mode != "standard" else 1)
    accumulated: Dict[str, SearchHit] = {}
    selected: List[SearchHit] = []
    grade = EvidenceGrade(
        outcome="insufficient",
        score=0.0,
        coverage=0.0,
        reason="No evidence has been graded yet.",
        missing_aspects=list(aspects),
        source="retrieval",
    )
    previous_grade: Optional[EvidenceGrade] = None
    retrieval_improved: Optional[bool] = None
    attempts_used = 0
    web_used = False
    web_items: List[Tuple[WebEvidence, float]] = []

    for attempt in range(1, attempts_allowed + 1):
        attempts_used = attempt
        queries = list(transform.search_queries)
        if transform.expanded_terms and attempt > 1:
            queries.append(" ".join(transform.expanded_terms))
        queries = list(
            dict.fromkeys(query for query in queries if query.strip())
        )[: 1 + settings.max_subqueries]

        attempt_hits: List[SearchHit] = []
        for query in queries:
            result = await hybrid_search(
                db,
                user_id,
                query,
                top_k=settings.retrieval_candidates,
                document_ids=document_ids,
                trace=trace,
            )
            for message in result.errors:
                trace.add_error(message)
            attempt_hits.extend(result.hits)

        if graph_context.used and graph_context.entity_names:
            attempt_hits.extend(
                graph_evidence_hits(db, user_id, graph_context.entity_names, limit=8)
            )

        for hit in deduplicate(attempt_hits):
            accumulated.setdefault(hit.chunk_id, hit)

        steps.append(
            f"Retrieved {len(accumulated)} unique passages (attempt {attempt})"
        )
        if not accumulated:
            grade = EvidenceGrade(
                outcome="insufficient",
                score=0.0,
                coverage=0.0,
                reason="No matching passages were found in the uploaded documents.",
                missing_aspects=list(aspects),
                source="retrieval",
            )
            steps.append("No relevant passages found")
            if attempt < attempts_allowed:
                transform = await refine_queries(
                    transform,
                    question,
                    trace=trace,
                    retry_hint="No passages matched; broaden the clinical terms.",
                )
                steps.append("Query refined and retrieval retried")
            continue

        candidates = deduplicate(list(accumulated.values()))
        candidates = candidates[: max(settings.retrieval_candidates * 2, 40)]
        reranked = await _rerank_hits(question, candidates, trace)
        selected = select_evidence(reranked, aspects, settings.retrieval_top_k)
        steps.append(
            f"Reranked {len(reranked)} candidates and retained {len(selected)} passages"
        )

        previous_grade = grade if attempt > 1 else None
        grade = await _grade_evidence(question, aspects, selected, trace)
        steps.append(
            f"Evidence graded: {grade.outcome} "
            f"(coverage {grade.coverage:.2f}, score {grade.score:.2f})"
        )
        if previous_grade is not None:
            retrieval_improved = bool(
                grade.coverage > previous_grade.coverage
                or grade.score > previous_grade.score
            )
            steps.append(
                "Retry improved retrieval"
                if retrieval_improved
                else "Retry did not improve retrieval"
            )
        trace.set_diagnostics(
            evidence_outcome=grade.outcome,
            evidence_coverage=grade.coverage,
            evidence_score=grade.score,
            evidence_threshold=settings.evidence_min_coverage,
            evidence_grade_source=grade.source,
            evidence_missing_aspects=grade.missing_aspects,
            passages_retained=len(selected),
        )

        if grade.outcome != "insufficient":
            break
        if attempt < attempts_allowed:
            transform = await refine_queries(
                transform, question, trace=trace, retry_hint=grade.reason
            )
            aspects = [
                aspect for aspect in transform.aspects if aspect.strip()
            ] or aspects
            steps.append("Query refined and retrieval retried")

    # External evidence is only consulted after document evidence proved insufficient.
    if grade.outcome == "insufficient" and web_allowed:
        with (trace.stage("web_search") if trace else _nullcontext()):
            web_candidates = await search_medical_web(question, trace=trace)
        if web_candidates:
            web_items = await _rerank_web(question, web_candidates, trace)
        if web_items:
            web_used = True
            grade = EvidenceGrade(
                outcome="sufficient",
                score=max(grade.score, 0.0),
                coverage=1.0,
                reason="Document evidence was insufficient; trusted external sources were used.",
                supported_aspects=list(aspects),
                missing_aspects=[],
                source="web",
            )
            steps.append(
                f"Consulted {len(web_items)} trusted external medical source(s); "
                "they are labelled separately"
            )
        else:
            steps.append("External medical search returned no relevant results")

    if grade.outcome == "insufficient" or (not selected and not web_items):
        reason = grade.reason or "The retrieved passages did not support the question."
        steps.append(f"Insufficient evidence ({reason}); abstaining")
        trace.set_diagnostics(
            decision="abstain",
            abstention_reason=reason,
            retrieval_attempts=attempts_used,
        )
        trace.log_summary(
            answer_found=False,
            web_used=web_used,
            extra={
                "question": question,
                "query_transform_status": transform.status,
                "query_transform_error": transform.error,
                "retrieval_attempts": attempts_used,
                "passages_retrieved": len(accumulated),
                "passages_retained": len(selected),
                "evidence_outcome": grade.outcome,
                "evidence_coverage": grade.coverage,
                "evidence_score": grade.score,
                "evidence_grade_source": grade.source,
                "evidence_threshold": settings.evidence_min_coverage,
                "decision": "abstain",
                "abstention_reason": reason,
                "llm_provider": settings.llm_provider,
                "llm_model": settings.llm_model,
            },
        )
        return _abstain(
            trace,
            question=question,
            attempts=attempts_used,
            steps=steps,
            grade=grade,
            transform=transform,
            web_used=web_used,
            graph_used=graph_context.used,
            documents_retrieved=len(accumulated),
            passages_retained=len(selected),
            abstention_reason=reason,
            retrieval_improved=retrieval_improved,
        )

    items: List[EvidenceItem] = []
    for hit in selected:
        items.append(
            EvidenceItem(
                kind="document",
                content=hit.content,
                citation=hit.as_citation(len(items) + 1),
            )
        )
    for evidence, score in web_items:
        citation = evidence.as_citation(len(items) + 1)
        citation.score = round(score, 4)
        items.append(EvidenceItem(kind="web", content=evidence.content, citation=citation))

    partial = grade.outcome == "partial" and not web_items
    if partial:
        steps.append(
            "Answering the supported part(s) only; unsupported parts will be declared"
        )
    messages = _generation_messages(
        question,
        items,
        graph_context.facts,
        missing_aspects=grade.missing_aspects if partial else (),
        partial=partial,
    )
    answer = ""
    claims: List[ClaimVerification] = []
    evidence_status = "partial" if partial else "sufficient"
    verification_status = "skipped"
    verification_unavailable = False

    for generation_attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        try:
            with trace.stage("generation"):
                generated = await get_llm_provider().complete(
                    messages,
                    temperature=settings.llm_temperature,
                    max_tokens=settings.llm_max_tokens,
                )
            trace.add_llm_usage(generated)
            answer = generated.text.strip()
        except ProviderError as exc:
            logger.error("Answer generation failed: %s", exc)
            trace.add_error("The language model was unavailable while generating the answer.")
            return _abstain(
                trace,
                question=question,
                attempts=attempts_used,
                steps=steps + ["Generation failed"],
                grade=grade,
                transform=transform,
                web_used=web_used,
                graph_used=graph_context.used,
                documents_retrieved=len(accumulated),
                passages_retained=len(selected),
                abstention_reason="Answer generation failed.",
                retrieval_improved=retrieval_improved,
            )

        if not answer or answer.strip().strip(".").lower() in {
            "sorry, i don't know",
            "sorry i don't know",
            "i don't know",
        }:
            return _abstain(
                trace,
                question=question,
                attempts=attempts_used,
                steps=steps + ["Model reported that the evidence was insufficient"],
                grade=grade,
                transform=transform,
                web_used=web_used,
                graph_used=graph_context.used,
                documents_retrieved=len(accumulated),
                passages_retained=len(selected),
                abstention_reason="The model judged the retrieved evidence insufficient.",
                retrieval_improved=retrieval_improved,
            )

        if not settings.enable_claim_verification:
            verification_status = "disabled"
            trace.mark_skipped("verification")
            break

        verification = await _verify_answer(question, answer, items, trace)
        if verification is None:
            verification_unavailable = True
            verification_status = "unverified"
            evidence_status = "unverified" if evidence_status == "sufficient" else evidence_status
            break

        claims = verification["claims"]
        if not verification["addresses_question"] and generation_attempt < MAX_GENERATION_ATTEMPTS:
            messages = messages + [
                {"role": "assistant", "content": answer},
                {
                    "role": "user",
                    "content": (
                        "That answer did not directly address the question. Answer it "
                        "directly and concisely using only the numbered evidence, with citations."
                    ),
                },
            ]
            steps.append("Answer did not address the question; regenerating")
            continue

        answer, claims, removed = _strip_unsupported(answer, claims)
        verification_status = "verified"
        if removed:
            evidence_status = "partial"
            steps.append(f"Removed {removed} unsupported claim sentence(s)")
        if not answer or (claims and not any(claim.supported for claim in claims)):
            if generation_attempt < MAX_GENERATION_ATTEMPTS:
                messages = _generation_messages(
                    question,
                    items,
                    graph_context.facts,
                    missing_aspects=grade.missing_aspects if partial else (),
                    partial=partial,
                ) + [
                    {
                        "role": "user",
                        "content": (
                            "Your previous answer contained unsupported claims. Answer using "
                            "only statements the evidence explicitly supports, or reply "
                            "exactly: Sorry, I don't know."
                        ),
                    }
                ]
                steps.append("Unsupported answer rejected; regenerating")
                continue
            return _abstain(
                trace,
                question=question,
                attempts=attempts_used,
                steps=steps + ["No verifiable claims remained"],
                grade=grade,
                transform=transform,
                web_used=web_used,
                graph_used=graph_context.used,
                documents_retrieved=len(accumulated),
                passages_retained=len(selected),
                abstention_reason="No verifiable claims remained after grounding checks.",
                retrieval_improved=retrieval_improved,
            )
        break

    if not answer:
        return _abstain(
            trace,
            question=question,
            attempts=attempts_used,
            steps=steps,
            grade=grade,
            transform=transform,
            web_used=web_used,
            graph_used=graph_context.used,
            documents_retrieved=len(accumulated),
            passages_retained=len(selected),
            abstention_reason="No answer was produced from the retrieved evidence.",
            retrieval_improved=retrieval_improved,
        )

    if verification_unavailable:
        answer = answer + UNVERIFIED_NOTE

    valid_cited = _citations_from_claims(answer, claims, items)
    if not valid_cited:
        steps.append(
            "Citations could not be verified against the retrieved passages; "
            "no sources were attached"
        )
    sources = [items[index - 1].citation for index in sorted(valid_cited)]
    steps.append("Answer generated with citations" if sources else "Answer generated")
    if claims:
        supported_count = sum(1 for claim in claims if claim.supported)
        steps.append(f"Claim verification: {supported_count}/{len(claims)} claims supported")

    metadata = _metadata(
        trace,
        question=question,
        attempts=attempts_used,
        transform=transform,
        documents_retrieved=len(accumulated),
        passages_retained=len(selected),
        grade=grade,
        graph_used=graph_context.used,
        web_used=web_used,
        evidence_status=evidence_status,
        steps=steps,
        claims=claims,
        abstention_reason=None,
        retrieval_improved=retrieval_improved,
        verification_status=verification_status,
    )
    trace.set_diagnostics(
        decision="answer",
        evidence_outcome=grade.outcome,
        evidence_status=evidence_status,
        citations=len(sources),
        retrieval_attempts=attempts_used,
        query_transform_status=transform.status,
    )
    trace.log_summary(
        answer_found=True,
        web_used=web_used,
        extra={
            "question": question,
            "query_transform_status": transform.status,
            "query_transform_error": transform.error,
            "retrieval_attempts": attempts_used,
            "passages_retrieved": len(accumulated),
            "passages_retained": len(selected),
            "evidence_outcome": grade.outcome,
            "evidence_coverage": grade.coverage,
            "evidence_score": grade.score,
            "evidence_grade_source": grade.source,
            "evidence_threshold": settings.evidence_min_coverage,
            "evidence_status": evidence_status,
            "verification_status": verification_status,
            "decision": "answer",
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model,
        },
    )
    return RagResult(
        answer=answer,
        sources=sources,
        evidence_status=evidence_status,
        insufficient=False,
        metadata=metadata,
        mode=mode,
        web_search_used=web_used,
    )


def domain_rejection_result(question: str, reason: str, trace: RequestTrace) -> RagResult:
    """Response for a question rejected by the medical domain gatekeeper."""
    message = (
        "I can only answer questions about medicine, health and the medical documents you "
        "upload. " + (reason or "This question appears to be outside that domain.")
    )
    metadata = AgentMetadata(
        request_id=trace.request_id,
        original_question=question,
        retrieval_attempts=0,
        documents_retrieved=0,
        steps=["Question rejected by the medical domain gatekeeper"],
        evidence_status="rejected_domain",
        abstention_reason="Question rejected by the medical domain gatekeeper.",
        web_search_enabled=get_settings().web_search_enabled,
        latency_ms=trace.latency_breakdown(),
        token_usage={"prompt": 0, "completion": 0, "total": 0},
        errors=[],
    )
    trace.mark_skipped("transform")
    trace.mark_skipped("verification")
    return RagResult(
        answer=message,
        sources=[],
        evidence_status="rejected_domain",
        insufficient=True,
        metadata=metadata,
    )
