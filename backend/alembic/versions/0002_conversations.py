"""Group chat history into per-user conversations.

Idempotent by design: revision ``0001`` builds the baseline schema from the
SQLAlchemy models, so a freshly migrated database may already contain the
``conversations`` table and the ``query_logs.conversation_id`` column.  Existing
databases (including SQLite development copies) already have ``query_logs``
without that column, which is what this revision adds.

Revision ID: 0002_conversations
Revises: 0001_initial
Create Date: 2026-11-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_conversations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _tables() -> set:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if "users" not in _tables():
        raise RuntimeError("Run revision 0001_initial before 0002_conversations.")

    if "conversations" not in _tables():
        op.create_table(
            "conversations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False, server_default="New chat"),
            sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_conversations_id", "conversations", ["id"])
        op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
        op.create_index("ix_conversations_updated_at", "conversations", ["updated_at"])

    if "query_logs" in _tables() and "conversation_id" not in _columns("query_logs"):
        with op.batch_alter_table("query_logs") as batch:
            batch.add_column(sa.Column("conversation_id", sa.Integer(), nullable=True))
            batch.create_index("ix_query_logs_conversation_id", ["conversation_id"])
            batch.create_foreign_key(
                "fk_query_logs_conversation_id",
                "conversations",
                ["conversation_id"],
                ["id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    if "query_logs" in _tables() and "conversation_id" in _columns("query_logs"):
        with op.batch_alter_table("query_logs") as batch:
            batch.drop_constraint("fk_query_logs_conversation_id", type_="foreignkey")
            batch.drop_index("ix_query_logs_conversation_id")
            batch.drop_column("conversation_id")

    if "conversations" in _tables():
        op.drop_index("ix_conversations_updated_at", table_name="conversations")
        op.drop_index("ix_conversations_user_id", table_name="conversations")
        op.drop_index("ix_conversations_id", table_name="conversations")
        op.drop_table("conversations")
