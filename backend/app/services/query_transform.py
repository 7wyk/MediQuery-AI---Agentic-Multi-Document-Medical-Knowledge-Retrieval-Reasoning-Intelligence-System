"""Query rewriting, multi-query generation and medical abbreviation expansion.

The LLM rewrite is best-effort: a structured-output failure never stops the RAG
pipeline. When the model cannot produce a valid transformation, deterministic
multi-aspect queries derived from the question are used instead so that every
part of a multi-part question is still searched for.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.config import get_settings
from app.providers.base import LLMResult, ProviderError
from app.providers.llm import parse_json_object
from app.providers.registry import get_llm_provider
from app.services.observability import RequestTrace

logger = logging.getLogger(__name__)

MAX_ASPECTS = 4
MAX_QUERY_LENGTH = 400

_TRANSFORM_PROMPT = """You optimise search queries for a medical document retrieval system.

Task: rewrite the user's question into retrieval queries for a search engine that
matches against medical guideline documents. Never answer the question, never give
medical advice, never invent patient facts.

Return ONE JSON object with exactly these fields and no others:
{{
  "rewritten": "string, required, 3-400 characters: a self-contained restatement of the question",
  "subqueries": ["string", ...],   // 0-{max_subqueries} alternative queries, one per distinct part of the question
  "expanded_terms": ["string", ...] // 0-10 clinical synonyms or abbreviation expansions
}}

Rules:
- Output valid JSON only: no markdown fences, no commentary, no trailing text.
- "rewritten" is mandatory and must never be empty or a refusal.
- Empty arrays are allowed for "subqueries" and "expanded_terms".
- If the question has several parts (for example a definition and a cause), create
  one subquery per part so each part can be retrieved independently.
- Expand medical abbreviations (e.g. "HTN" -> "hypertension", "BP" -> "blood pressure").
- Do not add fields such as "answer", "reasoning" or "confidence".

