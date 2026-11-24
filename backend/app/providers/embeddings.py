"""Hosted embedding providers (no local model weights)."""

from __future__ import annotations

import math
from typing import List, Sequence

from app.config import Settings
from app.providers.base import EmbeddingProvider, ProviderError, ProviderNotConfigured
from app.providers.http import request_json


def _normalize(vector: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(float(v) * float(v) for v in vector))
    if norm <= 1e-12:
        return [0.0 for _ in vector]
    return [float(v) / norm for v in vector]


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini embeddings (free tier available, 768 recommended dims)."""

    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        if not settings.gemini_api_key:
            raise ProviderNotConfigured("gemini-embeddings", "GEMINI_API_KEY")
        self.settings = settings
        self.api_key = settings.gemini_api_key
        self.model = settings.embedding_model
        self.dimensions = settings.embedding_dimensions
        self.base_url = settings.gemini_base_url.rstrip("/") + "/v1beta"

    async def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        vectors: List[List[float]] = []
        batch_size = max(1, min(self.settings.embedding_batch_size, 100))
        for start in range(0, len(texts), batch_size):
            batch = [t for t in texts[start : start + batch_size]]
            requests = []
            for text in batch:
                body = {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text[:30000]}]},
                }
                # Only embedding models that support MRL accept this field.
                if "embedding" in self.model:
                    body["outputDimensionality"] = self.dimensions
                requests.append(body)

            payload = await request_json(
                "POST",
                f"{self.base_url}/models/{self.model}:batchEmbedContents",
                provider="gemini-embeddings",
                headers={
                    "x-goog-api-key": self.api_key,
                    "Content-Type": "application/json",
                },
                json={"requests": requests},
                timeout=self.settings.ai_request_timeout_seconds,
                retries=self.settings.ai_max_retries,
            )
            embeddings = payload.get("embeddings") or []
            if len(embeddings) != len(batch):
                raise ProviderError(
                    "gemini-embeddings",
                    f"expected {len(batch)} embeddings, received {len(embeddings)}",
                )
            for item in embeddings:
                values = item.get("values") or []
                if not values:
                    raise ProviderError("gemini-embeddings", "empty vector in response")
                vectors.append(_normalize(values))
        return vectors


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """OpenAI-compatible embeddings (OpenAI, Jina, or any compatible gateway)."""

    def __init__(
        self,
        settings: Settings,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        dimensions: int,
        missing_env: str,
        send_dimensions: bool = True,
    ) -> None:
        if not api_key:
            raise ProviderNotConfigured(name, missing_env)
        self.settings = settings
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.send_dimensions = send_dimensions

    async def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        vectors: List[List[float]] = []
        batch_size = max(1, min(self.settings.embedding_batch_size, 64))
        for start in range(0, len(texts), batch_size):
            batch = list(texts[start : start + batch_size])
            body = {"model": self.model, "input": batch}
            if self.send_dimensions:
                body["dimensions"] = self.dimensions
            payload = await request_json(
                "POST",
                f"{self.base_url}/embeddings",
                provider=self.name,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=self.settings.ai_request_timeout_seconds,
                retries=self.settings.ai_max_retries,
            )
            data = sorted(payload.get("data") or [], key=lambda item: item.get("index", 0))
            if len(data) != len(batch):
                raise ProviderError(
                    self.name, f"expected {len(batch)} embeddings, received {len(data)}"
                )
            for item in data:
                values = item.get("embedding") or []
                if not values:
                    raise ProviderError(self.name, "empty vector in response")
                vectors.append(_normalize(values))
        return vectors


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    provider = settings.embedding_provider.strip().lower()
    if provider == "gemini":
        return GeminiEmbeddingProvider(settings)
    if provider == "openai":
        return OpenAICompatibleEmbeddingProvider(
            settings,
            name="openai-embeddings",
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            missing_env="OPENAI_API_KEY",
        )
    if provider == "jina":
        return OpenAICompatibleEmbeddingProvider(
            settings,
            name="jina-embeddings",
            base_url=settings.jina_base_url,
            api_key=settings.jina_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            missing_env="JINA_API_KEY",
        )
    raise ProviderError("embeddings", f"unsupported EMBEDDING_PROVIDER '{provider}'")
