"""FastAPI application entrypoint for MediQuery AI."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings, validate_for_startup
from app.database import SessionLocal, engine
from app.middlewares.http import RateLimitMiddleware, RequestContextMiddleware
from app.providers.registry import provider_status
from app.routes import analytics, auth, chat, documents, internal, tools
from app.services.jobs import worker_loop
from app.services.observability import configure_logging, install_log_filter

settings = get_settings()
configure_logging()
install_log_filter()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate mandatory configuration and prove the Supabase DB is reachable.
    validate_for_startup(settings)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    status_report = provider_status(settings)
    missing = [
        name for name, info in status_report.items()
        if not info.get("configured")
    ]
    if missing:
        logger.warning("Providers not configured: %s", ", ".join(missing))

    stop_event = asyncio.Event()
    worker_task = None

    if settings.background_worker_enabled:
        worker_task = asyncio.create_task(worker_loop(stop_event))
        logger.info("In-process background worker enabled")

    logger.info(
        "MediQuery AI started environment=%s database=Supabase PostgreSQL storage=Supabase",
        settings.environment,
    )
    try:
        yield
    finally:
        stop_event.set()
        if worker_task is not None:
            try:
                await asyncio.wait_for(worker_task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                worker_task.cancel()
        logger.info("MediQuery AI shut down cleanly")


app = FastAPI(
    title="MediQuery AI API",
    description=(
        "Cloud-native medical RAG API: hybrid retrieval, reranking, self-correcting "
        "generation, claim verification, trusted web fallback and knowledge graph."
    ),
    version=settings.api_version,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_list,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization", "Content-Type", "X-Request-ID", "X-Worker-Token"
    ],
    expose_headers=["X-Request-ID", "X-Process-Time"],
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(RateLimitMiddleware)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": "Invalid request.", "errors": exc.errors()[:10]},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled error on %s %s", request.method, request.url.path
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred."},
    )


@app.get("/health")
async def health_check():
    database_ok = True
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("Health check database failure: %s", type(exc).__name__)
        database_ok = False

    return {
        "status": "healthy" if database_ok else "degraded",
        "service": "MediQuery AI API",
        "version": settings.api_version,
        "database": "supabase-postgresql" if database_ok else "unavailable",
        "config": settings.public_summary(),
        "providers": provider_status(settings),
    }


@app.get("/")
async def root():
    return {
        "message": "MediQuery AI API",
        "docs": "/api/docs",
        "health": "/health",
        "version": settings.api_version,
    }


app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(analytics.router)
app.include_router(tools.router)
app.include_router(internal.router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=not settings.is_production,
    )
