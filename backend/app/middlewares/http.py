"""Request id, timing and rate limiting middleware."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings
from app.services.observability import new_request_id, request_id_var

logger = logging.getLogger(__name__)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming[:64] if incoming and incoming.isprintable() else new_request_id()
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        elapsed = time.perf_counter() - started
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{elapsed:.4f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path not in {"/health", "/"}:
            logger.info(
                "request completed method=%s path=%s status=%s duration_ms=%s",
                request.method,
                request.url.path,
                response.status_code,
                int(elapsed * 1000),
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory sliding-window limiter.

    Suitable for a single Render instance.  For horizontally scaled deployments
    put the limiter in a shared store (e.g. Upstash/Redis) - documented in the
    deployment guide.
    """

    def __init__(self, app) -> None:  # noqa: ANN001
        super().__init__(app)
        self.hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self.settings = get_settings()

    def _client_key(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        path = request.url.path
        if request.method == "OPTIONS" or path in {"/health", "/"}:
            return await call_next(request)

        is_upload = path.endswith("/documents/upload")
        limit = (
            self.settings.rate_limit_upload_per_minute
            if is_upload
            else self.settings.rate_limit_per_minute
        )
        bucket = "upload" if is_upload else "api"
        key = (self._client_key(request), bucket)
        now = time.monotonic()
        window = self.hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Too many requests. Please slow down and retry shortly."},
                headers={"Retry-After": "60"},
            )
        window.append(now)
        return await call_next(request)
