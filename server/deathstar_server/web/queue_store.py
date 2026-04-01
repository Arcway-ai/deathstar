"""SQLite-backed message queue for async agent processing."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from deathstar_server.web.database import Database


class QueueStore:
    """CRUD operations for the message_queue table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def enqueue(
        self,
        *,
        conversation_id: str,
        repo: str,
        branch: str | None = None,
        message: str,
        workflow: str = "prompt",
        model: str | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, object]:
        conn = self._db.get_conn()
        item_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO message_queue "
            "(id, conversation_id, repo, branch, message, workflow, model, "
            "system_prompt, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (item_id, conversation_id, repo, branch, message, workflow,
             model, system_prompt, now),
        )
        conn.commit()
        return {
            "id": item_id,
            "conversation_id": conversation_id,
            "repo": repo,
            "branch": branch,
            "message": message,
            "workflow": workflow,
            "model": model,
            "status": "pending",
            "created_at": now,
        }

    def list_pending(
        self,
        conversation_id: str | None = None,
        repo: str | None = None,
    ) -> list[dict[str, object]]:
        conn = self._db.get_conn()
        clauses = ["status IN ('pending', 'processing')"]
        params: list[object] = []
        if conversation_id:
            clauses.append("conversation_id = ?")
            params.append(conversation_id)
        if repo:
            clauses.append("repo = ?")
            params.append(repo)
        where = " AND ".join(clauses)
        rows = conn.execute(
            f"SELECT id, conversation_id, repo, branch, message, workflow, "
            f"status, created_at FROM message_queue WHERE {where} "
            f"ORDER BY created_at ASC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def cancel(self, item_id: str) -> bool:
        conn = self._db.get_conn()
        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "UPDATE message_queue SET status = 'cancelled', completed_at = ? "
            "WHERE id = ? AND status = 'pending'",
            (now, item_id),
        )
        conn.commit()
        return cur.rowcount > 0

    def claim_next(self, skip_repos_branches: set[tuple[str, str | None]] | None = None) -> dict[str, object] | None:
        """Atomically claim the oldest pending item for processing.

        Items matching any (repo, branch) in skip_repos_branches are skipped.
        """
        conn = self._db.get_conn()
        now = datetime.now(timezone.utc).isoformat()
        # Single atomic UPDATE with subquery
        excludes = ""
        params: list[object] = [now]
        if skip_repos_branches:
            placeholders = []
            for repo, branch in skip_repos_branches:
                if branch is None:
                    placeholders.append("(repo = ? AND branch IS NULL)")
                    params.append(repo)
                else:
                    placeholders.append("(repo = ? AND branch = ?)")
                    params.extend([repo, branch])
            excludes = " AND NOT (" + " OR ".join(placeholders) + ")"
        conn.execute(
            "UPDATE message_queue SET status = 'processing', started_at = ? "
            "WHERE id = ("
            "  SELECT id FROM message_queue "
            f"  WHERE status = 'pending'{excludes} "
            "  ORDER BY created_at ASC LIMIT 1"
            ")",
            params,
        )
        conn.commit()
        claimed = conn.execute(
            "SELECT * FROM message_queue "
            "WHERE status = 'processing' AND started_at = ? "
            "ORDER BY created_at ASC LIMIT 1",
            (now,),
        ).fetchone()
        return dict(claimed) if claimed else None

    def requeue(self, item_id: str) -> None:
        """Return a claimed item back to pending status."""
        conn = self._db.get_conn()
        conn.execute(
            "UPDATE message_queue SET status = 'pending', "
            "started_at = NULL, error_message = NULL, completed_at = NULL "
            "WHERE id = ?",
            (item_id,),
        )
        conn.commit()

    def mark_completed(self, item_id: str, result_message_id: str) -> None:
        conn = self._db.get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE message_queue SET status = 'completed', "
            "result_message_id = ?, completed_at = ? "
            "WHERE id = ? AND status = 'processing'",
            (result_message_id, now, item_id),
        )
        conn.commit()

    def mark_failed(self, item_id: str, error: str) -> None:
        conn = self._db.get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE message_queue SET status = 'failed', "
            "error_message = ?, completed_at = ? "
            "WHERE id = ? AND status = 'processing'",
            (error[:2000], now, item_id),
        )
        conn.commit()

    def recover_stale(self, timeout_seconds: int = 600) -> int:
        """Reset processing items older than timeout back to pending."""
        conn = self._db.get_conn()
        cutoff = datetime.now(timezone.utc).isoformat()
        # Use SQLite datetime() to compare ISO timestamps.
        # Items started more than timeout_seconds ago are considered stale.
        cur = conn.execute(
            "UPDATE message_queue SET status = 'pending', started_at = NULL "
            "WHERE status = 'processing' AND started_at IS NOT NULL "
            "AND datetime(started_at) < datetime(?, ?)",
            (cutoff, f"-{timeout_seconds} seconds"),
        )
        conn.commit()
        return cur.rowcount

    def has_pending(self) -> bool:
        conn = self._db.get_conn()
        row = conn.execute(
            "SELECT 1 FROM message_queue WHERE status = 'pending' LIMIT 1"
        ).fetchone()
        return row is not None
