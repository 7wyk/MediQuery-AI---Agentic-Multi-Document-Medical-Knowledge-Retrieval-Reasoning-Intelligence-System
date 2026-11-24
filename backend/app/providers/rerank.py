"""Hosted reranking providers plus a deterministic lexical fallback.

The lexical fallback is a scoring algorithm (no model weights) used when no
hosted reranker is configured; it is clearly reported as a limitation in the
response metadata and documentation.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import List, Sequence

from app.config import Settings
from app.providers.base import ProviderError, ProviderNotConfigured, RerankingProvider, RerankResult
from app.providers.http import request_json

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-]{1,}", re.IGNORECASE)
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "have",
    "has", "had", "not", "but", "you", "your", "what", "which", "who", "how", "why",
    "when", "where", "does", "did", "can", "could", "should", "would", "about", "into",
    "than", "then", "there", "their", "they", "its", "it's", "of", "in", "on", "to",
}


def _tokens(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOPWORDS]


class JinaReranker(RerankingProvider):
    name = "jina"

    def __init__(self, settings: Settings) -> None:
        if not settings.jina_api_key:
            raise ProviderNotConfigured("jina-rerank", "JINA_API_KEY")
        self.settings = settings
        self.api_key = settings.jina_api_key
        self.base_url = settings.jina_base_url.rstrip("/")
        self.model = settings.rerank_model

    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int = 8
    ) -> List[RerankResult]:
        if not documents:
            return []
        payload = await request_json(
            "POST",
            f"{self.base_url}/rerank",
            provider="jina-rerank",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "query": query,
                "documents": list(documents),
                "top_n": min(top_n, len(documents)),
            },
            timeout=self.settings.ai_request_timeout_seconds,
            retries=self.settings.ai_max_retries,
        )
        results = payload.get("results") or []
        if not results:
            raise ProviderError("jina-rerank", "response contained no rankings")
        return [
            RerankResult(index=int(item.get("index", 0)), score=float(item.get("relevance_score", 0.0)))
            for item in results
        ]


class CohereReranker(RerankingProvider):
    name = "cohere"

    def __init__(self, settings: Settings) -> None:
        if not settings.cohere_api_key:
            raise ProviderNotConfigured("cohere-rerank", "COHERE_API_KEY")
        self.settings = settings
        self.api_key = settings.cohere_api_key
        self.base_url = settings.cohere_base_url.rstrip("/")
        self.model = settings.rerank_model or "rerank-v3.5"

    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int = 8
    ) -> List[RerankResult]:
        if not documents:
            return []
        payload = await request_json(
            "POST",
            f"{self.base_url}/v2/rerank",
            provider="cohere-rerank",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "query": query,
                "documents": list(documents),
                "top_n": min(top_n, len(documents)),
            },
            timeout=self.settings.ai_request_timeout_seconds,
            retries=self.settings.ai_max_retries,
        )
        results = payload.get("results") or []
        if not results:
            raise ProviderError("cohere-rerank", "response contained no rankings")
        return [
            RerankResult(index=int(item.get("index", 0)), score=float(item.get("relevance_score", 0.0)))
            for item in results
        ]


class LexicalReranker(RerankingProvider):
    """Deterministic BM25-style scorer; no model, no network, no local weights."""

    name = "lexical"
    model = "bm25-lexical"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings

    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int = 8
    ) -> List[RerankResult]:
        if not documents:
            return []
        query_terms = _tokens(query)
        if not query_terms:
            return [RerankResult(index=i, score=0.5) for i in range(min(top_n, len(documents)))]

        doc_tokens = [_tokens(doc) for doc in documents]
        avg_len = sum(len(t) for t in doc_tokens) / max(1, len(doc_tokens))
        df = Counter()
        for tokens in doc_tokens:
            for term in set(tokens):
                df[term] += 1
        total_docs = len(documents)
        scored: List[RerankResult] = []
        for index, tokens in enumerate(doc_tokens):
            tf = Counter(tokens)
            length = max(1, len(tokens))
            score = 0.0
            for term in query_terms:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                idf = math.log(1 + (total_docs - df[term] + 0.5) / (df[term] + 0.5))
                denominator = freq + 1.2 * (1 - 0.75 + 0.75 * length / max(avg_len, 1))
                score += idf * (freq * 2.2) / denominator
            # Normalise into 0..1 so downstream thresholds stay meaningful.
            normalised = 1 - math.exp(-score / 3.0)
            scored.append(RerankResult(index=index, score=round(normalised, 6)))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_n]


class NoopReranker(RerankingProvider):
    name = "none"
    model = "none"

    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int = 8
    ) -> List[RerankResult]:
        return [RerankResult(index=i, score=1.0 / (i + 1)) for i in range(min(top_n, len(documents)))]


def build_rerank_provider(settings: Settings) -> RerankingProvider:
    provider = settings.rerank_provider.strip().lower()
    if provider in {"none", "off", "disabled"}:
        return NoopReranker()
    if provider == "jina":
        return JinaReranker(settings)
    if provider == "cohere":
        return CohereReranker(settings)
    if provider == "lexical":
        return LexicalReranker(settings)
    raise ProviderError("rerank", f"unsupported RERANK_PROVIDER '{provider}'")
