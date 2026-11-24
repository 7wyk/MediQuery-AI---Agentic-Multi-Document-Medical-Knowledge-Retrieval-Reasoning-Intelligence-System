"""Shared resilient HTTP helper for hosted AI providers."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

import httpx

from app.providers.base import ProviderError

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


async def request_json(
    method: str,
    url: str,
    *,
    provider: str,
    headers: Optional[dict] = None,
    json: Any = None,
    data: Any = None,
    params: Optional[dict] = None,
    timeout: float = 60.0,
    retries: int = 2,
    files: Any = None,
) -> Any:
    """Perform an HTTP request with bounded retries and safe error messages.

    Response bodies are used for diagnostics in logs only, never returned to an
    end user, and API keys are never logged.
    """
    last_error: Optional[ProviderError] = None
    attempts = max(1, retries + 1)

    for attempt in range(attempts):
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    data=data,
                    params=params,
                    files=files,
                )
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "provider request provider=%s method=%s status=%s latency_ms=%s attempt=%s",
                provider,
                method,
                response.status_code,
                elapsed_ms,
                attempt + 1,
            )

            if response.status_code < 400:
                if not response.content:
                    return {}
                try:
                    return response.json()
                except ValueError as exc:
                    raise ProviderError(provider, "returned a non-JSON response") from exc

            body_preview = response.text[:500].replace("\n", " ")
            retryable = response.status_code in _RETRYABLE_STATUS
            last_error = ProviderError(
                provider,
                f"HTTP {response.status_code}: {body_preview}",
                status_code=response.status_code,
                retryable=retryable,
            )
            logger.warning(
                "provider error provider=%s status=%s body=%s",
                provider,
                response.status_code,
                body_preview,
            )
            if not retryable:
                raise last_error

        except httpx.TimeoutException as exc:
            last_error = ProviderError(provider, "request timed out", retryable=True)
            logger.warning("provider timeout provider=%s attempt=%s", provider, attempt + 1)
            del exc
        except httpx.HTTPError as exc:
            last_error = ProviderError(provider, f"network error: {type(exc).__name__}", retryable=True)

        if attempt < attempts - 1:
            await asyncio.sleep(min(2 ** attempt * 0.75, 6.0))

    assert last_error is not None
    raise last_error
