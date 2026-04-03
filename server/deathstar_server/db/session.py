"""Session factory and FastAPI dependency for database access."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine
from sqlmodel import Session

_engine: Engine | None = None


def init_engine(engine: Engine) -> None:
    """Set the global engine. Called once at startup from app_state."""
    global _engine
    _engine = engine


def get_engine() -> Engine:
    """Return the global engine. Raises if not initialized."""
    if _engine is None:
        raise RuntimeError("Database engine not initialized — call init_engine() first")
    return _engine


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped session."""
    with Session(get_engine()) as session:
        yield session


def create_session() -> Session:
    """Create a session for use outside of FastAPI request context.

    The caller is responsible for closing the session.
    """
    return Session(get_engine())
