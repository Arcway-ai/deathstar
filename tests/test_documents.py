from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import SQLModel

from deathstar_server.db.engine import create_db_engine
from deathstar_server.web.document_store import DocumentStore


@pytest.fixture
def doc_store(tmp_path: Path) -> DocumentStore:
    engine = create_db_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    return DocumentStore(engine)


class TestCreateDocument:
    def test_creates_and_returns(self, doc_store: DocumentStore) -> None:
        doc = doc_store.create_document(
            repo="my-project",
            title="Auth redesign",
            content="# Overview\nRedesign the auth layer.",
            document_type="tech_spec",
        )
        assert doc["repo"] == "my-project"
        assert doc["title"] == "Auth redesign"
        assert doc["document_type"] == "tech_spec"
        assert doc["source_conversation_id"] is None
        assert doc["id"]
        assert doc["created_at"]

    def test_truncates_title(self, doc_store: DocumentStore) -> None:
        doc = doc_store.create_document(
            repo="my-project",
            title="x" * 600,
            content="body",
        )
        assert len(str(doc["title"])) == 500

    def test_with_source_conversation(self, doc_store: DocumentStore) -> None:
        doc = doc_store.create_document(
            repo="my-project",
            title="Plan",
            content="body",
            source_conversation_id="conv-123",
        )
        assert doc["source_conversation_id"] == "conv-123"


class TestListDocuments:
    def test_lists_by_repo(self, doc_store: DocumentStore) -> None:
        doc_store.create_document(repo="a", title="Doc A", content="body")
        doc_store.create_document(repo="b", title="Doc B", content="body")
        docs = doc_store.list_documents(repo="a")
        assert len(docs) == 1
        assert docs[0]["repo"] == "a"

    def test_lists_by_type(self, doc_store: DocumentStore) -> None:
        doc_store.create_document(repo="a", title="Spec", content="body", document_type="tech_spec")
        doc_store.create_document(repo="a", title="Plan", content="body", document_type="plan")
        docs = doc_store.list_documents(repo="a", document_type="plan")
        assert len(docs) == 1
        assert docs[0]["document_type"] == "plan"

    def test_lists_all(self, doc_store: DocumentStore) -> None:
        doc_store.create_document(repo="a", title="One", content="body")
        doc_store.create_document(repo="b", title="Two", content="body")
        docs = doc_store.list_documents()
        assert len(docs) == 2


class TestGetDocument:
    def test_returns_existing(self, doc_store: DocumentStore) -> None:
        created = doc_store.create_document(repo="a", title="T", content="body")
        fetched = doc_store.get_document(str(created["id"]))
        assert fetched is not None
        assert fetched["title"] == "T"

    def test_returns_none_for_missing(self, doc_store: DocumentStore) -> None:
        assert doc_store.get_document("nonexistent") is None


class TestUpdateDocument:
    def test_updates_title(self, doc_store: DocumentStore) -> None:
        doc = doc_store.create_document(repo="a", title="Old", content="body")
        updated = doc_store.update_document(str(doc["id"]), title="New")
        assert updated is not None
        assert updated["title"] == "New"
        assert updated["content"] == "body"

    def test_updates_content(self, doc_store: DocumentStore) -> None:
        doc = doc_store.create_document(repo="a", title="T", content="old")
        updated = doc_store.update_document(str(doc["id"]), content="new")
        assert updated is not None
        assert updated["content"] == "new"

    def test_updates_type(self, doc_store: DocumentStore) -> None:
        doc = doc_store.create_document(repo="a", title="T", content="body", document_type="plan")
        updated = doc_store.update_document(str(doc["id"]), document_type="tech_spec")
        assert updated is not None
        assert updated["document_type"] == "tech_spec"

    def test_returns_none_for_missing(self, doc_store: DocumentStore) -> None:
        assert doc_store.update_document("nonexistent", title="X") is None


class TestDeleteDocument:
    def test_deletes_existing(self, doc_store: DocumentStore) -> None:
        doc = doc_store.create_document(repo="a", title="T", content="body")
        assert doc_store.delete_document(str(doc["id"])) is True
        assert doc_store.get_document(str(doc["id"])) is None

    def test_returns_false_for_missing(self, doc_store: DocumentStore) -> None:
        assert doc_store.delete_document("nonexistent") is False
