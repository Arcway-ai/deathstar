"""SQLAlchemy engine creation and configuration."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event


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

    engine = create_engine(database_url, **kwargs)

    if is_sqlite:
        # SQLite doesn't enforce foreign keys by default — enable via PRAGMA
        # so CASCADE deletes (e.g. Conversation → Messages) work correctly.
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine
