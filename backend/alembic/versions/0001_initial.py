"""Initial cloud schema: unified users, documents, chunks, jobs, graph, telemetry.

Creates the complete schema for a fresh Supabase PostgreSQL database, enables
pgvector, and adds the HNSW + full-text indexes used by hybrid retrieval.
Existing legacy data is imported with `python scripts/import_legacy_sqlite.py`
before running the application (see DEPLOYMENT.md).

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-20
"""

from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Baseline schema is generated from the SQLAlchemy models exactly once.
    # All future changes must be new Alembic revisions, never create_all().
    import app.models  # noqa: F401
    from app.database import Base

    Base.metadata.create_all(bind=bind, checkfirst=True)

    if dialect == "postgresql":
        dimensions = int(os.getenv("EMBEDDING_DIMENSIONS", "768"))
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
            f"ON chunks USING hnsw ((embedding::vector({dimensions})) vector_cosine_ops)"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_chunks_content_fts "
            "ON chunks USING gin (to_tsvector('english', content))"
        )
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_documents_user_status "
            "ON documents (user_id, status)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    import app.models  # noqa: F401
    from app.database import Base

    Base.metadata.drop_all(bind=bind, checkfirst=True)
