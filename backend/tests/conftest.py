"""Test configuration.

Environment variables are set before importing the application so the engine,
settings and storage backend are all pointed at throw-away locations.  Every
hosted AI provider is replaced with a deterministic fake; tests never call an
external API.
"""

from __future__ import annotations

import json
import math
import os
import pathlib
import re
import tempfile
from typing import List, Sequence

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="mediquery-tests-"))
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "STORAGE_BACKEND": "local",
        "STORAGE_LOCAL_DIR": str(_TMP / "storage"),
        "JWT_SECRET": "test-secret-key-that-is-definitely-long-enough-123456",
        "BACKGROUND_WORKER_ENABLED": "false",
        "WEB_SEARCH_ENABLED": "false",
        "RERANK_PROVIDER": "lexical",
        "OCR_PROVIDER": "none",
        "VISION_PROVIDER": "none",
        "EMBEDDING_PROVIDER": "gemini",
        "LLM_PROVIDER": "groq",
        "GEMINI_API_KEY": "fake-key",
        "GROQ_API_KEY": "fake-key",
        "MEDICAL_DOMAIN_LLM_CHECK": "true",
        "ENABLE_GRAPH_RAG": "true",
        "RATE_LIMIT_PER_MINUTE": "1000",
        "RATE_LIMIT_UPLOAD_PER_MINUTE": "1000",
    }
)

import pytest  # noqa: E402

import app.models  # noqa: E402,F401 - register models
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.providers.base import (  # noqa: E402
    EmbeddingProvider,
    LLMProvider,
    LLMResult,
    OCRProvider,
)

MEDICAL_WORDS = {
    "diabetes", "symptom", "symptoms", "blood", "pressure", "hypertension", "drug",
    "dose", "dosage", "metformin", "insulin", "treatment", "patient", "clinical",
    "medical", "health", "glucose", "hba1c", "disease", "medication", "therapy",
}


def _vector(text: str, dimensions: int) -> List[float]:
    vector = [0.0] * dimensions
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        index = hash(token) % dimensions
        vector[index] += 1.0 + (len(token) % 3) * 0.1
    if not any(vector):
        vector[0] = 1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector]


class FakeEmbeddingProvider(EmbeddingProvider):
    name = "fake"
    model = "fake-embedding"

    def __init__(self) -> None:
        from app.config import get_settings

        self.dimensions = get_settings().embedding_dimensions

    async def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return [_vector(text, self.dimensions) for text in texts]


class FakeLLMProvider(LLMProvider):
    name = "fake"
    model = "fake-medical-llm"

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
        payload: dict

        if "optimise search queries" in lower:
            match = re.search(r"User question:\s*(.+)", text)
            question = match.group(1).strip() if match else ""
            payload = {"rewritten": question, "subqueries": [], "expanded_terms": []}
        elif "grade retrieval quality" in lower:
            payload = {
                "aspects": [
                    {"aspect": "question aspect", "supported": True, "evidence": [1]}
                ],
                "coverage": 1.0,
                "direct_support": True,
                "score": 0.85,
                "reason": "Relevant clinical content.",
            }
        elif "verify medical answers" in lower:
            payload = {
                "addresses_question": True,
                "grounded": True,
                "claims": [
                    {
                        "claim": "Clinical information is described in the uploaded document",
                        "evidence": [1],
                        "supported": True,
                    }
                ],
            }
        elif "knowledge-graph" in lower:
            payload = {"entities": [], "relations": []}
        elif "gatekeeper" in lower or "decide whether the user question" in lower:
            has_medical = any(word in lower for word in MEDICAL_WORDS)
            has_junk = any(
                word in lower for word in ("python", "javascript", "function", "football", "lease")
            )
            payload = {
                "is_medical": has_medical and not has_junk,
                "confidence": 0.9,
                "reason": "Classified by the test double.",
                "categories": [],
            }
        elif "translate" in lower:
            payload = {"text": text}
            return LLMResult(text=text, prompt_tokens=5, completion_tokens=5, provider="fake")
        else:
            return LLMResult(
                text="Clinical information from the uploaded document addresses this question [1].",
                prompt_tokens=20,
                completion_tokens=15,
                provider="fake",
            )

        return LLMResult(
            text=json.dumps(payload),
            prompt_tokens=12,
            completion_tokens=8,
            provider="fake",
        )


class FakeOCRProvider(OCRProvider):
    name = "fake-ocr"

    @property
    def available(self) -> bool:
        return False

    async def extract_text(self, image_bytes: bytes, mime_type: str) -> str:
        return ""


@pytest.fixture(scope="session", autouse=True)
def _schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def fake_providers(monkeypatch):
    from app.providers.rerank import LexicalReranker

    embed = FakeEmbeddingProvider()
    llm = FakeLLMProvider()
    ocr = FakeOCRProvider()
    lexical = LexicalReranker()

    targets = [
        ("app.services.indexing", "get_embedding_provider", embed),
        ("app.services.indexing", "get_ocr_provider", ocr),
        ("app.services.indexing", "get_vision_provider", None),
        ("app.services.retrieval", "get_embedding_provider", embed),
        ("app.services.agentic_rag", "get_llm_provider", llm),
        ("app.services.agentic_rag", "get_rerank_provider", lexical),
        ("app.services.query_transform", "get_llm_provider", llm),
        ("app.services.graph_rag", "get_llm_provider", llm),
        ("app.services.domain_validation", "get_llm_provider", llm),
        ("app.services.translation", "get_llm_provider", llm),
        ("app.services.tools", "request_json", None),
    ]

    import importlib

    for module_name, attribute, value in targets:
        if value is None and attribute == "request_json":
            continue
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, attribute, lambda *args, _v=value, **kwargs: _v)

    yield


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
