"""Tests for branch-aware conversation queries and database migration v4."""

from __future__ import annotations

import sqlite3

import pytest

from deathstar_server.web.database import Database


# ---------------------------------------------------------------------------
# Database migration v3 → v4
# ---------------------------------------------------------------------------


class TestMigrationV4:
    def test_migrates_from_v3_adding_branch_column(self, tmp_path):
        """Simulate a v3 database and verify migration to v4 adds branch column."""
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # Create a minimal v3 schema
        conn.executescript("""
            CREATE TABLE schema_version (version INTEGER NOT NULL);
            INSERT INTO schema_version (version) VALUES (3);

            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sdk_session_id TEXT
            );
            CREATE INDEX idx_conversations_repo ON conversations(repo);

            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
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

            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                repo TEXT NOT NULL,
                content TEXT NOT NULL,
                source_message_id TEXT DEFAULT '',
                source_prompt TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL
            );

            CREATE TABLE feedback (
                id TEXT PRIMARY KEY,
                message_id TEXT NOT NULL,
                conversation_id TEXT,
                kind TEXT NOT NULL,
                repo TEXT NOT NULL,
                content TEXT DEFAULT '',
                prompt TEXT DEFAULT '',
                comment TEXT DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE usage_log (
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
        """)

        # Insert a legacy conversation (no branch column)
        conn.execute(
            "INSERT INTO conversations (id, repo, title, created_at, updated_at) "
            "VALUES ('conv-1', 'my-repo', 'test', '2026-01-01', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        # Open via Database — should trigger migration
        db = Database(db_path)
        conn = db.get_conn()

        # Verify schema version
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        assert row[0] == 4

        # Verify branch column exists
        conv = conn.execute("SELECT id, branch FROM conversations WHERE id = 'conv-1'").fetchone()
        assert conv is not None
        assert conv["branch"] is None  # Legacy row has NULL branch

        # Verify index exists
        indices = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_conversations_repo_branch'"
        ).fetchone()
        assert indices is not None

    def test_fresh_install_has_branch_column(self, tmp_path):
        """A fresh database should include the branch column from the start."""
        db_path = tmp_path / "fresh.db"
        db = Database(db_path)
        conn = db.get_conn()

        # Verify branch column exists on fresh install
        conn.execute(
            "INSERT INTO conversations (id, repo, title, created_at, updated_at, branch) "
            "VALUES ('fresh-1', 'repo', 'test', '2026-01-01', '2026-01-01', 'feature/x')"
        )
        conn.commit()

        row = conn.execute("SELECT branch FROM conversations WHERE id = 'fresh-1'").fetchone()
        assert row["branch"] == "feature/x"


# ---------------------------------------------------------------------------
# Conversation store branch-aware queries
# ---------------------------------------------------------------------------


class TestConversationStoreBranch:
    @pytest.fixture()
    def store(self, tmp_path):
        from deathstar_server.web.conversations import ConversationStore
        db = Database(tmp_path / "test.db")
        return ConversationStore(db)

    def test_get_or_create_stores_branch(self, store):
        cid = store.get_or_create(None, "my-repo", branch="feature/auth")
        detail = store.get_conversation(cid)
        assert detail is not None
        assert detail.branch == "feature/auth"

    def test_get_or_create_null_branch(self, store):
        cid = store.get_or_create(None, "my-repo", branch=None)
        detail = store.get_conversation(cid)
        assert detail is not None
        assert detail.branch is None

    def test_list_conversations_filters_by_branch(self, store):
        cid_main = store.get_or_create(None, "my-repo", branch="main")
        store.add_user_message(cid_main, "on main")

        cid_feature = store.get_or_create(None, "my-repo", branch="feature/auth")
        store.add_user_message(cid_feature, "on feature")

        cid_legacy = store.get_or_create(None, "my-repo", branch=None)
        store.add_user_message(cid_legacy, "legacy no branch")

        # Filter by branch=main → should get main + legacy (NULL)
        main_convos = store.list_conversations("my-repo", "main")
        main_ids = {c.id for c in main_convos}
        assert cid_main in main_ids
        assert cid_legacy in main_ids
        assert cid_feature not in main_ids

        # Filter by branch=feature/auth → should get feature + legacy (NULL)
        feat_convos = store.list_conversations("my-repo", "feature/auth")
        feat_ids = {c.id for c in feat_convos}
        assert cid_feature in feat_ids
        assert cid_legacy in feat_ids
        assert cid_main not in feat_ids

    def test_list_conversations_no_branch_filter_returns_all(self, store):
        cid1 = store.get_or_create(None, "my-repo", branch="main")
        store.add_user_message(cid1, "msg1")

        cid2 = store.get_or_create(None, "my-repo", branch="feature/x")
        store.add_user_message(cid2, "msg2")

        cid3 = store.get_or_create(None, "my-repo", branch=None)
        store.add_user_message(cid3, "msg3")

        all_convos = store.list_conversations("my-repo", None)
        all_ids = {c.id for c in all_convos}
        assert {cid1, cid2, cid3} == all_ids

    def test_conversation_branch_returned_in_summary(self, store):
        cid = store.get_or_create(None, "my-repo", branch="bugfix/login")
        store.add_user_message(cid, "hello")

        convos = store.list_conversations("my-repo")
        assert len(convos) == 1
        assert convos[0].branch == "bugfix/login"
