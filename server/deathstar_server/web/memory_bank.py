from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Engine
from sqlmodel import Session, select

from deathstar_server.db.models import Memory

MAX_MEMORY_CONTENT_CHARS = 10_000


class MemoryBank:
    """PostgreSQL/SQLite-backed memory bank — stores approved AI responses per repo."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_memories(self, repo: str | None = None) -> list[dict[str, object]]:
        with Session(self._engine) as session:
            stmt = select(Memory)
            if repo:
                stmt = stmt.where(Memory.repo == repo)
            stmt = stmt.order_by(Memory.created_at.desc())
            rows = session.exec(stmt).all()
            return [_model_to_dict(m) for m in rows]

    def save_memory(
        self,
        *,
        repo: str,
        content: str,
        source_message_id: str,
        source_prompt: str,
        tags: list[str],
    ) -> dict[str, object]:
        with Session(self._engine) as session:
            mid = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            truncated_content = content[:MAX_MEMORY_CONTENT_CHARS]
            truncated_prompt = source_prompt[:2000]
            truncated_tags = tags[:10]

            memory = Memory(
                id=mid,
                repo=repo,
                content=truncated_content,
                source_message_id=source_message_id,
                source_prompt=truncated_prompt,
                tags=json.dumps(truncated_tags),
                created_at=now,
            )
            session.add(memory)
            session.commit()

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
        with Session(self._engine) as session:
            memory = session.get(Memory, memory_id)
            if memory is None:
                return False
            session.delete(memory)
            session.commit()
            return True

    def get_relevant_memories(
        self, repo: str, max_chars: int = 4000, max_count: int = 5,
    ) -> list[dict[str, object]]:
        """Return most recent memories for a repo, fitting within a character budget."""
        with Session(self._engine) as session:
            stmt = (
                select(Memory)
                .where(Memory.repo == repo)
                .order_by(Memory.created_at.desc())
            )
            rows = session.exec(stmt).all()

            result: list[dict[str, object]] = []
            total_chars = 0
            for memory in rows:
                if len(result) >= max_count:
                    break
                content_len = len(memory.content)
                if total_chars + content_len > max_chars:
                    break
                result.append(_model_to_dict(memory))
                total_chars += content_len
            return result


def _model_to_dict(memory: Memory) -> dict[str, object]:
    try:
        tags = json.loads(memory.tags) if isinstance(memory.tags, str) else memory.tags
    except (json.JSONDecodeError, TypeError):
        tags = []
    return {
        "id": memory.id,
        "repo": memory.repo,
        "content": memory.content,
        "source_message_id": memory.source_message_id,
        "source_prompt": memory.source_prompt,
        "tags": tags,
        "created_at": memory.created_at,
    }
