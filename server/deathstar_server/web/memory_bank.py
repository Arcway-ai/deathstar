from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from deathstar_server.web.database import Database

MAX_MEMORY_CONTENT_CHARS = 10_000


class MemoryBank:
    """SQLite-backed memory bank — stores approved AI responses per repo."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list_memories(self, repo: str | None = None) -> list[dict[str, object]]:
        conn = self._db.get_conn()
        if repo:
            rows = conn.execute(
                "SELECT id, repo, content, source_message_id, source_prompt, tags, created_at "
                "FROM memories WHERE repo = ? ORDER BY created_at DESC",
                (repo,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, repo, content, source_message_id, source_prompt, tags, created_at "
                "FROM memories ORDER BY created_at DESC",
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def save_memory(
        self,
        *,
        repo: str,
        content: str,
        source_message_id: str,
        source_prompt: str,
        tags: list[str],
    ) -> dict[str, object]:
        conn = self._db.get_conn()
        mid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        truncated_content = content[:MAX_MEMORY_CONTENT_CHARS]
        truncated_prompt = source_prompt[:2000]
        truncated_tags = tags[:10]
        conn.execute(
            "INSERT INTO memories "
            "(id, repo, content, source_message_id, source_prompt, tags, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mid, repo, truncated_content, source_message_id, truncated_prompt,
             json.dumps(truncated_tags), now),
        )
        conn.commit()
        return {
            "id": mid,
            "repo": repo,
            "content": truncated_content,
            "source_message_id": source_message_id,
            "source_prompt": truncated_prompt,
            "tags": truncated_tags,
            "created_at": now,
        }

    def delete_memory(self, memory_id: str) -> bool:
        conn = self._db.get_conn()
        cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        return cur.rowcount > 0

    def get_relevant_memories(
        self, repo: str, max_chars: int = 4000, max_count: int = 5,
    ) -> list[dict[str, object]]:
        """Return most recent memories for a repo, fitting within a character budget."""
        conn = self._db.get_conn()
        rows = conn.execute(
            "SELECT id, repo, content, source_message_id, source_prompt, tags, created_at "
            "FROM memories WHERE repo = ? ORDER BY created_at DESC",
            (repo,),
        ).fetchall()

        result: list[dict[str, object]] = []
        total_chars = 0
        for row in rows:
            if len(result) >= max_count:
                break
            content_len = len(row["content"])
            if total_chars + content_len > max_chars:
                break
            result.append(_row_to_dict(row))
            total_chars += content_len
        return result


def _row_to_dict(row) -> dict[str, object]:
    tags_raw = row["tags"]
    try:
        tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
    except (json.JSONDecodeError, TypeError):
        tags = []
    return {
        "id": row["id"],
        "repo": row["repo"],
        "content": row["content"],
        "source_message_id": row["source_message_id"],
        "source_prompt": row["source_prompt"],
        "tags": tags,
        "created_at": row["created_at"],
    }
