from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Engine
from sqlmodel import Session, select

from deathstar_server.db.models import Document

MAX_DOCUMENT_CONTENT_CHARS = 200_000


class DocumentStore:
    """PostgreSQL/SQLite-backed document store — persists documents per repo."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def list_documents(
        self, repo: str | None = None, document_type: str | None = None,
    ) -> list[dict[str, object]]:
        with Session(self._engine) as session:
            stmt = select(Document)
            if repo:
                stmt = stmt.where(Document.repo == repo)
            if document_type:
                stmt = stmt.where(Document.document_type == document_type)
            stmt = stmt.order_by(Document.updated_at.desc())
            rows = session.exec(stmt).all()
            return [_model_to_dict(d) for d in rows]

    def get_document(self, document_id: str) -> dict[str, object] | None:
        with Session(self._engine) as session:
            doc = session.get(Document, document_id)
            return _model_to_dict(doc) if doc else None

    def create_document(
        self,
        *,
        repo: str,
        title: str,
        content: str,
        document_type: str = "tech_spec",
        source_conversation_id: str | None = None,
    ) -> dict[str, object]:
        with Session(self._engine) as session:
            doc_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            doc = Document(
                id=doc_id,
                repo=repo,
                title=title[:500],
                content=content[:MAX_DOCUMENT_CONTENT_CHARS],
                document_type=document_type,
                source_conversation_id=source_conversation_id,
                created_at=now,
                updated_at=now,
            )
            session.add(doc)
            session.commit()
            return _model_to_dict(doc)

    def update_document(
        self,
        document_id: str,
        *,
        title: str | None = None,
        content: str | None = None,
        document_type: str | None = None,
    ) -> dict[str, object] | None:
        with Session(self._engine) as session:
            doc = session.get(Document, document_id)
            if not doc:
                return None
            if title is not None:
                doc.title = title[:500]
            if content is not None:
                doc.content = content[:MAX_DOCUMENT_CONTENT_CHARS]
            if document_type is not None:
                doc.document_type = document_type
            doc.updated_at = datetime.now(timezone.utc).isoformat()
            session.add(doc)
            session.commit()
            session.refresh(doc)
            return _model_to_dict(doc)

    def delete_document(self, document_id: str) -> bool:
        with Session(self._engine) as session:
            doc = session.get(Document, document_id)
            if doc is None:
                return False
            session.delete(doc)
            session.commit()
            return True


def _model_to_dict(doc: Document) -> dict[str, object]:
    return {
        "id": doc.id,
        "repo": doc.repo,
        "title": doc.title,
        "content": doc.content,
        "document_type": doc.document_type,
        "source_conversation_id": doc.source_conversation_id,
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }
