"""Apply database migrations.

Production schema changes are managed exclusively by Alembic. This helper is a
thin wrapper so existing instructions (`python init_db.py`) keep working, while
local development never silently creates a divergent schema with
``Base.metadata.create_all``.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    config = Config(str(Path(__file__).with_name("alembic.ini")))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    print(f"Applying migrations to {settings.environment} database...")
    command.upgrade(config, "head")
    print("✓ Database is at the latest migration.")
    if not settings.uses_postgres:
        print("Note: SQLite is for local development only; production uses Supabase PostgreSQL.")


if __name__ == "__main__":
    main()
