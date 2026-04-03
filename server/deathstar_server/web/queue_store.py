"""Message queue store for async agent processing."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine
from sqlmodel import Session, select

from deathstar_server.db.models import MessageQueue


class QueueStore:
    """CRUD operations for the message_queue table."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

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
        with Session(self._engine) as session:
            item_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()

            item = MessageQueue(
                id=item_id,
                conversation_id=conversation_id,
                repo=repo,
                branch=branch,
                message=message,
                workflow=workflow,
                model=model,
                system_prompt=system_prompt,
                status="pending",
                created_at=now,
            )
            session.add(item)
            session.commit()

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
        with Session(self._engine) as session:
            stmt = select(MessageQueue).where(
                MessageQueue.status.in_(["pending", "processing"])
            )
            if conversation_id:
                stmt = stmt.where(MessageQueue.conversation_id == conversation_id)
            if repo:
                stmt = stmt.where(MessageQueue.repo == repo)
            stmt = stmt.order_by(MessageQueue.created_at.asc())

            rows = session.exec(stmt).all()
            return [
                {
                    "id": item.id,
                    "conversation_id": item.conversation_id,
                    "repo": item.repo,
                    "branch": item.branch,
                    "message": item.message,
                    "workflow": item.workflow,
                    "status": item.status,
                    "created_at": item.created_at,
                }
                for item in rows
            ]

    def cancel(self, item_id: str) -> bool:
        with Session(self._engine) as session:
            item = session.get(MessageQueue, item_id)
            if item is None or item.status != "pending":
                return False
            now = datetime.now(timezone.utc).isoformat()
            item.status = "cancelled"
            item.completed_at = now
            session.commit()
            return True

    def force_cancel(self, item_id: str) -> bool:
        """Cancel a pending or processing item."""
        with Session(self._engine) as session:
            item = session.get(MessageQueue, item_id)
            if item is None or item.status not in ("pending", "processing"):
                return False
            now = datetime.now(timezone.utc).isoformat()
            item.status = "cancelled"
            item.completed_at = now
            session.commit()
            return True

    def claim_next(
        self, skip_repos_branches: set[tuple[str, str | None]] | None = None,
    ) -> dict[str, object] | None:
        """Atomically claim the oldest pending item for processing."""
        with Session(self._engine) as session:
            now = datetime.now(timezone.utc).isoformat()

            # Build the query to find the next pending item
            stmt = (
                select(MessageQueue)
                .where(MessageQueue.status == "pending")
                .order_by(MessageQueue.created_at.asc())
                .limit(1)
            )

            if skip_repos_branches:
                for repo, branch in skip_repos_branches:
                    if branch is None:
                        stmt = stmt.where(
                            ~((MessageQueue.repo == repo) & (MessageQueue.branch.is_(None)))  # type: ignore[union-attr]
                        )
                    else:
                        stmt = stmt.where(
                            ~((MessageQueue.repo == repo) & (MessageQueue.branch == branch))
                        )

            item = session.exec(stmt).first()
            if item is None:
                return None

            item.status = "processing"
            item.started_at = now
            session.commit()
            session.refresh(item)

            return {
                "id": item.id,
                "conversation_id": item.conversation_id,
                "repo": item.repo,
                "branch": item.branch,
                "message": item.message,
                "workflow": item.workflow,
                "model": item.model,
                "system_prompt": item.system_prompt,
                "status": item.status,
                "result_message_id": item.result_message_id,
                "error_message": item.error_message,
                "created_at": item.created_at,
                "started_at": item.started_at,
                "completed_at": item.completed_at,
            }

    def requeue(self, item_id: str) -> None:
        """Return a claimed item back to pending status."""
        with Session(self._engine) as session:
            item = session.get(MessageQueue, item_id)
            if item:
                item.status = "pending"
                item.started_at = None
                item.error_message = None
                item.completed_at = None
                session.commit()

    def mark_completed(self, item_id: str, result_message_id: str) -> None:
        with Session(self._engine) as session:
            item = session.get(MessageQueue, item_id)
            if item and item.status == "processing":
                now = datetime.now(timezone.utc).isoformat()
                item.status = "completed"
                item.result_message_id = result_message_id
                item.completed_at = now
                session.commit()

    def mark_failed(self, item_id: str, error: str) -> None:
        with Session(self._engine) as session:
            item = session.get(MessageQueue, item_id)
            if item and item.status == "processing":
                now = datetime.now(timezone.utc).isoformat()
                item.status = "failed"
                item.error_message = error[:2000]
                item.completed_at = now
                session.commit()

    def recover_stale(self, timeout_seconds: int = 600) -> int:
        """Reset processing items older than timeout back to pending.

        Uses ISO timestamp string comparison which works portably across
        SQLite and PostgreSQL since ISO 8601 strings sort lexicographically.
        """
        with Session(self._engine) as session:
            cutoff = (
                datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
            ).isoformat()

            stmt = (
                select(MessageQueue)
                .where(MessageQueue.status == "processing")
                .where(MessageQueue.started_at.is_not(None))  # type: ignore[union-attr]
                .where(MessageQueue.started_at < cutoff)  # type: ignore[operator]
            )
            stale_items = session.exec(stmt).all()

            for item in stale_items:
                item.status = "pending"
                item.started_at = None

            session.commit()
            return len(stale_items)

    def has_pending(self) -> bool:
        with Session(self._engine) as session:
            stmt = (
                select(MessageQueue.id)
                .where(MessageQueue.status == "pending")
                .limit(1)
            )
            return session.exec(stmt).first() is not None