User question: {question}"""

_JSON_SYSTEM_PROMPT = (
    "You are a query-rewriting component. You return a single valid JSON object and "
    "nothing else. No markdown fences, no explanations outside the JSON."
)

_CLAUSE_SPLIT = re.compile(r"(?<=[?;])\s+")
_CONJUNCTION_SPLIT = re.compile(
    r"\s+(?:and|also|plus)\s+(?=(?:what|how|why|when|where|which|who|does|do|is|are|"
    r"can|should|could|would|will|tell|list|explain)\b)",
    re.IGNORECASE,
)

# Intent -> trigger phrases -> generic clinical search terms. These only extend the
# *search query*; they never add facts to the answer and are provider-independent.
_INTENT_RULES: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    (
        "definition",
        ("what is", "what are", "define", "definition", "meaning", "overview", "describe"),
        ("definition", "classification", "overview"),
    ),
    (
        "causes",
        (
            "cause", "causes", "caused", "etiology", "aetiology", "why", "risk factor",
            "risk factors", "contribut", "predispos",
        ),
        ("causes", "risk factors", "etiology", "contributing factors"),
    ),
    (
        "symptoms",
        ("symptom", "signs", "presentation", "manifest", "feel"),
        ("symptoms", "clinical signs", "presentation"),
    ),
    (
        "diagnosis",
        ("diagnos", "criteria", "test", "measure", "detect", "screening"),
        ("diagnosis", "diagnostic criteria", "tests", "assessment"),
    ),
    (
        "treatment",
        ("treat", "management", "manage", "therapy", "drug", "medication", "dose", "dosage"),
        ("treatment", "management", "therapy", "guideline recommendations"),
    ),
    (
        "prevention",
        ("prevent", "prophyla", "lifestyle"),
        ("prevention", "lifestyle measures"),
    ),
    (
        "complications",
        ("complication", "prognosis", "outcome", "progression"),
        ("complications", "prognosis", "disease course"),
    ),
)


@dataclass
class QueryTransformResult:
    original: str
    rewritten: str
    subqueries: List[str] = field(default_factory=list)
    expanded_terms: List[str] = field(default_factory=list)
    aspects: List[str] = field(default_factory=list)
    used_llm: bool = False
    fallback_used: bool = False
    status: str = "disabled"  # llm | fallback | disabled
    error: Optional[str] = None
    llm_result: Optional[LLMResult] = None

    @property
    def search_queries(self) -> List[str]:
        queries = [self.rewritten, *self.subqueries]
        cleaned: List[str] = []
        seen: set[str] = set()
        for query in queries:
            value = re.sub(r"\s+", " ", str(query or "")).strip()
            if not value or value.lower() in seen:
                continue
            seen.add(value.lower())
            cleaned.append(value[:MAX_QUERY_LENGTH])
        return cleaned or [self.original]

    @property
    def changed(self) -> bool:
        return any(
            query.strip().lower() != self.original.strip().lower()
            for query in self.search_queries
        )


def clean_question(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip(" ?.;:")


def split_question_aspects(question: str) -> List[str]:
    """Split a question into its distinct parts, deterministically.

    "What is hypertension? What is the cause of it?" -> two aspects;
    "What is hypertension and what causes it?" -> two aspects.
    """
    text = re.sub(r"\s+", " ", (question or "")).strip()
    if not text:
        return []
    aspects: List[str] = []
    for clause in _CLAUSE_SPLIT.split(text):
        for piece in _CONJUNCTION_SPLIT.split(clause):
            cleaned = clean_question(piece)
            if len(cleaned) < 3:
                continue
            if cleaned.lower() not in {item.lower() for item in aspects}:
                aspects.append(cleaned)
    if not aspects:
        cleaned = clean_question(text)
        return [cleaned] if cleaned else []
    return aspects[:MAX_ASPECTS]


def intent_terms(aspect: str) -> Tuple[str, ...]:
    lowered = (aspect or "").lower()
    terms: List[str] = []
    for _, triggers, expansions in _INTENT_RULES:
        if any(trigger in lowered for trigger in triggers):
            for expansion in expansions:
                if expansion not in terms:
                    terms.append(expansion)
    return tuple(terms)


def _enrich(aspect: str) -> str:
    terms = intent_terms(aspect)
    if not terms:
        return clean_question(aspect)
    return clean_question(f"{aspect} {' '.join(terms)}")


def build_fallback_queries(
    question: str, *, broaden: bool = False, limit: int = 4
) -> List[str]:
    """Deterministic aspect/intent queries used when rewriting is unavailable."""
    queries: List[str] = []

    def add(value: str) -> None:
        cleaned = clean_question(value)[:MAX_QUERY_LENGTH]
        if cleaned and cleaned.lower() not in {item.lower() for item in queries}:
            queries.append(cleaned)

    add(question)
    aspects = split_question_aspects(question)
    for aspect in aspects:
        add(_enrich(aspect))
    if broaden:
        merged: List[str] = []
        for aspect in aspects:
            for term in intent_terms(aspect):
                if term not in merged:
                    merged.append(term)
        if merged:
            add(f"{question} {' '.join(merged)}")
        add(f"{question} clinical guideline overview")
    return queries[:limit]


def _covered(aspect: str, queries: Sequence[str]) -> bool:
    aspect_terms = set(_words(aspect))
    if not aspect_terms:
        return True
    for query in queries:
        query_terms = set(_words(query))
        if aspect_terms and len(aspect_terms & query_terms) / len(aspect_terms) >= 0.6:
            return True
    return False


def _words(value: str) -> List[str]:
    return re.findall(r"[a-z0-9][a-z0-9\-]{1,}", (value or "").lower())


def _validate_payload(
    payload: object, max_subqueries: int
) -> Tuple[str, List[str], List[str]]:
    """Validate the model's JSON against the documented schema.

    Raises ``ValueError`` with a diagnostic reason instead of accepting partial or
    wrongly typed structured output.
    """
    if not isinstance(payload, dict):
        raise ValueError("transformation payload was not a JSON object")

    raw_rewritten = payload.get("rewritten")
    if not isinstance(raw_rewritten, str):
        raise ValueError("transformation payload is missing the required 'rewritten' string")
    rewritten = clean_question(raw_rewritten)[:MAX_QUERY_LENGTH]
    if len(rewritten) < 3:
        raise ValueError("transformation payload contained an empty 'rewritten' value")

    raw_subqueries = payload.get("subqueries", [])
    if raw_subqueries is None:
        raw_subqueries = []
    if not isinstance(raw_subqueries, list):
        raise ValueError("transformation payload 'subqueries' was not an array")
    subqueries = [
        clean_question(item)[:300]
        for item in raw_subqueries
        if isinstance(item, str) and len(clean_question(item)) >= 3
    ][:max_subqueries]

    raw_terms = payload.get("expanded_terms", [])
    if raw_terms is None:
        raw_terms = []
    if not isinstance(raw_terms, list):
        raise ValueError("transformation payload 'expanded_terms' was not an array")
    expanded = [
        clean_question(item)[:80]
        for item in raw_terms
        if isinstance(item, str) and clean_question(item)
    ][:10]

    return rewritten, subqueries, expanded


def _merge_aspects(
    result: QueryTransformResult, max_subqueries: int
) -> None:
    """Guarantee every question aspect is represented in the search queries."""
    if result.status != "llm":
        return
    existing = list(result.search_queries)
    for aspect in result.aspects:
        if _covered(aspect, existing):
            continue
        if len(result.subqueries) >= max_subqueries:
            break
        enriched = _enrich(aspect)
        if enriched.lower() in {item.lower() for item in existing}:
            continue
        result.subqueries.append(enriched[:300])
        existing.append(enriched)


async def transform_query(
    question: str, *, trace: Optional[RequestTrace] = None, retry_hint: Optional[str] = None
) -> QueryTransformResult:
    settings = get_settings()
    result = QueryTransformResult(
        original=question,
        rewritten=clean_question(question) or question,
        aspects=split_question_aspects(question),
    )
    if not settings.enable_query_transform:
        logger.info("Query transformation disabled by configuration")
        if trace:
            trace.mark_skipped("transform")
        return result

    prompt = _TRANSFORM_PROMPT.format(
        max_subqueries=settings.max_subqueries, question=question
    )
    if retry_hint:
        prompt += (
            "\n\nPrevious retrieval was graded insufficient. Focus the queries on: "
            + retry_hint[:300]
        )

    try:
        provider = get_llm_provider()
        with (trace.stage("transform") if trace else _nullcontext()):
            llm_result = await provider.complete(
                [
                    {"role": "system", "content": _JSON_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=settings.llm_json_max_tokens,
                json_mode=True,
            )
        if trace:
            trace.add_llm_usage(llm_result)
        payload = parse_json_object(llm_result.text)
        rewritten, subqueries, expanded = _validate_payload(
            payload, settings.max_subqueries
        )
    except (ProviderError, ValueError) as exc:
        reason = str(exc)[:300]
        logger.warning(
            "Query transformation failed (%s); using deterministic multi-aspect queries: %s",
            type(exc).__name__,
            reason,
        )
        result.status = "fallback"
        result.fallback_used = True
        result.error = "Query rewriting was unavailable; deterministic multi-aspect queries were used."
        result.subqueries = [
            query
            for query in build_fallback_queries(question)[1 : 1 + settings.max_subqueries]
        ]
        result.subqueries = [
            query for query in result.subqueries if query.lower() != clean_question(question).lower()
        ]
        if trace:
            trace.add_error(f"Query transformation failed: {reason}")
            trace.set_diagnostics(
                query_transform_status="fallback", query_transform_error=reason
            )
        return result

    result.rewritten = rewritten
    result.subqueries = subqueries
    result.expanded_terms = expanded
    result.used_llm = True
    result.status = "llm"
    _merge_aspects(result, settings.max_subqueries)
    if trace:
        trace.set_diagnostics(
            query_transform_status="llm",
            transformed_query=result.rewritten,
            query_transform_error=None,
        )
    logger.info(
        "Query transformed status=llm rewritten=%r subqueries=%s aspects=%s",
        result.rewritten,
        result.subqueries,
        result.aspects,
    )
    return result


async def refine_queries(
    previous: QueryTransformResult,
    question: str,
    *,
    trace: Optional[RequestTrace] = None,
    retry_hint: Optional[str] = None,
) -> QueryTransformResult:
    """Produce a *different* query set for the corrective retry.

    If the LLM rewrite fails again (or returns the same queries), deterministic
    broadened queries are used so attempt 2 is never an identical search.
    """
    settings = get_settings()
    refined = await transform_query(question, trace=trace, retry_hint=retry_hint)
    previous_queries = {query.lower() for query in previous.search_queries}
    new_queries = {query.lower() for query in refined.search_queries} - previous_queries
    if new_queries:
        logger.info("Refined queries differ from the previous attempt: %s", sorted(new_queries))
        return refined

    fallback = build_fallback_queries(question, broaden=True)
    distinct = [query for query in fallback if query.lower() not in previous_queries]
    if not distinct:
        distinct = [f"{question} clinical guideline overview"]
    refined.subqueries = distinct[: max(settings.max_subqueries, 1)]
    refined.fallback_used = True
    refined.status = "fallback"
    if not refined.error:
        refined.error = "Query rewriting returned unchanged queries; deterministic broadened queries were used."
    if trace:
        trace.add_error("Query refinement did not change the queries; deterministic expansion applied.")
        trace.set_diagnostics(
            query_transform_status="fallback", query_transform_error=refined.error
        )
    logger.info("Refinement replaced unchanged queries with: %s", refined.subqueries)
    return refined


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *args) -> bool:
        return False
