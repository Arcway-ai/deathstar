"""Tests for branch-aware conversation queries (SQLModel)."""

from __future__ import annotations

import pytest

from sqlmodel import SQLModel

from deathstar_server.db.engine import create_db_engine


class TestConversationStoreBranch:
    @pytest.fixture()
    def store(self, tmp_path):
        from deathstar_server.web.conversations import ConversationStore
        engine = create_db_engine(f"sqlite:///{tmp_path}/test.db")
        SQLModel.metadata.create_all(engine)
        return ConversationStore(engine)

    def test_get_or_create_stores_branch(self, store):
        cid = store.get_or_create(None, "my-repo", branch="feature/auth")
        detail = store.get_conversation(cid)
        assert detail is not None
        assert detail.branch == "feature/auth"

    def test_get_or_create_null_branch(self, store):
        cid = store.get_or_create(None, "my-repo", branch=None)
        detail = store.get_conversation(cid)
        assert detail is not None
        assert detail.branch is None

    def test_list_conversations_filters_by_branch(self, store):
        cid_main = store.get_or_create(None, "my-repo", branch="main")
        store.add_user_message(cid_main, "on main")

        cid_feature = store.get_or_create(None, "my-repo", branch="feature/auth")
        store.add_user_message(cid_feature, "on feature")

        cid_legacy = store.get_or_create(None, "my-repo", branch=None)
        store.add_user_message(cid_legacy, "legacy no branch")

        # Filter by branch=main → should get main + legacy (NULL)
        main_convos = store.list_conversations("my-repo", "main")
        main_ids = {c.id for c in main_convos}
        assert cid_main in main_ids
        assert cid_legacy in main_ids
        assert cid_feature not in main_ids

        # Filter by branch=feature/auth → should get feature + legacy (NULL)
        feat_convos = store.list_conversations("my-repo", "feature/auth")
        feat_ids = {c.id for c in feat_convos}
        assert cid_feature in feat_ids
        assert cid_legacy in feat_ids
        assert cid_main not in feat_ids

    def test_list_conversations_no_branch_filter_returns_all(self, store):
        cid1 = store.get_or_create(None, "my-repo", branch="main")
        store.add_user_message(cid1, "msg1")

        cid2 = store.get_or_create(None, "my-repo", branch="feature/x")
        store.add_user_message(cid2, "msg2")

        cid3 = store.get_or_create(None, "my-repo", branch=None)
        store.add_user_message(cid3, "msg3")

        all_convos = store.list_conversations("my-repo", None)
        all_ids = {c.id for c in all_convos}
        assert {cid1, cid2, cid3} == all_ids

    def test_conversation_branch_returned_in_summary(self, store):
        cid = store.get_or_create(None, "my-repo", branch="bugfix/login")
        store.add_user_message(cid, "hello")

        convos = store.list_conversations("my-repo")
        assert len(convos) == 1
        assert convos[0].branch == "bugfix/login"
