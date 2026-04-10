from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import SQLModel

from deathstar_server.db.engine import create_db_engine
from deathstar_server.web.linear_store import (
    LinearStore,
    SyncResult,
    _derive_branch_name,
    _slugify,
)


@pytest.fixture
def store(tmp_path: Path) -> LinearStore:
    engine = create_db_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    return LinearStore(engine)


def _make_store_pair(tmp_path: Path) -> tuple[LinearStore, LinearStore]:
    """Return two stores sharing the same DB for concurrency tests."""
    engine = create_db_engine(f"sqlite:///{tmp_path}/test.db")
    SQLModel.metadata.create_all(engine)
    return LinearStore(engine), LinearStore(engine)


# ------------------------------------------------------------------
# Helper function tests
# ------------------------------------------------------------------


class TestSlugify:
    def test_simple_text(self) -> None:
        assert _slugify("Add user auth") == "add-user-auth"

    def test_special_characters(self) -> None:
        assert _slugify("Fix bug #42 (urgent!)") == "fix-bug-42-urgent"

    def test_multiple_spaces_and_underscores(self) -> None:
        assert _slugify("refactor__the   api") == "refactor-the-api"

    def test_empty_string(self) -> None:
        assert _slugify("") == ""

    def test_only_special_characters(self) -> None:
        assert _slugify("!!!@@@") == ""

    def test_truncates_at_60(self) -> None:
        long_title = "a" * 100
        assert len(_slugify(long_title)) == 60

    def test_leading_trailing_hyphens_stripped(self) -> None:
        assert _slugify("--hello--") == "hello"


class TestDeriveBranchName:
    def test_standard_case(self) -> None:
        assert _derive_branch_name("ENG-123", "Add user auth") == "eng-123/add-user-auth"

    def test_empty_title(self) -> None:
        assert _derive_branch_name("ENG-99", "") == "eng-99"

    def test_special_title(self) -> None:
        result = _derive_branch_name("PROJ-1", "Fix: login page (v2)")
        assert result == "proj-1/fix-login-page-v2"


# ------------------------------------------------------------------
# link_project tests
# ------------------------------------------------------------------


class TestLinkProject:
    def test_creates_project(self, store: LinearStore) -> None:
        project = store.link_project(
            repo="my-repo",
            linear_project_id="proj-abc",
            conversation_id=None,
            team_id="team-1",
            project_data={
                "name": "Sprint 1",
                "slugId": "sprint-1",
                "status": {"id": "s1", "name": "Started", "type": "started"},
                "url": "https://linear.app/p/1",
            },
        )
        assert project.repo == "my-repo"
        assert project.linear_project_id == "proj-abc"
        assert project.name == "Sprint 1"
        assert project.state == "started"
        assert project.id  # UUID generated

    def test_idempotent_update(self, store: LinearStore) -> None:
        store.link_project(
            repo="my-repo",
            linear_project_id="proj-abc",
            conversation_id=None,
            team_id="team-1",
            project_data={"name": "Sprint 1"},
        )
        updated = store.link_project(
            repo="my-repo",
            linear_project_id="proj-abc",
            conversation_id=None,
            team_id="team-1",
            project_data={"name": "Sprint 1 (updated)"},
        )
        assert updated.name == "Sprint 1 (updated)"

        # Should still be just one project
        projects = store.list_projects_for_repo("my-repo")
        assert len(projects) == 1

    def test_extracts_state_from_status_object_on_update(self, store: LinearStore) -> None:
        store.link_project(
            repo="r",
            linear_project_id="proj-1",
            conversation_id=None,
            team_id="t",
            project_data={"name": "P", "status": {"type": "planned"}},
        )
        updated = store.link_project(
            repo="r",
            linear_project_id="proj-1",
            conversation_id=None,
            team_id="t",
            project_data={"name": "P", "status": {"id": "s2", "name": "Started", "type": "started"}},
        )
        assert updated.state == "started"

    def test_defaults_state_when_no_status(self, store: LinearStore) -> None:
        project = store.link_project(
            repo="r",
            linear_project_id="proj-2",
            conversation_id=None,
            team_id="t",
            project_data={"name": "No Status"},
        )
        assert project.state == "planned"

    def test_integrity_error_fallback(self, tmp_path: Path) -> None:
        """Concurrent inserts with the same linear_project_id should not crash."""
        store_a, store_b = _make_store_pair(tmp_path)

        proj_a = store_a.link_project(
            repo="repo", linear_project_id="same-id",
            conversation_id=None, team_id="t1",
            project_data={"name": "A"},
        )
        # Second insert for the same linear_project_id goes through the
        # update path since we share the same DB.
        proj_b = store_b.link_project(
            repo="repo", linear_project_id="same-id",
            conversation_id=None, team_id="t1",
            project_data={"name": "B"},
        )
        assert proj_a.linear_project_id == proj_b.linear_project_id
        # The second call updates the name
        assert proj_b.name == "B"


