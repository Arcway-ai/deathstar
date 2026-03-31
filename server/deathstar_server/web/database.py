"""SQLite database for DeathStar — conversations, memories, feedback, usage."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 3

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sdk_session_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_conversations_repo ON conversations(repo);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    workflow TEXT,
    provider TEXT,
    model TEXT,
    duration_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    agent_blocks TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, timestamp);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    content TEXT NOT NULL,
    source_message_id TEXT DEFAULT '',
    source_prompt TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_repo ON memories(repo, created_at DESC);

CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    conversation_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('thumbs_up', 'thumbs_down')),
    repo TEXT NOT NULL,
    content TEXT DEFAULT '',
    prompt TEXT DEFAULT '',
    comment TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_repo ON feedback(repo, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_message ON feedback(message_id);

CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT,
    message_id TEXT,
    repo TEXT NOT NULL,
    workflow TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    duration_ms INTEGER NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    persona TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_repo ON usage_log(repo, created_at DESC);
"""


class Database:
    """Central SQLite database for DeathStar persistence."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._local = threading.local()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    @property
    def path(self) -> Path:
        return self._path

    def get_conn(self) -> sqlite3.Connection:
        """Get a thread-local connection with WAL mode and foreign keys enabled."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _ensure_schema(self) -> None:
        conn = self.get_conn()
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cur.fetchone() is None:
            conn.executescript(_SCHEMA_SQL)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,)
            )
            conn.commit()
            logger.info("created database schema v%d at %s", _SCHEMA_VERSION, self._path)
        else:
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            current = row[0] if row else 0
            if current < _SCHEMA_VERSION:
                self._run_migrations(conn, current)

    def _run_migrations(self, conn: sqlite3.Connection, from_version: int) -> None:
        if from_version < 2:
            conn.execute("ALTER TABLE conversations ADD COLUMN sdk_session_id TEXT")
            logger.info("migration v2: added sdk_session_id column to conversations")

        if from_version < 3:
            conn.execute("ALTER TABLE messages ADD COLUMN agent_blocks TEXT")
            logger.info("migration v3: added agent_blocks column to messages")

        conn.execute(
            "UPDATE schema_version SET version = ?", (_SCHEMA_VERSION,)
        )
        conn.commit()
        logger.info("migrated database from v%d to v%d", from_version, _SCHEMA_VERSION)

