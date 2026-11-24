"""Structured logging, request tracing, token accounting and cost estimation."""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

from app.config import get_settings
from app.providers.base import LLMResult

logger = logging.getLogger(__name__)

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

SENSITIVE_KEYS = {
    "password", "hashed_password", "access_token", "refresh_token", "authorization",
    "api_key", "apikey", "service_role_key", "jwt_secret", "token", "secret",
}


def new_request_id() -> str:
    return uuid.uuid4().hex


def configure_logging(level: Optional[str] = None) -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, (level or settings.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging API
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get() or "-"
        return True


def install_log_filter() -> None:
    root = logging.getLogger()
    for handler in root.handlers:
        handler.addFilter(RequestIdFilter())


def redact(data: object) -> object:
    """Recursively remove secrets from a structure before logging it."""
    if isinstance(data, dict):
        return {
            key: ("***" if str(key).lower() in SENSITIVE_KEYS else redact(value))
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact(item) for item in data[:50]]
    if isinstance(data, str) and len(data) > 500:
        return data[:500] + "…"
    return data


def safe_log(message: str, **fields: object) -> None:
    payload = redact(fields)
    logger.info("%s %s", message, json.dumps(payload, default=str))


@dataclass
class RequestTrace:
    """Per-request telemetry for the RAG pipeline."""

    request_id: str = field(default_factory=new_request_id)
    user_id: Optional[int] = None
    stages: Dict[str, float] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retries: int = 0
    errors: List[str] = field(default_factory=list)
    reranker: Optional[str] = None
    embedding_tokens_estimate: int = 0
    rerank_documents: int = 0
    skipped_stages: set[str] = field(default_factory=set)
    diagnostics: Dict[str, object] = field(default_factory=dict)
    started_at: float = field(default_factory=time.perf_counter)

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.stages[name] = round(self.stages.get(name, 0.0) + elapsed_ms, 2)

    def add_llm_usage(self, result: LLMResult) -> None:
        self.prompt_tokens += result.prompt_tokens or 0
        self.completion_tokens += result.completion_tokens or 0

    def add_embedding_text(self, text: str) -> None:
        self.embedding_tokens_estimate += max(1, len(text) // 4)

    def add_error(self, message: str) -> None:
        if message and message not in self.errors:
            self.errors.append(message[:400])

    def mark_skipped(self, stage: str) -> None:
        """Record that a stage did not run (so 0 ms is not read as a measurement)."""
        self.skipped_stages.add(stage)

    def set_diagnostics(self, **fields: object) -> None:
        """Attach privacy-safe RAG decision details to the request summary log."""
        self.diagnostics.update(fields)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started_at) * 1000, 2)

    def estimated_cost_usd(self) -> float:
        settings = get_settings()
        llm_cost = (
            self.prompt_tokens / 1_000_000 * settings.cost_llm_input_per_1m
            + self.completion_tokens / 1_000_000 * settings.cost_llm_output_per_1m
        )
        embedding_cost = (
            self.embedding_tokens_estimate / 1_000_000 * settings.cost_embedding_per_1m
        )
        rerank_cost = self.rerank_documents / 1000 * settings.cost_rerank_per_1k
        return round(llm_cost + embedding_cost + rerank_cost, 6)

    def latency_breakdown(self) -> Dict[str, float]:
        breakdown = {
            "transform_ms": self.stages.get("transform", 0.0),
            "grading_ms": self.stages.get("grading", 0.0),
            "embedding_ms": self.stages.get("embedding", 0.0),
            "retrieval_ms": self.stages.get("retrieval", 0.0),
            "rerank_ms": self.stages.get("rerank", 0.0),
            "llm_ms": self.stages.get("generation", 0.0) + self.stages.get("transform", 0.0),
            "generation_ms": self.stages.get("generation", 0.0),
            "web_search_ms": self.stages.get("web_search", 0.0),
            "total_ms": self.elapsed_ms,
        }
        # Only report verification latency when verification actually ran; an
        # abstained request never reaches it, so 0.0 would be misleading.
        if "verification" in self.stages:
            breakdown["verification_ms"] = self.stages["verification"]
        return breakdown

    def log_summary(
        self,
        *,
        answer_found: bool,
        web_used: bool,
        extra: Optional[Dict[str, object]] = None,
    ) -> None:
        safe_log(
            "rag_request_complete",
            request_id=self.request_id,
            user_id=self.user_id,
            latency_ms=self.latency_breakdown(),
            tokens={"prompt": self.prompt_tokens, "completion": self.completion_tokens},
            estimated_cost_usd=self.estimated_cost_usd(),
            retries=self.retries,
            skipped_stages=sorted(self.skipped_stages),
            web_search_used=web_used,
            answer_found=answer_found,
            errors=self.errors,
            **(extra or {}),
        )
