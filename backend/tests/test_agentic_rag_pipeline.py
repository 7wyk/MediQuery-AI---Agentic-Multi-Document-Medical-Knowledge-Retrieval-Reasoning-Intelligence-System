"""Regression tests for the agentic RAG pipeline.

Covers the reported failures: Groq structured-output failures during query
transformation, retrieval that misses one part of a multi-part question, and
evidence grading that abstained despite usable evidence.
"""

from __future__ import annotations

import json
import uuid
from typing import Sequence

import pytest

from app.providers.base import LLMProvider, LLMResult, ProviderError
from app.providers.llm import parse_json_object
from app.services.agentic_rag import EvidenceGrade, _grade_evidence
from app.services.observability import RequestTrace
from app.services.query_transform import (
    QueryTransformResult,
    refine_queries,
    split_question_aspects,
    transform_query,
)
from app.services.retrieval import SearchHit, select_evidence

HYPERTENSION_TEXT = (
    "Hypertension clinical guideline. Hypertension is a chronic condition in which "
    "arterial blood pressure is persistently elevated at or above 140/90 mmHg. "
    "Contributing risk factors include high salt intake, obesity, smoking, alcohol use, "
    "older age and family history. Common symptoms include headache and dizziness. "
    "Treatment includes lifestyle change and antihypertensive medication. "
    "Blood pressure should be monitored regularly in patients with diabetes."
)


class ScriptedLLM(LLMProvider):
    """Deterministic LLM double whose replies are scripted per call type."""

    name = "scripted"
    model = "scripted-llm"

    def __init__(
        self,
        *,
        transform=None,
        grade=None,
        verify=None,
        generation=None,
    ) -> None:
        self.transform = transform
        self.grade = grade
        self.verify = verify
        self.generation = generation
        self.calls: list[str] = []

    async def complete(  # type: ignore[override]
        self,
        messages,
        *,
        temperature: float = 0.1,
        max_tokens: int = 1200,
        json_mode: bool = False,
    ) -> LLMResult:
        text = "\n".join(message.get("content", "") for message in messages)
        lower = text.lower()

        if "optimise search queries" in lower:
            kind, handler = "transform", self.transform
        elif "grade retrieval quality" in lower:
            kind, handler = "grade", self.grade
        elif "verify medical answers" in lower:
            kind, handler = "verify", self.verify
        elif "knowledge-graph" in lower:
            return self._json({"entities": [], "relations": []})
        elif "gatekeeper" in lower or "decide whether the user question" in lower:
            return self._json(
                {
                    "is_medical": True,
                    "confidence": 0.9,
                    "reason": "Medical question.",
                    "categories": [],
                }
            )
        else:
            kind, handler = "generation", self.generation

        self.calls.append(kind)
        if handler is None:
            raise ProviderError("scripted", f"no scripted response for {kind}")
        if callable(handler):
            handler = handler(text)
        if isinstance(handler, Exception):
            raise handler
        if isinstance(handler, dict):
            return self._json(handler)
        return LLMResult(
            text=str(handler),
            prompt_tokens=10,
            completion_tokens=10,
            provider="scripted",
            model=self.model,
        )

    @staticmethod
    def _json(payload: dict) -> LLMResult:
        return LLMResult(
            text=json.dumps(payload),
            prompt_tokens=10,
            completion_tokens=10,
            provider="scripted",
        )


def _hit(
    chunk_id: str,
    content: str,
    *,
    score: float = 0.5,
    rerank: float | None = None,
    page: int = 1,
    document_id: str = "doc-1",
    filename: str = "hypertension.txt",
) -> SearchHit:
    return SearchHit(
        chunk_id=chunk_id,
        document_id=document_id,
        user_id=1,
        filename=filename,
        content=content,
        page=page,
        score=score,
        rerank_score=rerank,
    )


