"""Alembic environment — ThemisIQ / One For All.

Reads DATABASE_URL from settings so credentials never live in alembic.ini.
Supports both online (connected) and offline (SQL-script) modes.

Usage:
  # Apply all pending migrations:
  DATABASE_URL=postgresql://themisiq:pass@db:5432/themisiq alembic upgrade head

  # Autogenerate a new migration (requires a live PostgreSQL connection):
  DATABASE_URL=... alembic revision --autogenerate -m "describe_change"

  # Generate SQL script without connecting:
  alembic upgrade head --sql
"""
import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Make the app importable when alembic runs from oneforall/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: E402

# Alembic Config object gives access to values in alembic.ini
config = context.config

# Inject DATABASE_URL at runtime (never stored in alembic.ini)
if settings.DATABASE_URL:
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
else:
    raise RuntimeError(
        "DATABASE_URL is not set. Export it before running alembic.\n"
        "  export DATABASE_URL=postgresql://themisiq:pass@localhost:5432/themisiq"
    )

# Configure Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# We do not use SQLAlchemy ORM models — ThemisIQ uses raw psycopg2 SQL.
# Set target_metadata=None; autogenerate will introspect the live DB instead.
target_metadata = None


def run_migrations_offline() -> None:
    """Render migrations as SQL without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
