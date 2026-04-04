from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Engine, func
from sqlmodel import Session, select

from deathstar_server.db.models import Conversation, Message
from deathstar_shared.models import (
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    ProviderName,
    WorkflowKind,
)

HISTORY_CHAR_LIMIT = 16_000


class ConversationStore:
    """PostgreSQL/SQLite-backed conversation store using SQLModel."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_conversations(
        self, repo: str | None = None, branch: str | None = None,
    ) -> list[ConversationSummary]:
        with Session(self._engine) as session:
            # Subquery for message count
            msg_count = (
                select(func.count(Message.id))
                .where(Message.conversation_id == Conversation.id)
                .correlate(Conversation)
                .scalar_subquery()
            )

            stmt = select(Conversation, msg_count.label("message_count"))

            if repo:
                stmt = stmt.where(Conversation.repo == repo)
            if branch:
                stmt = stmt.where(
                    (Conversation.branch == branch) | (Conversation.branch.is_(None))  # type: ignore[union-attr]
                )

            stmt = stmt.order_by(Conversation.updated_at.desc())
            rows = session.exec(stmt).all()  # type: ignore[arg-type]

            return [
                ConversationSummary(
                    id=conv.id,
                    repo=conv.repo,
                    title=conv.title,
                    message_count=count,
                    created_at=conv.created_at,
                    updated_at=conv.updated_at,
                    branch=conv.branch,
                )
                for conv, count in rows
            ]

    def get_conversation(self, conversation_id: str) -> ConversationDetail | None:
        with Session(self._engine) as session:
            conv = session.get(Conversation, conversation_id)
            if conv is None:
                return None

            stmt = (
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.timestamp)
            )
            messages = session.exec(stmt).all()

            return ConversationDetail(
                id=conv.id,
                repo=conv.repo,
                title=conv.title,
                messages=[
                    ConversationMessage(
                        id=m.id,
                        role=m.role,
                        content=m.content,
                        timestamp=m.timestamp,
                        workflow=m.workflow,
                        provider=m.provider,
                        model=m.model,
                        duration_ms=m.duration_ms,
                        agent_blocks=json.loads(m.agent_blocks) if m.agent_blocks else None,
                    )
                    for m in messages
                ],
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                branch=conv.branch,
            )

    def delete_conversation(self, conversation_id: str) -> bool:
        with Session(self._engine) as session:
            conv = session.get(Conversation, conversation_id)
            if conv is None:
                return False
            session.delete(conv)
            session.commit()
            return True

    def get_or_create(
        self, conversation_id: str | None, repo: str, branch: str | None = None,
    ) -> str:
        with Session(self._engine) as session:
            if conversation_id:
                existing = session.get(Conversation, conversation_id)
                if existing:
                    return conversation_id

            now = datetime.now(timezone.utc).isoformat()
            cid = str(uuid.uuid4())
            conv = Conversation(
                id=cid,
                repo=repo,
                title="New conversation",
                created_at=now,
                updated_at=now,
                branch=branch,
            )
            session.add(conv)
            session.commit()
            return cid

    def add_user_message(self, conversation_id: str, content: str) -> str:
        with Session(self._engine) as session:
            msg_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            # Count existing messages *before* adding the new one so the check
            # is independent of SQLAlchemy autoflush behaviour.
            count = session.exec(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conversation_id
                )
            ).one()

            msg = Message(
                id=msg_id,
                conversation_id=conversation_id,
                role="user",
                content=content,
                timestamp=now,
            )
            session.add(msg)

            conv = session.get(Conversation, conversation_id)
            if conv:
                if count == 0:
                    conv.title = content[:80]
                conv.updated_at = now

            session.commit()
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
        with Session(self._engine) as session:
            msg_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            blocks_json = json.dumps(agent_blocks) if agent_blocks else None

            msg = Message(
                id=msg_id,
                conversation_id=conversation_id,
                role="assistant",
                content=content,
                timestamp=now,
                workflow=workflow,
                provider=provider,
                model=model,
                duration_ms=duration_ms,
                agent_blocks=blocks_json,
            )
            session.add(msg)

            conv = session.get(Conversation, conversation_id)
            if conv:
                conv.updated_at = now

            session.commit()
            return msg_id

    def update_session_id(self, conversation_id: str, session_id: str | None) -> None:
        with Session(self._engine) as session:
            conv = session.get(Conversation, conversation_id)
            if conv:
                conv.sdk_session_id = session_id
                session.commit()

    def get_session_id(self, conversation_id: str) -> str | None:
        with Session(self._engine) as session:
            conv = session.get(Conversation, conversation_id)
            if conv is None:
                return None
            return conv.sdk_session_id

    def build_history_prompt(self, conversation_id: str) -> str:
        with Session(self._engine) as session:
            stmt = (
                select(Message.role, Message.content)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.timestamp)
            )
            rows = session.exec(stmt).all()

            if not rows:
                return ""

            lines: list[str] = []
            total = 0
            for role, content in reversed(rows):
                label = "User" if role == "user" else "Assistant"
                entry = f"{label}: {content}"
                if total + len(entry) > HISTORY_CHAR_LIMIT:
                    break
                lines.append(entry)
                total += len(entry)

            if not lines:
                return ""
            lines.reverse()
            return "Conversation history:\n" + "\n\n".join(lines)
