from __future__ import annotations

import uuid
from datetime import datetime, timezone

from deathstar_server.web.database import Database


class FeedbackStore:
    """SQLite-backed store for message-level feedback (thumbs up/down)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save_feedback(
        self,
        *,
        message_id: str,
        conversation_id: str | None = None,
        kind: str,
        repo: str,
        content: str = "",
        prompt: str = "",
        comment: str = "",
    ) -> dict[str, object]:
        conn = self._db.get_conn()
        fid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO feedback "
            "(id, message_id, conversation_id, kind, repo, content, prompt, comment, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (fid, message_id, conversation_id, kind, repo,
             content[:10_000], prompt[:2000], comment[:1000], now),
        )
        conn.commit()
        return {
            "id": fid,
            "message_id": message_id,
            "kind": kind,
            "repo": repo,
            "created_at": now,
        }

    def list_feedback(
        self, repo: str | None = None, kind: str | None = None,
    ) -> list[dict[str, object]]:
        conn = self._db.get_conn()
        query = (
            "SELECT id, message_id, conversation_id, kind, repo, comment, created_at "
            "FROM feedback"
        )
        params: list[str] = []
        conditions: list[str] = []
        if repo:
            conditions.append("repo = ?")
            params.append(repo)
        if kind:
            conditions.append("kind = ?")
            params.append(kind)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_feedback_for_message(self, message_id: str) -> dict[str, object] | None:
        conn = self._db.get_conn()
        row = conn.execute(
            "SELECT id, message_id, kind, repo, comment, created_at "
            "FROM feedback WHERE message_id = ? ORDER BY created_at DESC LIMIT 1",
            (message_id,),
        ).fetchone()
        return dict(row) if row else None
