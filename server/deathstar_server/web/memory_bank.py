from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

logger = logging.getLogger(__name__)

MAX_MEMORIES = 200
MAX_MEMORY_CONTENT_CHARS = 10_000
_UUID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


class MemoryEntry:
    __slots__ = ("id", "repo", "content", "source_message_id", "source_prompt", "tags", "created_at")

    def __init__(
        self,
        *,
        id: str,
        repo: str,
        content: str,
        source_message_id: str,
        source_prompt: str,
        tags: list[str],
        created_at: datetime,
    ) -> None:
        self.id = id
        self.repo = repo
        self.content = content
        self.source_message_id = source_message_id
        self.source_prompt = source_prompt
        self.tags = tags
        self.created_at = created_at

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "repo": self.repo,
            "content": self.content,
            "source_message_id": self.source_message_id,
            "source_prompt": self.source_prompt,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
        }


class MemoryBank:
    """Persistent memory bank scoped per repo.

    Stores approved AI responses (thumbs-up) as retrievable context for future prompts.
    Token budget strategy:
    - Each memory is truncated to MAX_MEMORY_CONTENT_CHARS on save
    - When building context, we return top N memories (by recency) capped at a char limit
    - The frontend is responsible for injecting memories into the system prompt
    """

    def __init__(self, persist_dir: Path) -> None:
        self._dir = persist_dir
        self._lock = Lock()
        self._entries: dict[str, MemoryEntry] = {}
        self._load_from_disk()

    def list_memories(self, repo: str | None = None) -> list[dict[str, object]]:
        with self._lock:
            entries = self._entries.values()
            if repo:
                entries = [e for e in entries if e.repo == repo]
            return [
                e.to_dict()
                for e in sorted(entries, key=lambda e: e.created_at, reverse=True)
            ]

    def save_memory(
        self,
        *,
        repo: str,
        content: str,
        source_message_id: str,
        source_prompt: str,
        tags: list[str],
    ) -> dict[str, object]:
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            repo=repo,
            content=content[:MAX_MEMORY_CONTENT_CHARS],
            source_message_id=source_message_id,
            source_prompt=source_prompt[:2000],
            tags=tags[:10],
            created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._entries[entry.id] = entry
            self._enforce_limit()
            self._persist(entry)
        return entry.to_dict()

    def delete_memory(self, memory_id: str) -> bool:
        with self._lock:
            entry = self._entries.pop(memory_id, None)
            if entry is None:
                return False
            self._delete_from_disk(memory_id)
            return True

    def get_relevant_memories(self, repo: str, max_chars: int = 4000, max_count: int = 5) -> list[dict[str, object]]:
        """Return most recent memories for a repo, fitting within a character budget."""
        with self._lock:
            repo_entries = [e for e in self._entries.values() if e.repo == repo]
            repo_entries.sort(key=lambda e: e.created_at, reverse=True)

            result: list[dict[str, object]] = []
            total_chars = 0
            for entry in repo_entries:
                if len(result) >= max_count:
                    break
                if total_chars + len(entry.content) > max_chars:
                    break
                result.append(entry.to_dict())
                total_chars += len(entry.content)
            return result

    def _enforce_limit(self) -> None:
        if len(self._entries) > MAX_MEMORIES:
            oldest = min(self._entries.values(), key=lambda e: e.created_at)
            self._entries.pop(oldest.id)
            self._delete_from_disk(oldest.id)

    def _persist(self, entry: MemoryEntry) -> None:
        if not _UUID_RE.match(entry.id):
            return
        try:
            repo_dir = self._dir / entry.repo
            repo_dir.mkdir(parents=True, exist_ok=True)
            path = repo_dir / f"{entry.id}.json"
            path.write_text(json.dumps(entry.to_dict(), indent=2), encoding="utf-8")
        except OSError:
            logger.warning("failed to persist memory %s", entry.id, exc_info=True)

    def _delete_from_disk(self, memory_id: str) -> None:
        if not _UUID_RE.match(memory_id):
            return
        try:
            for repo_dir in self._dir.iterdir():
                if not repo_dir.is_dir():
                    continue
                path = repo_dir / f"{memory_id}.json"
                if path.exists():
                    path.unlink()
                    return
        except OSError:
            logger.warning("failed to delete memory file %s", memory_id, exc_info=True)

    def _load_from_disk(self) -> None:
        if not self._dir.exists():
            return
        for repo_dir in self._dir.iterdir():
            if not repo_dir.is_dir():
                continue
            for path in repo_dir.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    entry = MemoryEntry(
                        id=data["id"],
                        repo=data["repo"],
                        content=data["content"],
                        source_message_id=data.get("source_message_id", ""),
                        source_prompt=data.get("source_prompt", ""),
                        tags=data.get("tags", []),
                        created_at=datetime.fromisoformat(data["created_at"]),
                    )
                    self._entries[entry.id] = entry
                except (json.JSONDecodeError, KeyError, TypeError):
                    logger.warning("skipping corrupt memory file: %s", path, exc_info=True)
