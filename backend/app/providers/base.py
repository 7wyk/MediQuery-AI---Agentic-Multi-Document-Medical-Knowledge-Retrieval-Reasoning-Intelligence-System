"""Provider interfaces for all hosted AI capabilities.

The application never falls back to a locally hosted model.  If a provider is
not configured or an API call fails, a ``ProviderError`` (or
``ProviderNotConfigured``) is raised so callers can degrade gracefully with an
explicit message.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Sequence


class ProviderError(RuntimeError):
    """A hosted provider failed in a way the caller must handle."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status_code: Optional[int] = None,
        retryable: bool = False,
    ) -> None:
        self.provider = provider
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(f"{provider}: {message}")


class ProviderNotConfigured(ProviderError):
    def __init__(self, provider: str, missing: str) -> None:
        super().__init__(provider, f"not configured (missing {missing})")


@dataclass
class LLMResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    provider: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


@dataclass
class RerankResult:
    index: int
    score: float


class EmbeddingProvider(ABC):
    name: str = "embedding"
    model: str = ""
    dimensions: int = 768

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        ...

    async def embed_query(self, text: str) -> List[float]:
        vectors = await self.embed_documents([text])
        if not vectors:
            raise ProviderError(self.name, "empty embedding response")
        return vectors[0]


class LLMProvider(ABC):
    name: str = "llm"
    model: str = ""

    @abstractmethod
    async def complete(
        self,
        messages: Sequence[dict],
        *,
        temperature: float = 0.1,
        max_tokens: int = 1200,
        json_mode: bool = False,
    ) -> LLMResult:
        ...


class RerankingProvider(ABC):
    name: str = "rerank"
    model: str = ""

    @abstractmethod
    async def rerank(
        self, query: str, documents: Sequence[str], top_n: int = 8
    ) -> List[RerankResult]:
        ...


class VisionProvider(ABC):
    name: str = "vision"
    model: str = ""

    @abstractmethod
    async def describe_image(self, image_bytes: bytes, mime_type: str, prompt: str) -> str:
        ...


class OCRProvider(ABC):
    name: str = "ocr"

    @property
    @abstractmethod
    def available(self) -> bool:
        ...

    @abstractmethod
    async def extract_text(self, image_bytes: bytes, mime_type: str) -> str:
        ...
