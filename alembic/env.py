"""Alembic environment configuration for DeathStar migrations."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

# Import all models so SQLModel.metadata is fully populated
from deathstar_server.db import models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

# Require DEATHSTAR_DATABASE_URL — alembic.ini intentionally has no URL
# so that credentials are never committed to version control.
database_url = os.getenv("DEATHSTAR_DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DEATHSTAR_DATABASE_URL is not set. "
        "Export it before running Alembic, e.g.:\n"
        "  export DEATHSTAR_DATABASE_URL=postgresql://user:pass@host:5432/deathstar"
    )
config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without a live connection."""
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
    """Run migrations in 'online' mode — connects to the database and applies."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
