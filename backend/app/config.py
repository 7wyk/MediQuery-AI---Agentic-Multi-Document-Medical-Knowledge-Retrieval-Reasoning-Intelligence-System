"""Central application configuration.

All configuration is environment driven.  Nothing in this module performs
network calls or loads local models, so importing the application never
depends on third-party credentials being present (except in production, where
``validate_for_startup`` intentionally fails fast).
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """Raised when required production configuration is missing or invalid."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- general
    app_name: str = "MediQuery AI API"
    api_version: str = "2.0.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"

    # --------------------------------------------------------------- database
    # SQLite is accepted only for local development/tests.  Production
    # validation rejects it in favour of Supabase PostgreSQL.
    database_url: str = "sqlite:///./mediquery_dev.db"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800
    db_echo: bool = False

    # ---------------------------------------------------------------- storage
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "mediquery-documents"
    # "supabase" (production) or "local" (development/tests only)
    storage_backend: str = "supabase"
    storage_local_dir: str = "./local_storage"
    signed_url_expires_seconds: int = 3600

    # ------------------------------------------------------------------- auth
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # ------------------------------------------------------------------- http
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    # Extra loopback origins accepted only outside production, so a dev server
    # that Vite moves to another port (5174, 5175, ...) or is opened through
    # 127.0.0.1 instead of localhost still reaches the API.  Never applied in
    # production: production must list its real origins in CORS_ORIGINS.
    cors_dev_origin_regex: str = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
    rate_limit_per_minute: int = 90
    rate_limit_upload_per_minute: int = 12
    request_timeout_seconds: int = 120

    # -------------------------------------------------------------- ingestion
    max_upload_mb: int = 25
    max_files_per_request: int = 5
    max_document_pages: int = 400
    max_chunks_per_document: int = 4000
    max_image_analysis_per_document: int = 15
    max_ocr_pages: int = 25
    enable_image_analysis: bool = True
    chunk_size: int = 900
    chunk_overlap: int = 120

    # -------------------------------------------------------- hosted AI models
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    jina_api_key: str = ""
    jina_base_url: str = "https://api.jina.ai/v1"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    cohere_api_key: str = ""
    cohere_base_url: str = "https://api.cohere.com"

    embedding_provider: str = "gemini"  # gemini | openai | jina
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    embedding_batch_size: int = 32

    llm_provider: str = "groq"  # groq | gemini | openai
    llm_model: str = "openai/gpt-oss-120b"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1400
    llm_timeout_seconds: int = 60
    # Reasoning models count reasoning tokens against max_tokens, so structured
    # (JSON) calls need a budget large enough to survive the reasoning phase.
    llm_json_max_tokens: int = 1600
    llm_reasoning_effort: str = "low"  # low | medium | high (gpt-oss models only)

    rerank_provider: str = "jina"  # jina | cohere | lexical | none
    rerank_model: str = "jina-reranker-v2-base-multilingual"
    rerank_top_n: int = 8

    ocr_provider: str = "gemini"  # gemini | ocrspace | none
    ocrspace_api_key: str = ""
    ocrspace_base_url: str = "https://api.ocr.space"
    vision_provider: str = "gemini"  # gemini | none
    vision_model: str = "gemini-3.6-flash"

    ai_request_timeout_seconds: int = 60
    ai_max_retries: int = 2

    # -------------------------------------------------------------- retrieval
    retrieval_top_k: int = 6
    retrieval_candidates: int = 30
    keyword_candidates: int = 30
    rrf_k: int = 60
    min_rerank_score: float = 0.15
    # Fraction of a question's aspects that must be directly supported before an
    # answer is produced; below 1.0 a partial (honestly labelled) answer is allowed.
    evidence_min_coverage: float = 0.5

    # ----------------------------------------------------------- agentic RAG
    agent_max_attempts: int = 2
    enable_query_transform: bool = True
    max_subqueries: int = 3
    enable_claim_verification: bool = True
    medical_domain_llm_check: bool = True
    medical_domain_threshold: float = 0.3

    # ------------------------------------------------------------- web search
    web_search_enabled: bool = False
    web_search_provider: str = "europepmc"
    web_search_max_results: int = 5
    web_search_timeout_seconds: int = 15
    web_search_allowed_domains: str = (
        "europepmc.org,pubmed.ncbi.nlm.nih.gov,ncbi.nlm.nih.gov,nih.gov,who.int,cdc.gov"
    )

    # ------------------------------------------------------------- graph RAG
    enable_graph_rag: bool = True
    graph_max_hops: int = 2
    graph_max_entities: int = 40

    # ------------------------------------------------------------ background
    background_worker_enabled: bool = True
    job_poll_interval_seconds: float = 2.0
    job_max_attempts: int = 3
    worker_concurrency: int = 2
    worker_token: str = ""
    job_stale_seconds: int = 900

    # ----------------------------------------------------------- observability
    cost_llm_input_per_1m: float = 0.0
    cost_llm_output_per_1m: float = 0.0
    cost_embedding_per_1m: float = 0.0
    cost_rerank_per_1k: float = 0.0
    evaluation_enabled: bool = False

    # ---------------------------------------------------------------- helpers
    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in {"production", "prod"}

    @property
    def is_testing(self) -> bool:
        return self.environment.strip().lower() in {"test", "testing"}

    @property
    def uses_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql", "postgres"))

    @property
    def cors_allow_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def cors_origin_regex(self) -> str:
        """Loopback origin pattern for local development; empty in production."""
        if self.is_production:
            return ""
        return self.cors_dev_origin_regex.strip()

    @property
    def allowed_web_domains(self) -> List[str]:
        return [d.strip().lower() for d in self.web_search_allowed_domains.split(",") if d.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def public_summary(self) -> dict:
        """Non-sensitive configuration summary for the health endpoint."""
        return {
            "environment": self.environment,
            "database": "postgresql" if self.uses_postgres else "sqlite-dev",
            "storage": self.storage_backend,
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
    """Fail fast on unsafe/misconfigured production deployments."""
    problems: List[str] = []

    if settings.is_production:
        if not settings.uses_postgres:
            problems.append("DATABASE_URL must point at Supabase PostgreSQL in production")
        if len(settings.jwt_secret) < 32:
            problems.append("JWT_SECRET must be at least 32 characters in production")
        if settings.storage_backend != "supabase":
            problems.append("STORAGE_BACKEND must be 'supabase' in production")
        if not settings.supabase_url or not settings.supabase_service_role_key:
            problems.append("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        if settings.web_search_enabled and not settings.allowed_web_domains:
            problems.append("WEB_SEARCH_ALLOWED_DOMAINS must not be empty when web search is on")

    if problems:
        raise ConfigurationError("; ".join(problems))

    if not settings.jwt_secret:
        logger.warning(
            "JWT_SECRET is not set; an ephemeral development secret will be used. "
            "Tokens will not survive a restart."
        )
    if settings.storage_backend == "local" and settings.is_production:
        raise ConfigurationError("Local storage is not permitted in production")
    if settings.embedding_provider not in {"gemini", "openai", "jina"}:
        raise ConfigurationError(f"Unsupported EMBEDDING_PROVIDER: {settings.embedding_provider}")
    if settings.llm_provider not in {"groq", "gemini", "openai"}:
        raise ConfigurationError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")
