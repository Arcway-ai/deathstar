from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Engine
from sqlmodel import Session, select

from deathstar_server.db.models import Feedback


class FeedbackStore:
    """PostgreSQL/SQLite-backed store for message-level feedback (thumbs up/down)."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
        with Session(self._engine) as session:
            fid = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            fb = Feedback(
                id=fid,
                message_id=message_id,
                conversation_id=conversation_id,
                kind=kind,
                repo=repo,
                content=content[:10_000],
                prompt=prompt[:2000],
                comment=comment[:1000],
                created_at=now,
            )
            session.add(fb)
            session.commit()

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
        with Session(self._engine) as session:
            stmt = select(Feedback)
            if repo:
                stmt = stmt.where(Feedback.repo == repo)
            if kind:
                stmt = stmt.where(Feedback.kind == kind)
            stmt = stmt.order_by(Feedback.created_at.desc())

            rows = session.exec(stmt).all()
            return [
                {
                    "id": fb.id,
                    "message_id": fb.message_id,
                    "conversation_id": fb.conversation_id,
                    "kind": fb.kind,
                    "repo": fb.repo,
                    "comment": fb.comment,
                    "created_at": fb.created_at,
                }
                for fb in rows
            ]

    def get_feedback_for_message(self, message_id: str) -> dict[str, object] | None:
        with Session(self._engine) as session:
            stmt = (
                select(Feedback)
                .where(Feedback.message_id == message_id)
                .order_by(Feedback.created_at.desc())
                .limit(1)
            )
            fb = session.exec(stmt).first()
            if fb is None:
                return None
            return {
                "id": fb.id,
                "message_id": fb.message_id,
                "kind": fb.kind,
                "repo": fb.repo,
                "comment": fb.comment,
                "created_at": fb.created_at,
            }
