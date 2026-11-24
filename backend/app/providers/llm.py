"""Hosted chat-completion providers using the OpenAI-compatible protocol."""

from __future__ import annotations

import json
import logging
from typing import Optional, Sequence

from app.config import Settings
from app.providers.base import LLMProvider, LLMResult, ProviderError, ProviderNotConfigured
from app.providers.http import request_json

logger = logging.getLogger(__name__)

_REASONING_EFFORTS = {"low", "medium", "high"}


def _is_json_validation_failure(exc: ProviderError) -> bool:
    """True when a provider rejected the request because JSON mode produced no document.

    Groq (and some other OpenAI-compatible providers) answer HTTP 400 with
    ``code=json_validate_failed`` when ``response_format={"type": "json_object"}``
    is set and the model stopped before emitting a complete JSON document — for
    reasoning models that happens whenever the reasoning phase consumes the whole
    completion budget.
    """
    message = str(exc).lower()
    return exc.status_code == 400 and (
        "json_validate_failed" in message
        or "failed to generate json" in message
        or "failed to validate json" in message
    )


class OpenAICompatibleLLM(LLMProvider):
    def __init__(
        self,
        settings: Settings,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        missing_env: str,
    ) -> None:
        if not api_key:
            raise ProviderNotConfigured(name, missing_env)
        self.settings = settings
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def _supports_reasoning_effort(self) -> bool:
        effort = (self.settings.llm_reasoning_effort or "").strip().lower()
        return (
            self.name == "groq"
            and "gpt-oss" in self.model.lower()
            and effort in _REASONING_EFFORTS
        )

    async def complete(
        self,
        messages: Sequence[dict],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: bool = False,
    ) -> LLMResult:
        body = {
            "model": self.model,
            "messages": list(messages),
            "temperature": (
                self.settings.llm_temperature if temperature is None else float(temperature)
            ),
            "max_tokens": int(max_tokens or self.settings.llm_max_tokens),
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self._supports_reasoning_effort():
            # Keeps the reasoning phase short so the JSON document fits the budget.
            body["reasoning_effort"] = self.settings.llm_reasoning_effort.strip().lower()

        payload = await self._post(body, json_mode=json_mode)

        choices = payload.get("choices") or []
        if not choices:
            raise ProviderError(self.name, "response contained no choices")
        content = (choices[0].get("message") or {}).get("content") or ""
        if not content.strip():
            raise ProviderError(self.name, "response contained an empty answer")
        usage = payload.get("usage") or {}
        return LLMResult(
            text=content.strip(),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            model=payload.get("model") or self.model,
            provider=self.name,
        )

    async def _post(self, body: dict, *, json_mode: bool) -> dict:
        request_body = dict(body)
        for attempt in (1, 2):
            try:
                return await request_json(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    provider=self.name,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                    timeout=self.settings.llm_timeout_seconds,
                    retries=self.settings.ai_max_retries,
                )
            except ProviderError as exc:
                # Bounded recovery: strict JSON mode can be incompatible with a
                # reasoning model's token accounting. Retry once without the
                # response_format hint and let the caller parse/validate the text.
                if attempt == 1 and json_mode and _is_json_validation_failure(exc):
                    logger.warning(
                        "provider=%s model=%s rejected strict JSON mode; retrying once "
                        "without response_format",
                        self.name,
                        self.model,
                    )
                    request_body.pop("response_format", None)
                    continue
                raise
        raise ProviderError(self.name, "JSON mode request failed")  # pragma: no cover


def build_llm_provider(settings: Settings) -> LLMProvider:
    provider = settings.llm_provider.strip().lower()
    if provider == "groq":
        return OpenAICompatibleLLM(
            settings,
            name="groq",
            base_url=settings.groq_base_url,
            api_key=settings.groq_api_key,
            model=settings.llm_model,
            missing_env="GROQ_API_KEY",
        )
    if provider == "gemini":
        return OpenAICompatibleLLM(
            settings,
            name="gemini",
            base_url=settings.gemini_base_url.rstrip("/") + "/v1beta/openai",
            api_key=settings.gemini_api_key,
            model=settings.llm_model,
            missing_env="GEMINI_API_KEY",
        )
    if provider == "openai":
        return OpenAICompatibleLLM(
            settings,
            name="openai",
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            missing_env="OPENAI_API_KEY",
        )
    raise ProviderError("llm", f"unsupported LLM_PROVIDER '{provider}'")


def _matching_brace(text: str, start: int) -> int:
    """Index of the brace that closes the object opened at ``start``, or -1."""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def parse_json_object(text: str) -> dict:
    """Parse a JSON object from a model response, tolerating code fences.

    Raises ``ProviderError`` with a diagnostic reason for empty, truncated,
    malformed or non-object output so callers never silently accept invalid
    structured data.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise ProviderError("llm", "model returned an empty response where JSON was required")
    if cleaned.startswith("```"):
        if cleaned.count("```") >= 2:
            cleaned = cleaned.split("```", 2)[1]
        else:
            cleaned = cleaned[3:]
        if cleaned.lstrip().lower().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    cleaned = cleaned.strip().strip("`").strip()
    if not cleaned:
        raise ProviderError("llm", "model returned an empty JSON code block")
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        start = cleaned.find("{")
        if start == -1:
            raise ProviderError(
                "llm", "model response contained no JSON object"
            ) from exc
        end = _matching_brace(cleaned, start)
        if end == -1:
            raise ProviderError(
                "llm", "model JSON response was truncated before the object closed"
            ) from exc
        try:
            parsed = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as inner:
            raise ProviderError(
                "llm", f"model returned malformed JSON ({inner.msg})"
            ) from inner
    if not isinstance(parsed, dict):
        raise ProviderError(
            "llm", f"model JSON response was a {type(parsed).__name__}, expected an object"
        )
    return parsed