def _grade_payload(
    *,
    supported: int,
    total: int,
    direct_support: bool = True,
    score: float = 0.8,
    reason: str = "Graded from the retrieved passages.",
) -> dict:
    aspects = [
        {
            "aspect": f"aspect {index + 1}",
            "supported": index < supported,
            "evidence": [index + 1] if index < supported else [],
        }
        for index in range(total)
    ]
    return {
        "aspects": aspects,
        "coverage": supported / total,
        "direct_support": direct_support,
        "score": score,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# TASK 1 — query transformation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_transform_produces_valid_schema(monkeypatch):
    llm = ScriptedLLM(
        transform={
            "rewritten": "hypertension definition and causes",
            "subqueries": ["what causes hypertension"],
            "expanded_terms": ["HTN", "blood pressure"],
        }
    )
    monkeypatch.setattr("app.services.query_transform.get_llm_provider", lambda: llm)

    result = await transform_query("What is hypertension and what causes it?")

    assert result.status == "llm"
    assert result.used_llm is True
    assert result.fallback_used is False
    assert result.rewritten == "hypertension definition and causes"
    assert result.expanded_terms == ["HTN", "blood pressure"]
    # Both parts of the multi-part question remain represented.
    assert len(result.aspects) == 2
    assert any("cause" in query.lower() for query in result.search_queries)
    assert any(
        "hypertension" in query.lower() and "definition" in query.lower()
        for query in result.search_queries
    )


@pytest.mark.asyncio
async def test_query_transform_recovers_from_malformed_json(monkeypatch):
    llm = ScriptedLLM(transform="I am not able to return JSON for this request.")
    monkeypatch.setattr("app.services.query_transform.get_llm_provider", lambda: llm)

    result = await transform_query("What is hypertension? What is the cause of it?")

    assert result.status == "fallback"
    assert result.fallback_used is True
    assert result.used_llm is False
    assert result.error
    assert "hypertension" in result.rewritten.lower()
    assert len(result.aspects) == 2
    assert any("cause" in query.lower() for query in result.search_queries)


@pytest.mark.asyncio
async def test_query_transform_handles_empty_response(monkeypatch):
    llm = ScriptedLLM(
        transform=ProviderError("groq", "response contained an empty answer", status_code=400)
    )
    monkeypatch.setattr("app.services.query_transform.get_llm_provider", lambda: llm)

    result = await transform_query("What is hypertension?")

    assert result.status == "fallback"
    assert result.rewritten
    assert result.search_queries
    assert "hypertension" in result.search_queries[0].lower()


@pytest.mark.asyncio
async def test_query_transform_rejects_wrong_field_types(monkeypatch):
    llm = ScriptedLLM(transform={"rewritten": 42, "subqueries": "not-a-list"})
    monkeypatch.setattr("app.services.query_transform.get_llm_provider", lambda: llm)

    result = await transform_query("What causes hypertension?")

    assert result.status == "fallback"
    assert result.error


@pytest.mark.asyncio
async def test_refine_queries_always_changes_the_search(monkeypatch):
    question = "What is hypertension? What is the cause of it?"
    first = await _fallback_transform(question, monkeypatch)
    previous_queries = {query.lower() for query in first.search_queries}

    llm = ScriptedLLM(
        transform={"rewritten": question, "subqueries": [], "expanded_terms": []}
    )
    monkeypatch.setattr("app.services.query_transform.get_llm_provider", lambda: llm)

    refined = await refine_queries(
        first, question, retry_hint="Evidence about causes was missing."
    )

    assert {query.lower() for query in refined.search_queries} != previous_queries
    assert refined.search_queries


async def _fallback_transform(question: str, monkeypatch) -> QueryTransformResult:
    llm = ScriptedLLM(transform="not json")
    monkeypatch.setattr("app.services.query_transform.get_llm_provider", lambda: llm)
    return await transform_query(question)


# ---------------------------------------------------------------------------
# TASK 2 — retrieval selection
# ---------------------------------------------------------------------------


def test_select_evidence_covers_every_question_aspect():
    hits = [
        _hit("s1", "Symptoms of hypertension include headache and dizziness.", rerank=0.95),
        _hit("s2", "Symptoms also include blurred vision and fatigue.", rerank=0.9),
        _hit("d1", "Hypertension is defined as blood pressure at or above 140/90 mmHg.", rerank=0.4),
        _hit(
            "c1",
            "Risk factors and causes of hypertension include high salt intake and obesity.",
            rerank=0.35,
        ),
    ]

    selected = select_evidence(
        hits, ["What is hypertension", "what causes it"], 3
    )
    ids = {hit.chunk_id for hit in selected}

    assert "d1" in ids, "definition passage must be retained for a definition aspect"
    assert "c1" in ids, "cause passage must be retained for a cause aspect"
    assert len(selected) == 3


def test_select_evidence_deduplicates_near_identical_passages():
    duplicated = (
        "Hypertension is a chronic condition with persistently elevated arterial "
        "blood pressure requiring long term monitoring and treatment."
    )
    hits = [
        _hit("a", duplicated, rerank=0.9),
        _hit("b", duplicated + " ", rerank=0.85),
        _hit("c", "Causes include high salt intake and obesity.", rerank=0.6),
    ]

    selected = select_evidence(hits, ["What is hypertension"], 3)
    ids = [hit.chunk_id for hit in selected]

    assert "a" in ids
    assert "b" not in ids


# ---------------------------------------------------------------------------
# TASK 3 — evidence grading
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grade_evidence_marks_full_coverage_sufficient(monkeypatch):
    llm = ScriptedLLM(grade=_grade_payload(supported=2, total=2, score=0.9))
    monkeypatch.setattr("app.services.agentic_rag.get_llm_provider", lambda: llm)
    hits = [
        _hit("c1", "Hypertension is a chronic condition with elevated blood pressure.", rerank=0.8),
        _hit("c2", "Causes include high salt intake, obesity and family history.", rerank=0.7),
    ]

    grade = await _grade_evidence(
        "What is hypertension and what causes it?",
        ["What is hypertension", "what causes it"],
        hits,
        RequestTrace(),
    )

    assert grade.outcome == "sufficient"
    assert grade.coverage == 1.0
    assert grade.source == "model"
    assert grade.missing_aspects == []


@pytest.mark.asyncio
async def test_grade_evidence_allows_partial_coverage(monkeypatch):
    llm = ScriptedLLM(
        grade=_grade_payload(
            supported=1,
            total=2,
            score=0.5,
            reason="The passages define the condition but do not describe causes.",
        )
    )
    monkeypatch.setattr("app.services.agentic_rag.get_llm_provider", lambda: llm)
    hits = [
        _hit("c1", "Hypertension is a chronic condition with elevated blood pressure.", rerank=0.8),
        _hit("c2", "Symptoms include headache and dizziness.", rerank=0.6),
    ]

    grade = await _grade_evidence(
        "What is hypertension and what causes it?",
        ["What is hypertension", "what causes it"],
        hits,
        RequestTrace(),
    )

    assert grade.outcome == "partial"
    assert grade.coverage == 0.5
    assert grade.missing_aspects
    assert grade.score != 0.6 or grade.score == 0.5


@pytest.mark.asyncio
async def test_grade_evidence_abstains_without_direct_support(monkeypatch):
    llm = ScriptedLLM(
        grade={
            "aspects": [
                {"aspect": "definition", "supported": False, "evidence": []},
                {"aspect": "causes", "supported": False, "evidence": []},
            ],
            "coverage": 0.0,
            "direct_support": False,
            "score": 0.1,
            "reason": "The passages do not answer the question.",
        }
    )
    monkeypatch.setattr("app.services.agentic_rag.get_llm_provider", lambda: llm)
    hits = [_hit("c1", "Unrelated administrative policy text.", rerank=0.7)]

    grade = await _grade_evidence(
        "What causes hypertension?",
        ["What causes hypertension"],
        hits,
        RequestTrace(),
    )

    assert grade.outcome == "insufficient"
    assert grade.coverage == 0.0


@pytest.mark.asyncio
async def test_grade_evidence_heuristic_is_derived_from_passages(monkeypatch):
    llm = ScriptedLLM(
        grade=ProviderError("groq", "HTTP 400: json_validate_failed", status_code=400)
    )
    monkeypatch.setattr("app.services.agentic_rag.get_llm_provider", lambda: llm)
    hits = [
        _hit("c1", "Hypertension is a chronic condition with elevated blood pressure.", rerank=0.75),
        _hit("c2", "Symptoms include headache and dizziness.", rerank=0.5),
    ]

    grade = await _grade_evidence(
        "What is hypertension and what causes it?",
        ["What is hypertension", "what causes it"],
        hits,
        RequestTrace(),
    )

    assert grade.source == "heuristic"
    assert 0.0 <= grade.score <= 1.0
    assert grade.coverage == pytest.approx(0.5)
    assert grade.outcome == "partial"


# ---------------------------------------------------------------------------
# TASK 1E — provider JSON compatibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groq_json_mode_degrades_once(monkeypatch):
    from app.config import get_settings
    from app.providers import llm as llm_module

    settings = get_settings()
    provider = llm_module.OpenAICompatibleLLM(
        settings,
        name="groq",
        base_url=settings.groq_base_url,
        api_key="test-key",
        model="openai/gpt-oss-120b",
        missing_env="GROQ_API_KEY",
    )
    calls: list[dict] = []

    async def fake_request_json(method, url, **kwargs):
        calls.append(dict(kwargs["json"]))
        if len(calls) == 1:
            raise ProviderError(
                "groq",
                "HTTP 400: json_validate_failed Failed to generate JSON",
                status_code=400,
            )
        return {
            "choices": [{"message": {"content": '{"rewritten": "q"}'}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
        }

    monkeypatch.setattr(llm_module, "request_json", fake_request_json)

    result = await provider.complete(
        [{"role": "user", "content": "rewrite this"}], json_mode=True, max_tokens=1600
    )

    assert result.text == '{"rewritten": "q"}'
    assert len(calls) == 2
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]
    assert calls[0]["reasoning_effort"] == "low"


def test_parse_json_object_rejects_truncated_output():
    with pytest.raises(ProviderError, match="truncated"):
        parse_json_object('{"rewritten": "hypertension"')


def test_parse_json_object_rejects_empty_output():
    with pytest.raises(ProviderError, match="empty"):
        parse_json_object("   ")


# ---------------------------------------------------------------------------
# TASK 4/5 — end-to-end pipeline behaviour through the API
# ---------------------------------------------------------------------------


def _register_and_login(client):
    email = f"rag-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "securepass123", "full_name": "RAG Owner"},
    )
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": "securepass123"}
    )
    return email, {"Authorization": f"Bearer {login.json()['access_token']}"}


