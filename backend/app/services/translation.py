"""Translation via the configured hosted LLM (no local translation model)."""

from __future__ import annotations

import logging
import re

from app.config import get_settings
from app.providers.base import ProviderError
from app.providers.registry import get_llm_provider

logger = logging.getLogger(__name__)

_SCRIPTS = [
    ("zh", re.compile(r"[\u4e00-\u9fff]")),
    ("ja", re.compile(r"[\u3040-\u30ff]")),
    ("ko", re.compile(r"[\uac00-\ud7af]")),
    ("ar", re.compile(r"[\u0600-\u06ff]")),
    ("ru", re.compile(r"[\u0400-\u04ff]")),
    ("hi", re.compile(r"[\u0900-\u097f]")),
    ("el", re.compile(r"[\u0370-\u03ff]")),
    ("he", re.compile(r"[\u0590-\u05ff]")),
]


def detect_language(text: str) -> str:
    """Lightweight script-based detection; defaults to English."""
    for code, pattern in _SCRIPTS:
        if pattern.search(text or ""):
            return code
    return "en"


async def translate_text(text: str, source_lang: str, target_lang: str) -> str:
    if not text.strip() or source_lang == target_lang:
        return text
    settings = get_settings()
    try:
        provider = get_llm_provider()
        result = await provider.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a medical translator. Translate faithfully, preserve numbers, "
                        "drug names, units and citations, and return only the translation."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Translate from {source_lang} to {target_lang}:\n\n{text}",
                },
            ],
            temperature=0.0,
            max_tokens=min(settings.llm_max_tokens, 1200),
        )
        translated = result.text.strip()
        return translated or text
    except ProviderError as exc:
        logger.warning("Translation unavailable, returning original text: %s", exc)
        return text


async def process_multilingual_query(question: str, target_lang: str = "en") -> tuple:
    detected = detect_language(question)
    if detected == target_lang:
        return question, detected
    translated = await translate_text(question, detected, target_lang)
    return translated, detected


async def translate_response(response: str, target_lang: str) -> str:
    if target_lang == "en":
        return response
    return await translate_text(response, "en", target_lang)
