"""SQLAlchemy engine creation and configuration."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine


def create_db_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine from a database URL.

    Supports both PostgreSQL (production) and SQLite (testing).
    """
    is_sqlite = database_url.startswith("sqlite")

    kwargs: dict = {}
    if is_sqlite:
        # SQLite: no connection pooling, enable foreign keys
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # PostgreSQL: connection pool tuning
        kwargs["pool_pre_ping"] = True
        kwargs["pool_size"] = 10
        kwargs["max_overflow"] = 20

    return create_engine(database_url, **kwargs)