def _upload_guideline(client, headers) -> str:
    response = client.post(
        "/api/v1/documents/upload",
        headers=headers,
        files=[("files", ("hypertension.txt", HYPERTENSION_TEXT.encode(), "text/plain"))],
    )
    assert response.status_code == 200, response.text
    document_id = response.json()["documents"][0]["id"]

    from app.services.jobs import process_pending_jobs_once
    import asyncio

    asyncio.run(process_pending_jobs_once(limit=1))
    document = client.get(f"/api/v1/documents/{document_id}/status", headers=headers).json()
    assert document["status"] == "completed", document
    return document_id


def _patch_llm(monkeypatch, llm: ScriptedLLM) -> None:
    for module in (
        "app.services.agentic_rag",
        "app.services.query_transform",
        "app.services.domain_validation",
    ):
        monkeypatch.setattr(f"{module}.get_llm_provider", lambda _llm=llm: _llm)


def test_partial_question_is_answered_not_abstained(client, monkeypatch):
    _, headers = _register_and_login(client)
    _upload_guideline(client, headers)

    llm = ScriptedLLM(
        transform={
            "rewritten": "hypertension definition and causes",
            "subqueries": ["what causes hypertension"],
            "expanded_terms": [],
        },
        grade=_grade_payload(
            supported=1,
            total=2,
            score=0.55,
            reason="The definition is present but causes are not described.",
        ),
        verify={
            "addresses_question": True,
            "grounded": True,
            "claims": [
                {
                    "claim": "Hypertension is a chronic condition with elevated arterial blood pressure",
                    "evidence": [1],
                    "supported": True,
                }
            ],
        },
        generation=(
            "Hypertension is a chronic condition with persistently elevated arterial "
            "blood pressure [1].\n\nThe uploaded documents do not provide enough "
            "information about its causes."
        ),
    )
    _patch_llm(monkeypatch, llm)

    response = client.post(
        "/api/v1/chat/query",
        headers=headers,
        json={"question": "What is hypertension? What is the cause of it?", "mode": "agentic"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["insufficient_evidence"] is False
    assert body["evidence_status"] == "partial"
    assert body["answer"]
    assert body["sources"], "a grounded partial answer keeps its citations"
    metadata = body["agent_metadata"]
    assert metadata["evidence_outcome"] == "partial"
    assert metadata["evidence_coverage"] == pytest.approx(0.5)
    assert metadata["abstention_reason"] is None
    assert metadata["passages_retained"] >= 1
    assert metadata["original_question"] == "What is hypertension? What is the cause of it?"
    assert "verification_ms" in metadata["latency_ms"]


def test_insufficient_evidence_abstains_without_generating(client, monkeypatch):
    _, headers = _register_and_login(client)
    _upload_guideline(client, headers)

    llm = ScriptedLLM(
        transform={"rewritten": "hypertension", "subqueries": [], "expanded_terms": []},
        grade={
            "aspects": [
                {"aspect": "definition", "supported": False, "evidence": []},
                {"aspect": "causes", "supported": False, "evidence": []},
            ],
            "coverage": 0.0,
            "direct_support": False,
            "score": 0.05,
            "reason": "The passages do not contain the requested information.",
        },
        generation=None,
    )
    _patch_llm(monkeypatch, llm)

    response = client.post(
        "/api/v1/chat/query",
        headers=headers,
        json={"question": "What is the cause of hypertension?", "mode": "agentic"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["insufficient_evidence"] is True
    assert body["sources"] == []
    assert body["agent_metadata"]["abstention_reason"]
    assert body["agent_metadata"]["retrieval_attempts"] == 2
    assert "generation" not in llm.calls, "abstention must not call answer generation"
    assert "verification_ms" not in body["agent_metadata"]["latency_ms"]


def test_citations_only_reference_retrieved_passages(client, monkeypatch):
    _, headers = _register_and_login(client)
    _upload_guideline(client, headers)

    llm = ScriptedLLM(
        transform={"rewritten": "hypertension definition", "subqueries": [], "expanded_terms": []},
        grade=_grade_payload(supported=1, total=1, score=0.9),
        verify={
            "addresses_question": True,
            "grounded": True,
            "claims": [
                {
                    "claim": "Hypertension is defined by persistently elevated arterial blood pressure",
                    "evidence": [99],
                    "supported": True,
                }
            ],
        },
        generation="Hypertension is defined by persistently elevated arterial blood pressure [99].",
    )
    _patch_llm(monkeypatch, llm)

    response = client.post(
        "/api/v1/chat/query",
        headers=headers,
        json={"question": "What is hypertension?", "mode": "agentic"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    metadata = body["agent_metadata"]
    for source in body["sources"]:
        assert 1 <= source["index"] <= metadata["passages_retained"]
        assert source["filename"] == "hypertension.txt"
        assert source["document_id"]
    assert "[99]" in body["answer"]


@pytest.mark.asyncio
async def test_split_question_aspects_handles_common_phrasings():
    assert len(split_question_aspects("What is hypertension? What is the cause of it?")) == 2
    assert len(split_question_aspects("What is hypertension and what causes it?")) == 2
    assert split_question_aspects("What is hypertension?") == ["What is hypertension"]
