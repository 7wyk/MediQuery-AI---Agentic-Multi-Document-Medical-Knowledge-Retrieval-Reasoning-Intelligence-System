"""Apply Alembic migrations to the configured Supabase PostgreSQL database."""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from app.config import get_settings, validate_for_startup


def main() -> None:
    settings = get_settings()
    validate_for_startup(settings)

    parsed_url = make_url(settings.database_url)
    if parsed_url.get_backend_name() != "postgresql":
        raise RuntimeError("Only Supabase PostgreSQL is supported. SQLite is disabled.")

    config = Config(str(Path(__file__).with_name("alembic.ini")))
    config.set_main_option(
        "sqlalchemy.url",
        parsed_url.set(drivername="postgresql+psycopg")
        .render_as_string(hide_password=False)
        .replace("%", "%%"),
    )

    print("Applying Alembic migrations to Supabase PostgreSQL...")
    command.upgrade(config, "head")
    print("Database schema is up to date.")


if __name__ == "__main__":
    main()
