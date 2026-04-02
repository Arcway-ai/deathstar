from __future__ import annotations

from pathlib import Path

from deathstar_server.web.database import Database
from deathstar_server.web.queue_store import QueueStore


def _make_queue_store(tmp_path: Path) -> QueueStore:
    db = Database(tmp_path / "test.db")
    return QueueStore(db)


class TestEnqueue:
    def test_creates_pending_item(self, tmp_path):
        store = _make_queue_store(tmp_path)
        item = store.enqueue(
            conversation_id="conv-1",
            repo="my-repo",
            branch="main",
            message="hello",
            workflow="prompt",
        )
        assert item["id"]
        assert item["status"] == "pending"
        assert item["repo"] == "my-repo"
        assert item["message"] == "hello"
        assert item["conversation_id"] == "conv-1"

    def test_enqueue_with_all_fields(self, tmp_path):
        store = _make_queue_store(tmp_path)
        item = store.enqueue(
            conversation_id="conv-1",
            repo="my-repo",
            branch="feature",
            message="do something",
            workflow="patch",
            model="claude-sonnet",
            system_prompt="you are helpful",
        )
        assert item["workflow"] == "patch"
        assert item["model"] == "claude-sonnet"


class TestListPending:
    def test_lists_pending_items(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        store.enqueue(conversation_id="c1", repo="r1", message="b")
        items = store.list_pending()
        assert len(items) == 2

    def test_filters_by_conversation(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        store.enqueue(conversation_id="c2", repo="r1", message="b")
        items = store.list_pending(conversation_id="c1")
        assert len(items) == 1
        assert items[0]["conversation_id"] == "c1"

    def test_filters_by_repo(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        store.enqueue(conversation_id="c2", repo="r2", message="b")
        items = store.list_pending(repo="r2")
        assert len(items) == 1
        assert items[0]["repo"] == "r2"

    def test_excludes_completed(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        claimed = store.claim_next()
        assert claimed is not None
        store.mark_completed(str(claimed["id"]), "msg-1")
        items = store.list_pending()
        assert len(items) == 0


class TestCancel:
    def test_cancels_pending_item(self, tmp_path):
        store = _make_queue_store(tmp_path)
        item = store.enqueue(conversation_id="c1", repo="r1", message="a")
        assert store.cancel(str(item["id"])) is True
        items = store.list_pending()
        assert len(items) == 0

    def test_cannot_cancel_processing(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        claimed = store.claim_next()
        assert claimed is not None
        assert store.cancel(str(claimed["id"])) is False

    def test_cancel_nonexistent_returns_false(self, tmp_path):
        store = _make_queue_store(tmp_path)
        assert store.cancel("nonexistent") is False


class TestClaimNext:
    def test_claims_oldest_pending(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="first")
        store.enqueue(conversation_id="c1", repo="r1", message="second")
        claimed = store.claim_next()
        assert claimed is not None
        assert claimed["message"] == "first"
        assert claimed["status"] == "processing"

    def test_returns_none_when_empty(self, tmp_path):
        store = _make_queue_store(tmp_path)
        assert store.claim_next() is None

    def test_does_not_reclaim_processing(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="only")
        first = store.claim_next()
        assert first is not None
        second = store.claim_next()
        assert second is None


class TestMarkCompleted:
    def test_marks_as_completed(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        claimed = store.claim_next()
        assert claimed is not None
        store.mark_completed(str(claimed["id"]), "result-msg-1")
        # Should not appear in pending
        assert store.list_pending() == []
        # Verify in DB
        conn = store._db.get_conn()
        row = conn.execute(
            "SELECT status, result_message_id FROM message_queue WHERE id = ?",
            (claimed["id"],),
        ).fetchone()
        assert row["status"] == "completed"
        assert row["result_message_id"] == "result-msg-1"


class TestMarkFailed:
    def test_marks_as_failed(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        claimed = store.claim_next()
        assert claimed is not None
        store.mark_failed(str(claimed["id"]), "something went wrong")
        conn = store._db.get_conn()
        row = conn.execute(
            "SELECT status, error_message FROM message_queue WHERE id = ?",
            (claimed["id"],),
        ).fetchone()
        assert row["status"] == "failed"
        assert row["error_message"] == "something went wrong"


class TestRecoverStale:
    def test_recovers_stuck_items(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="stuck")
        claimed = store.claim_next()
        assert claimed is not None
        # Force started_at to be old
        conn = store._db.get_conn()
        conn.execute(
            "UPDATE message_queue SET started_at = '2020-01-01T00:00:00+00:00' WHERE id = ?",
            (claimed["id"],),
        )
        conn.commit()
        recovered = store.recover_stale(timeout_seconds=1)
        assert recovered == 1
        # Should be claimable again
        reclaimed = store.claim_next()
        assert reclaimed is not None
        assert reclaimed["id"] == claimed["id"]

    def test_does_not_recover_recent(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="fresh")
        store.claim_next()
        recovered = store.recover_stale(timeout_seconds=600)
        assert recovered == 0


class TestForceCancel:
    def test_force_cancels_pending_item(self, tmp_path):
        store = _make_queue_store(tmp_path)
        item = store.enqueue(conversation_id="c1", repo="r1", message="a")
        assert store.force_cancel(str(item["id"])) is True
        assert store.list_pending() == []

    def test_force_cancels_processing_item(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        claimed = store.claim_next()
        assert claimed is not None
        # Unlike cancel(), force_cancel() succeeds on processing items
        assert store.force_cancel(str(claimed["id"])) is True
        assert store.list_pending() == []

    def test_force_cancel_nonexistent_returns_false(self, tmp_path):
        store = _make_queue_store(tmp_path)
        assert store.force_cancel("nonexistent") is False

    def test_force_cancel_completed_returns_false(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        claimed = store.claim_next()
        assert claimed is not None
        store.mark_completed(str(claimed["id"]), "msg-1")
        # Already completed — force_cancel should not match
        assert store.force_cancel(str(claimed["id"])) is False

    def test_mark_completed_noop_after_force_cancel(self, tmp_path):
        """Worker finishing after a force_cancel must not revert status to completed."""
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        claimed = store.claim_next()
        assert claimed is not None
        store.force_cancel(str(claimed["id"]))
        # Worker tries to mark_completed (WHERE status = 'processing' — no match)
        store.mark_completed(str(claimed["id"]), "late-msg")
        conn = store._db.get_conn()
        row = conn.execute(
            "SELECT status FROM message_queue WHERE id = ?", (claimed["id"],)
        ).fetchone()
        assert row["status"] == "cancelled"


class TestHasPending:
    def test_true_when_pending(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        assert store.has_pending() is True

    def test_false_when_empty(self, tmp_path):
        store = _make_queue_store(tmp_path)
        assert store.has_pending() is False

    def test_false_when_all_processing(self, tmp_path):
        store = _make_queue_store(tmp_path)
        store.enqueue(conversation_id="c1", repo="r1", message="a")
        store.claim_next()
        assert store.has_pending() is False
