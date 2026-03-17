from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from deathstar_shared.models import (
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    ProviderName,
    WorkflowKind,
)

logger = logging.getLogger(__name__)

MAX_CONVERSATIONS = 50
MAX_MESSAGES_PER_CONVERSATION = 100
HISTORY_CHAR_LIMIT = 16_000
_UUID_RE = re.compile(r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")


class _Conversation:
    __slots__ = ("id", "repo", "title", "messages", "created_at", "updated_at")

    def __init__(self, *, id: str, repo: str, title: str, created_at: datetime, updated_at: datetime) -> None:
        self.id = id
        self.repo = repo
        self.title = title
        self.messages: list[ConversationMessage] = []
        self.created_at = created_at
        self.updated_at = updated_at


class ConversationStore:
    def __init__(self, persist_dir: Path) -> None:
        self._dir = persist_dir
        self._lock = Lock()
        self._convos: dict[str, _Conversation] = {}
        self._load_from_disk()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_conversations(self, repo: str | None = None) -> list[ConversationSummary]:
        with self._lock:
            convos = self._convos.values()
            if repo:
                convos = [c for c in convos if c.repo == repo]
            return [
                ConversationSummary(
                    id=c.id,
                    repo=c.repo,
                    title=c.title,
                    message_count=len(c.messages),
                    created_at=c.created_at,
                    updated_at=c.updated_at,
                )
                for c in sorted(convos, key=lambda c: c.updated_at, reverse=True)
            ]

    def get_conversation(self, conversation_id: str) -> ConversationDetail | None:
        with self._lock:
            c = self._convos.get(conversation_id)
            if c is None:
                return None
            return ConversationDetail(
                id=c.id,
                repo=c.repo,
                title=c.title,
                messages=list(c.messages),
                created_at=c.created_at,
                updated_at=c.updated_at,
            )

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._lock:
            c = self._convos.pop(conversation_id, None)
            if c is None:
                return False
            self._delete_from_disk(conversation_id)
            return True

    def get_or_create(self, conversation_id: str | None, repo: str) -> str:
        with self._lock:
            if conversation_id and conversation_id in self._convos:
                return conversation_id
            return self._create_locked(repo)

    def add_user_message(self, conversation_id: str, content: str) -> str:
        msg_id = str(uuid.uuid4())
        msg = ConversationMessage(
            id=msg_id,
            role="user",
            content=content,
            timestamp=datetime.now(timezone.utc),
        )
        with self._lock:
            c = self._convos[conversation_id]
            c.messages.append(msg)
            c.updated_at = msg.timestamp
            if len(c.messages) == 1:
                c.title = content[:80]
            self._enforce_message_limit(c)
            self._persist(c)
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
    ) -> str:
        msg_id = str(uuid.uuid4())
        msg = ConversationMessage(
            id=msg_id,
            role="assistant",
            content=content,
            timestamp=datetime.now(timezone.utc),
            workflow=workflow,
            provider=provider,
            model=model,
            duration_ms=duration_ms,
        )
        with self._lock:
            c = self._convos[conversation_id]
            c.messages.append(msg)
            c.updated_at = msg.timestamp
            self._enforce_message_limit(c)
            self._persist(c)
        return msg_id

    def build_history_prompt(self, conversation_id: str) -> str:
        with self._lock:
            c = self._convos.get(conversation_id)
            if c is None or not c.messages:
                return ""

            lines: list[str] = []
            total = 0
            for msg in reversed(c.messages):
                entry = f"{'User' if msg.role == 'user' else 'Assistant'}: {msg.content}"
                if total + len(entry) > HISTORY_CHAR_LIMIT:
                    break
                lines.append(entry)
                total += len(entry)

            if not lines:
                return ""
            lines.reverse()
            return "Conversation history:\n" + "\n\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _create_locked(self, repo: str) -> str:
        if len(self._convos) >= MAX_CONVERSATIONS:
            oldest = min(self._convos.values(), key=lambda c: c.updated_at)
            self._convos.pop(oldest.id)
            self._delete_from_disk(oldest.id)

        cid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        c = _Conversation(id=cid, repo=repo, title="New conversation", created_at=now, updated_at=now)
        self._convos[cid] = c
        self._persist(c)
        return cid

    def _enforce_message_limit(self, c: _Conversation) -> None:
        if len(c.messages) > MAX_MESSAGES_PER_CONVERSATION:
            c.messages = c.messages[-MAX_MESSAGES_PER_CONVERSATION:]

    # ------------------------------------------------------------------
    # Disk persistence
    # ------------------------------------------------------------------

    def _persist(self, c: _Conversation) -> None:
        if not _UUID_RE.match(c.id):
            return
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            data = {
                "id": c.id,
                "repo": c.repo,
                "title": c.title,
                "created_at": c.created_at.isoformat(),
                "updated_at": c.updated_at.isoformat(),
                "messages": [m.model_dump(mode="json") for m in c.messages],
            }
            path = self._dir / f"{c.id}.json"
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            logger.warning("failed to persist conversation %s", c.id, exc_info=True)

    def _delete_from_disk(self, conversation_id: str) -> None:
        if not _UUID_RE.match(conversation_id):
            return
        try:
            path = self._dir / f"{conversation_id}.json"
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("failed to delete conversation file %s", conversation_id, exc_info=True)

    def _load_from_disk(self) -> None:
        if not self._dir.exists():
            return
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                c = _Conversation(
                    id=data["id"],
                    repo=data["repo"],
                    title=data.get("title", "Untitled"),
                    created_at=datetime.fromisoformat(data["created_at"]),
                    updated_at=datetime.fromisoformat(data["updated_at"]),
                )
                for m in data.get("messages", []):
                    c.messages.append(ConversationMessage(**m))
                self._convos[c.id] = c
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning("skipping corrupt conversation file: %s", path, exc_info=True)
