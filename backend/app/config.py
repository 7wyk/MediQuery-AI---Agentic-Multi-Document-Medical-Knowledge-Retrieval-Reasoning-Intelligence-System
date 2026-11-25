"""Central configuration for MediQuery AI.

Supabase PostgreSQL is the only supported database.
Supabase Storage is the only supported object-storage backend.
All environments must provide these services explicitly.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # General
    app_name: str = "MediQuery AI API"
    api_version: str = "2.0.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Supabase PostgreSQL only (no default/fallback)
    database_url: str = Field(..., min_length=1)
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800
    db_echo: bool = False

    # Supabase Storage only (no local storage fallback)
    supabase_url: str = Field(..., min_length=1)
    supabase_service_role_key: str = Field(..., min_length=1)
    supabase_storage_bucket: str = "mediquery-documents"
    storage_backend: Literal["supabase"] = "supabase"
    signed_url_expires_seconds: int = 3600

    # Authentication: persistent secret required in every environment
    jwt_secret: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # HTTP / CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    cors_dev_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
    rate_limit_per_minute: int = 90
    rate_limit_upload_per_minute: int = 12
    request_timeout_seconds: int = 120

    # Ingestion
    max_upload_mb: int = 25
    max_files_per_request: int = 5
    max_document_pages: int = 400
    max_chunks_per_document: int = 4000
    max_image_analysis_per_document: int = 15
    max_ocr_pages: int = 25
    enable_image_analysis: bool = True
    chunk_size: int = 900
    chunk_overlap: int = 120

    # Hosted AI providers
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    jina_api_key: str = ""
    jina_base_url: str = "https://api.jina.ai/v1"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    cohere_api_key: str = ""
    cohere_base_url: str = "https://api.cohere.com"

    # Embeddings
    embedding_provider: str = "gemini"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    embedding_batch_size: int = 32

    # LLM
    llm_provider: str = "groq"
    llm_model: str = "openai/gpt-oss-120b"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1400
    llm_timeout_seconds: int = 60
    llm_json_max_tokens: int = 1600
    llm_reasoning_effort: str = "low"

    # Reranking
    rerank_provider: str = "jina"
    rerank_model: str = "jina-reranker-v2-base-multilingual"
    rerank_top_n: int = 8
    min_rerank_score: float = 0.15

    # OCR / vision
    ocr_provider: str = "gemini"
    ocrspace_api_key: str = ""
    ocrspace_base_url: str = "https://api.ocr.space"
    vision_provider: str = "gemini"
    vision_model: str = "gemini-3.6-flash"
    ai_request_timeout_seconds: int = 60
    ai_max_retries: int = 2

    # Retrieval
    retrieval_top_k: int = 6
    retrieval_candidates: int = 30
    keyword_candidates: int = 30
    rrf_k: int = 60
    evidence_min_coverage: float = 0.5

    # Agentic RAG
    agent_max_attempts: int = 2
    enable_query_transform: bool = True
    max_subqueries: int = 3
    enable_claim_verification: bool = True
    medical_domain_llm_check: bool = True
    medical_domain_threshold: float = 0.3

    # Trusted medical web search
    web_search_enabled: bool = False
    web_search_provider: str = "europepmc"
    web_search_max_results: int = 5
    web_search_timeout_seconds: int = 15
    web_search_allowed_domains: str = (
        "europepmc.org,pubmed.ncbi.nlm.nih.gov,ncbi.nlm.nih.gov,"
        "nih.gov,who.int,cdc.gov"
    )

    # Graph RAG
    enable_graph_rag: bool = True
    graph_max_hops: int = 2
    graph_max_entities: int = 40

    # Background jobs
    background_worker_enabled: bool = True
    job_poll_interval_seconds: float = 2.0
    job_max_attempts: int = 3
    worker_concurrency: int = 2
    worker_token: str = ""
    job_stale_seconds: int = 900

    # Observability
    cost_llm_input_per_1m: float = 0.0
    cost_llm_output_per_1m: float = 0.0
    cost_embedding_per_1m: float = 0.0
    cost_rerank_per_1k: float = 0.0
    evaluation_enabled: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    @property
    def is_testing(self) -> bool:
        return self.environment.strip().lower() in {"test", "testing"}

    @property
    def uses_postgres(self) -> bool:
        try:
            url = make_url(self.database_url)
            return (
                url.get_backend_name() == "postgresql"
                and bool(url.host)
                and bool(url.database)
            )
        except Exception:
            return False

    @property
    def cors_allow_list(self) -> List[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def cors_origin_regex(self) -> str:
        return "" if self.is_production else self.cors_dev_origin_regex.strip()

    @property
    def allowed_web_domains(self) -> List[str]:
        return [
            item.strip().lower()
            for item in self.web_search_allowed_domains.split(",")
            if item.strip()
        ]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def public_summary(self) -> dict:
        return {
            "environment": self.environment,
            "database": "supabase-postgresql" if self.uses_postgres else "invalid",
            "storage": "supabase",
            "embedding_provider": self.embedding_provider,
            "embedding_dimensions": self.embedding_dimensions,
            "llm_provider": self.llm_provider,
            "rerank_provider": self.rerank_provider,
            "ocr_provider": self.ocr_provider,
            "vision_provider": self.vision_provider,
            "web_search_enabled": self.web_search_enabled,
            "graph_rag_enabled": self.enable_graph_rag,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def validate_for_startup(settings: Settings) -> None:
    """Fail fast unless Supabase PostgreSQL and Supabase Storage are configured."""
    problems: List[str] = []

    if not settings.uses_postgres:
        problems.append(
            "DATABASE_URL must be a valid Supabase PostgreSQL URL. SQLite is not supported."
        )

    if not settings.supabase_url.startswith("https://"):
        problems.append("SUPABASE_URL must be a valid HTTPS project URL.")

    if not settings.supabase_service_role_key.strip():
        problems.append("SUPABASE_SERVICE_ROLE_KEY is required.")

    if settings.storage_backend != "supabase":
        problems.append("Only Supabase Storage is supported.")

    if not settings.supabase_storage_bucket.strip():
        problems.append("SUPABASE_STORAGE_BUCKET must not be empty.")

    if len(settings.jwt_secret) < 32:
        problems.append("JWT_SECRET must contain at least 32 characters.")

    if settings.is_production:
        if settings.debug:
            problems.append("DEBUG must be false in production.")
        if not settings.cors_allow_list:
            problems.append("CORS_ORIGINS must include the deployed frontend origin.")
        if settings.web_search_enabled and not settings.allowed_web_domains:
            problems.append(
                "WEB_SEARCH_ALLOWED_DOMAINS must not be empty when web search is enabled."
            )

    if settings.embedding_provider not in {"gemini", "openai", "jina"}:
        problems.append(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider}")

    if settings.llm_provider not in {"groq", "gemini", "openai"}:
        problems.append(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")

    if problems:
        raise ConfigurationError(
            "Application configuration validation failed:\n- " + "\n- ".join(problems)
        )

    logger.info(
        "Configuration validated: environment=%s database=Supabase PostgreSQL storage=Supabase",
        settings.environment,
    )
