"""SQLAlchemy engine/session setup for Supabase PostgreSQL only.

SQLite is intentionally unsupported. Use Alembic for all schema changes.
"""
from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

try:
    parsed_url = make_url(settings.database_url.strip())

    if parsed_url.get_backend_name() != "postgresql":
        raise ValueError("Only PostgreSQL is supported; SQLite is disabled.")

    if not parsed_url.host or not parsed_url.database:
        raise ValueError("PostgreSQL URL must include a host and database name.")

    # Use Psycopg 3 explicitly, regardless of whether Supabase supplied
    # postgresql:// or postgresql+psycopg://.
    DATABASE_URL = parsed_url.set(drivername="postgresql+psycopg")

except Exception as exc:
    raise RuntimeError(
        "Invalid DATABASE_URL. Configure a valid Supabase PostgreSQL connection URL."
    ) from exc

engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_recycle=settings.db_pool_recycle,
    pool_timeout=30,
    echo=settings.db_echo,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

Base = declarative_base()


def get_db() -> Generator:
    """Yield a SQLAlchemy session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def is_postgres() -> bool:
    """This engine can only be constructed for PostgreSQL."""
    return engine.dialect.name == "postgresql"
