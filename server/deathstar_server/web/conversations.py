from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from deathstar_server.web.database import Database
from deathstar_shared.models import (
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    ProviderName,
    WorkflowKind,
)

HISTORY_CHAR_LIMIT = 16_000

_PROTECTED_BRANCHES = frozenset({"main", "master"})


class ConversationStore:
    """SQLite-backed conversation store."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Branch association
    # ------------------------------------------------------------------

    def add_branch(self, conversation_id: str, branch: str) -> None:
        """Associate a branch with a conversation. Idempotent. Skips main/master."""
        if not branch or branch in _PROTECTED_BRANCHES:
            return
        conn = self._db.get_conn()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT OR IGNORE INTO conversation_branches (conversation_id, branch, added_at) "
            "VALUES (?, ?, ?)",
            (conversation_id, branch, now),
        )
        conn.commit()

    def get_branches(self, conversation_id: str) -> list[str]:
        """Return all branches associated with a conversation."""
        conn = self._db.get_conn()
        rows = conn.execute(
            "SELECT branch FROM conversation_branches "
            "WHERE conversation_id = ? ORDER BY added_at",
            (conversation_id,),
        ).fetchall()
        return [r["branch"] for r in rows]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_conversations(
        self, repo: str | None = None, branch: str | None = None,
    ) -> list[ConversationSummary]:
        conn = self._db.get_conn()
        base = (
            "SELECT c.id, c.repo, c.title, c.created_at, c.updated_at, c.branch, "
            "(SELECT COUNT(*) FROM messages WHERE conversation_id = c.id) AS message_count "
            "FROM conversations c"
        )
        conditions: list[str] = []
        params: list[str] = []
        if repo:
            conditions.append("c.repo = ?")
            params.append(repo)
        if branch:
            # Show conversations for this branch AND legacy ones (branch IS NULL)
            conditions.append("(c.branch = ? OR c.branch IS NULL)")
            params.append(branch)

        query = base
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY c.updated_at DESC"

        rows = conn.execute(query, params).fetchall()

        # Batch-load branches for all conversations
        conv_ids = [r["id"] for r in rows]
        branches_map: dict[str, list[str]] = {cid: [] for cid in conv_ids}
        if conv_ids:
            placeholders = ",".join("?" * len(conv_ids))
            branch_rows = conn.execute(
                f"SELECT conversation_id, branch FROM conversation_branches "
                f"WHERE conversation_id IN ({placeholders}) ORDER BY added_at",
                conv_ids,
            ).fetchall()
            for br in branch_rows:
                branches_map[br["conversation_id"]].append(br["branch"])

        return [
            ConversationSummary(
                id=r["id"],
                repo=r["repo"],
                title=r["title"],
                message_count=r["message_count"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                branch=r["branch"],
                branches=branches_map.get(r["id"], []),
            )
            for r in rows
        ]

    def get_conversation(self, conversation_id: str) -> ConversationDetail | None:
        conn = self._db.get_conn()
        c = conn.execute(
            "SELECT id, repo, title, created_at, updated_at, branch "
            "FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if c is None:
            return None
        msg_rows = conn.execute(
            "SELECT id, role, content, timestamp, workflow, provider, model, duration_ms, agent_blocks "
            "FROM messages WHERE conversation_id = ? ORDER BY timestamp",
            (conversation_id,),
        ).fetchall()
        branches = self.get_branches(conversation_id)
        return ConversationDetail(
            id=c["id"],
            repo=c["repo"],
            title=c["title"],
            messages=[
                ConversationMessage(
                    id=m["id"],
                    role=m["role"],
                    content=m["content"],
                    timestamp=m["timestamp"],
                    workflow=m["workflow"],
                    provider=m["provider"],
                    model=m["model"],
                    duration_ms=m["duration_ms"],
                    agent_blocks=json.loads(m["agent_blocks"]) if m["agent_blocks"] else None,
                )
                for m in msg_rows
            ],
            created_at=c["created_at"],
            updated_at=c["updated_at"],
            branch=c["branch"],
            branches=branches,
        )

    def delete_conversation(self, conversation_id: str) -> bool:
        conn = self._db.get_conn()
        cur = conn.execute(
            "DELETE FROM conversations WHERE id = ?", (conversation_id,)
        )
        conn.commit()
        return cur.rowcount > 0

    def get_or_create(
        self, conversation_id: str | None, repo: str, branch: str | None = None,
    ) -> str:
        conn = self._db.get_conn()
        if conversation_id:
            row = conn.execute(
                "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if row:
                # Auto-associate branch with existing conversation
                if branch:
                    self.add_branch(conversation_id, branch)
                return conversation_id

        cid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO conversations (id, repo, title, created_at, updated_at, branch) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (cid, repo, "New conversation", now, now, branch),
        )
        conn.commit()
        # Auto-associate branch with new conversation
        if branch:
            self.add_branch(cid, branch)
        return cid

    def add_user_message(self, conversation_id: str, content: str) -> str:
        conn = self._db.get_conn()
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (msg_id, conversation_id, "user", content, now),
        )
        # Update title to first user message if this is the first message
        count = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]
        if count == 1:
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (content[:80], now, conversation_id),
            )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        conn.commit()
        return msg_id

    def add_assistant_message(
        self,
        conversation_id: str,
        content: str,
        *,
        workflow: WorkflowKind,
        provider: ProviderName,
        model: str,
        duration_ms: int,
        agent_blocks: list[dict] | None = None,
    ) -> str:
        conn = self._db.get_conn()
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        blocks_json = json.dumps(agent_blocks) if agent_blocks else None
        conn.execute(
            "INSERT INTO messages "
            "(id, conversation_id, role, content, timestamp, workflow, provider, model, duration_ms, agent_blocks) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (msg_id, conversation_id, "assistant", content, now, workflow, provider, model, duration_ms, blocks_json),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        conn.commit()
        return msg_id

    def update_session_id(self, conversation_id: str, session_id: str | None) -> None:
        conn = self._db.get_conn()
        conn.execute(
            "UPDATE conversations SET sdk_session_id = ? WHERE id = ?",
            (session_id, conversation_id),
        )
        conn.commit()

    def get_session_id(self, conversation_id: str) -> str | None:
        conn = self._db.get_conn()
        row = conn.execute(
            "SELECT sdk_session_id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        return row["sdk_session_id"]

    def build_history_prompt(self, conversation_id: str) -> str:
        conn = self._db.get_conn()
        rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE conversation_id = ? ORDER BY timestamp",
            (conversation_id,),
        ).fetchall()
        if not rows:
            return ""

        lines: list[str] = []
        total = 0
        for row in reversed(rows):
            label = "User" if row["role"] == "user" else "Assistant"
            entry = f"{label}: {row['content']}"
            if total + len(entry) > HISTORY_CHAR_LIMIT:
                break
            lines.append(entry)
            total += len(entry)

        if not lines:
            return ""
        lines.reverse()
        return "Conversation history:\n" + "\n\n".join(lines)
