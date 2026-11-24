"""Provider registry.

Providers are constructed lazily and cached per process so importing the
application has no credential or network side effects.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Optional

from app.config import Settings, get_settings
from app.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    OCRProvider,
    ProviderError,
    RerankingProvider,
    VisionProvider,
)
from app.providers.embeddings import build_embedding_provider
from app.providers.llm import build_llm_provider
from app.providers.ocr import build_ocr_provider, build_vision_provider
from app.providers.rerank import LexicalReranker, build_rerank_provider

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    return build_embedding_provider(get_settings())


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    return build_llm_provider(get_settings())


@lru_cache(maxsize=1)
def get_rerank_provider() -> RerankingProvider:
    settings = get_settings()
    try:
        return build_rerank_provider(settings)
    except ProviderError as exc:
        logger.warning("Falling back to lexical reranker: %s", exc)
        return LexicalReranker(settings)


@lru_cache(maxsize=1)
def get_ocr_provider() -> OCRProvider:
    return build_ocr_provider(get_settings())


@lru_cache(maxsize=1)
def get_vision_provider() -> Optional[VisionProvider]:
    try:
        return build_vision_provider(get_settings())
    except ProviderError as exc:
        logger.warning("Vision provider unavailable: %s", exc)
        return None


def clear_provider_cache() -> None:
    """Used by tests when settings change."""
    for factory in (
        get_embedding_provider,
        get_llm_provider,
        get_rerank_provider,
        get_ocr_provider,
        get_vision_provider,
    ):
        factory.cache_clear()


def provider_status(settings: Settings | None = None) -> dict:
    """Non-sensitive provider configuration report for /health."""
    settings = settings or get_settings()
    requirements = {
        "embedding": {
            "gemini": settings.gemini_api_key,
            "jina": settings.jina_api_key,
            "openai": settings.openai_api_key,
        },
        "llm": {
            "groq": settings.groq_api_key,
            "gemini": settings.gemini_api_key,
            "openai": settings.openai_api_key,
        },
        "rerank": {
            "jina": settings.jina_api_key,
            "cohere": settings.cohere_api_key,
            "lexical": "always",
            "none": "always",
        },
        "vision": {"gemini": settings.gemini_api_key, "none": "always"},
        "ocr": {
            "gemini": settings.gemini_api_key,
            "ocrspace": settings.ocrspace_api_key,
            "none": "always",
        },
    }
    selected = {
        "embedding": settings.embedding_provider,
        "llm": settings.llm_provider,
        "rerank": settings.rerank_provider,
        "vision": settings.vision_provider,
        "ocr": settings.ocr_provider,
    }
    report = {}
    for capability, provider in selected.items():
        key = (requirements.get(capability) or {}).get(provider.lower())
        report[capability] = {
            "provider": provider,
            "configured": bool(key),
        }
    report["web_search"] = {
        "provider": settings.web_search_provider,
        "configured": settings.web_search_enabled,
    }
    return report