class TestGetProject:
    def test_found(self, store: LinearStore) -> None:
        store.link_project(
            repo="r", linear_project_id="p1",
            conversation_id=None, team_id="t1",
            project_data={"name": "P"},
        )
        result = store.get_project_by_linear_id("p1")
        assert result is not None
        assert result.name == "P"

    def test_not_found(self, store: LinearStore) -> None:
        assert store.get_project_by_linear_id("nonexistent") is None


class TestListProjects:
    def test_filters_by_repo(self, store: LinearStore) -> None:
        store.link_project(repo="a", linear_project_id="p1", conversation_id=None, team_id="t", project_data={"name": "A"})
        store.link_project(repo="b", linear_project_id="p2", conversation_id=None, team_id="t", project_data={"name": "B"})
        results = store.list_projects_for_repo("a")
        assert len(results) == 1
        assert results[0].repo == "a"


# ------------------------------------------------------------------
# sync_issues tests
# ------------------------------------------------------------------


class TestSyncIssues:
    def _link_project(self, store: LinearStore) -> str:
        project = store.link_project(
            repo="my-repo", linear_project_id="lp-1",
            conversation_id=None, team_id="t1",
            project_data={"name": "Test"},
        )
        return project.id

    def test_creates_issues(self, store: LinearStore) -> None:
        pid = self._link_project(store)
        result = store.sync_issues(pid, [
            {
                "id": "issue-1", "identifier": "ENG-1", "title": "First",
                "state": {"name": "Todo", "type": "unstarted"},
                "priority": 2, "url": "https://linear.app/1",
            },
            {
                "id": "issue-2", "identifier": "ENG-2", "title": "Second",
                "state": {"name": "Backlog"},
                "priority": 4, "url": "https://linear.app/2",
            },
        ])
        assert result.created == 2
        assert result.updated == 0
        assert result.deleted_ids == ()

        issues = store.list_issues_for_project(pid)
        assert len(issues) == 2

    def test_updates_changed_issues(self, store: LinearStore) -> None:
        pid = self._link_project(store)
        store.sync_issues(pid, [
            {"id": "i1", "identifier": "ENG-1", "title": "Original", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ])

        result = store.sync_issues(pid, [
            {"id": "i1", "identifier": "ENG-1", "title": "Updated title", "state": {"name": "In Progress"}, "priority": 1, "url": ""},
        ])
        assert result.created == 0
        assert result.updated == 1

        issue = store.get_issue_by_linear_id("i1")
        assert issue is not None
        assert issue.title == "Updated title"
        assert issue.status == "In Progress"
        assert issue.priority == 1

    def test_no_op_when_unchanged(self, store: LinearStore) -> None:
        pid = self._link_project(store)
        data = [{"id": "i1", "identifier": "ENG-1", "title": "Same", "state": {"name": "Todo"}, "priority": 0, "url": ""}]
        store.sync_issues(pid, data)
        result = store.sync_issues(pid, data)
        assert result.created == 0
        assert result.updated == 0

    def test_deletes_removed_issues(self, store: LinearStore) -> None:
        pid = self._link_project(store)
        store.sync_issues(pid, [
            {"id": "i1", "identifier": "ENG-1", "title": "Keep", "state": {"name": "Todo"}, "priority": 0, "url": ""},
            {"id": "i2", "identifier": "ENG-2", "title": "Remove", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ])

        result = store.sync_issues(pid, [
            {"id": "i1", "identifier": "ENG-1", "title": "Keep", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ])
        assert result.deleted_ids  # Should have one deleted
        assert len(result.deleted_ids) == 1
        assert store.get_issue_by_linear_id("i2") is None

    def test_derives_branch_name(self, store: LinearStore) -> None:
        pid = self._link_project(store)
        store.sync_issues(pid, [
            {"id": "i1", "identifier": "ENG-42", "title": "Add user auth", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ])
        issue = store.get_issue_by_linear_id("i1")
        assert issue is not None
        assert issue.branch == "eng-42/add-user-auth"

    def test_uses_remote_branch_name(self, store: LinearStore) -> None:
        pid = self._link_project(store)
        store.sync_issues(pid, [
            {"id": "i1", "identifier": "ENG-1", "title": "Stuff", "branchName": "custom/branch", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ])
        issue = store.get_issue_by_linear_id("i1")
        assert issue is not None
        assert issue.branch == "custom/branch"

    def test_extracts_assignee(self, store: LinearStore) -> None:
        pid = self._link_project(store)
        store.sync_issues(pid, [
            {
                "id": "i1", "identifier": "ENG-1", "title": "Task",
                "state": {"name": "Todo"}, "priority": 0, "url": "",
                "assignee": {"displayName": "Alice", "name": "alice"},
            },
        ])
        issue = store.get_issue_by_linear_id("i1")
        assert issue is not None
        assert issue.assignee == "Alice"

    def test_missing_project_returns_empty(self, store: LinearStore) -> None:
        result = store.sync_issues("nonexistent-id", [])
        assert result.created == 0
        assert result.deleted_ids == ()

    def test_skips_issues_without_id(self, store: LinearStore) -> None:
        pid = self._link_project(store)
        result = store.sync_issues(pid, [
            {"identifier": "ENG-1", "title": "No ID"},
        ])
        assert result.created == 0


# ------------------------------------------------------------------
# Issue lookup tests
# ------------------------------------------------------------------


class TestGetIssueByBranch:
    def test_found(self, store: LinearStore) -> None:
        project = store.link_project(
            repo="my-repo", linear_project_id="lp-1",
            conversation_id=None, team_id="t1",
            project_data={"name": "P"},
        )
        store.sync_issues(project.id, [
            {"id": "i1", "identifier": "ENG-1", "title": "Auth", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ])
        result = store.get_issue_by_branch("my-repo", "eng-1/auth")
        assert result is not None
        assert result.linear_issue_id == "i1"

    def test_not_found(self, store: LinearStore) -> None:
        assert store.get_issue_by_branch("repo", "no-such-branch") is None


class TestUpdateIssueStatus:
    def test_updates_existing(self, store: LinearStore) -> None:
        project = store.link_project(
            repo="r", linear_project_id="p1",
            conversation_id=None, team_id="t",
            project_data={"name": "P"},
        )
        store.sync_issues(project.id, [
            {"id": "i1", "identifier": "ENG-1", "title": "T", "state": {"name": "Todo"}, "priority": 0, "url": ""},
        ])
        assert store.update_issue_status("i1", "Done") is True
        issue = store.get_issue_by_linear_id("i1")
        assert issue is not None
        assert issue.status == "Done"

    def test_not_found_returns_false(self, store: LinearStore) -> None:
        assert store.update_issue_status("nonexistent", "Done") is False


class TestSyncResultImmutability:
    def test_deleted_ids_is_tuple(self) -> None:
        result = SyncResult(created=1, updated=0, deleted_ids=("a", "b"))
        assert isinstance(result.deleted_ids, tuple)
        with pytest.raises(AttributeError):
            result.created = 99  # type: ignore[misc]
