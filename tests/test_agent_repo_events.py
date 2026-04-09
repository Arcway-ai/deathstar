"""Tests for agent tool → RepoEvent detection bridge.

Verifies that _emit_repo_events_for_tool correctly detects state-changing
operations from tool call results and emits the appropriate RepoEvents
through the event bus.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deathstar_server.services.event_bus import (
    EVENT_LOCAL_CHECKOUT,
    EVENT_LOCAL_COMMIT,
    EVENT_PR_UPDATE,
    EVENT_PUSH,
    EVENT_REPO_DIRTY,
    SOURCE_AGENT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner_and_bus():
    """Create an AgentRunner with a mock event bus for testing repo events."""
    mock_bus = MagicMock()
    mock_bus.publish = MagicMock(return_value=1)

    # We only need the _event_bus attribute and the class methods
    # Import inline to avoid heavy SDK imports at module level
    from deathstar_server.services.agent_runner import AgentRunner

    runner = object.__new__(AgentRunner)
    runner._event_bus = mock_bus
    return runner, mock_bus


@pytest.fixture()
def agent():
    """Create a minimal mock RunningAgent."""
    a = MagicMock()
    a.repo = "my-org/my-repo"
    a.branch = "feature/test-branch"
    a.conversation_id = "conv-123"
    return a


# ---------------------------------------------------------------------------
# Git commit detection
# ---------------------------------------------------------------------------


class TestGitCommitDetection:
    def test_git_commit(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git commit -m 'feat: add feature'"}, "", False,
        )
        bus.publish.assert_called_once()
        event = bus.publish.call_args[0][0]
        assert event.event_type == EVENT_LOCAL_COMMIT
        assert event.repo == "my-org/my-repo"
        assert event.source == SOURCE_AGENT

    def test_git_commit_all(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git commit -a -m 'update'"}, "", False,
        )
        bus.publish.assert_called_once()
        assert bus.publish.call_args[0][0].event_type == EVENT_LOCAL_COMMIT

    def test_git_merge(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git merge feature/other"}, "", False,
        )
        bus.publish.assert_called_once()
        assert bus.publish.call_args[0][0].event_type == EVENT_LOCAL_COMMIT

    def test_git_commit_error_not_emitted(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git commit -m 'fail'"}, "error", True,
        )
        bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Git push detection
# ---------------------------------------------------------------------------


class TestGitPushDetection:
    def test_git_push(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git push origin feature/test-branch"}, "", False,
        )
        bus.publish.assert_called_once()
        event = bus.publish.call_args[0][0]
        assert event.event_type == EVENT_PUSH
        assert event.source == SOURCE_AGENT
        assert event.data["ref"] == "refs/heads/feature/test-branch"
        assert event.data["sender"] == "Agent"

    def test_git_push_no_branch(self, runner_and_bus, agent):
        agent.branch = None
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git push origin HEAD"}, "", False,
        )
        event = bus.publish.call_args[0][0]
        assert event.data["ref"] == "refs/heads/unknown"

    def test_git_push_error_not_emitted(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git push origin main"}, "rejected", True,
        )
        bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Git checkout / switch detection
# ---------------------------------------------------------------------------


class TestGitCheckoutDetection:
    def test_git_checkout(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git checkout feature/new"}, "", False,
        )
        bus.publish.assert_called_once()
        event = bus.publish.call_args[0][0]
        assert event.event_type == EVENT_LOCAL_CHECKOUT
        assert event.data["from_branch"] == "feature/test-branch"
        assert event.data["to_branch"] == "feature/new"

    def test_git_checkout_new_branch(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git checkout -b feature/created"}, "", False,
        )
        event = bus.publish.call_args[0][0]
        assert event.data["to_branch"] == "feature/created"

    def test_git_switch(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git switch develop"}, "", False,
        )
        event = bus.publish.call_args[0][0]
        assert event.event_type == EVENT_LOCAL_CHECKOUT
        assert event.data["to_branch"] == "develop"

    def test_git_switch_create(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git switch -c feature/brand-new"}, "", False,
        )
        event = bus.publish.call_args[0][0]
        assert event.data["to_branch"] == "feature/brand-new"

    def test_checkout_with_no_agent_branch(self, runner_and_bus, agent):
        agent.branch = None
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git checkout main"}, "", False,
        )
        event = bus.publish.call_args[0][0]
        assert event.data["from_branch"] == "unknown"


# ---------------------------------------------------------------------------
# GitHub PR operations
# ---------------------------------------------------------------------------


class TestPRDetection:
    def test_gh_pr_create(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash",
            {"command": "gh pr create --title 'feat' --body 'desc'"},
            "https://github.com/my-org/my-repo/pull/42\n",
            False,
        )
        bus.publish.assert_called_once()
        event = bus.publish.call_args[0][0]
        assert event.event_type == EVENT_PR_UPDATE
        assert event.data["action"] == "created"
        assert event.data["number"] == 42

    def test_gh_pr_create_no_url(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash",
            {"command": "gh pr create --title 'feat'"},
            "Creating pull request...\n",
            False,
        )
        event = bus.publish.call_args[0][0]
        assert event.data["action"] == "created"
        assert "number" not in event.data

    def test_gh_pr_merge(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "gh pr merge 42"}, "Merged", False,
        )
        bus.publish.assert_called_once()
        event = bus.publish.call_args[0][0]
        assert event.event_type == EVENT_PR_UPDATE
        assert event.data["action"] == "updated"

    def test_gh_pr_close(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "gh pr close 42"}, "Closed", False,
        )
        event = bus.publish.call_args[0][0]
        assert event.event_type == EVENT_PR_UPDATE

    def test_gh_pr_edit(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "gh pr edit 42 --title 'new title'"}, "", False,
        )
        event = bus.publish.call_args[0][0]
        assert event.event_type == EVENT_PR_UPDATE

    def test_gh_pr_review(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "gh pr review 42 --approve"}, "", False,
        )
        event = bus.publish.call_args[0][0]
        assert event.event_type == EVENT_PR_UPDATE


# ---------------------------------------------------------------------------
# File modification detection
# ---------------------------------------------------------------------------


class TestFileModificationDetection:
    def test_write_tool(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Write", {"file_path": "/workspace/test.py", "content": "..."}, "", False,
        )
        bus.publish.assert_called_once()
        event = bus.publish.call_args[0][0]
        assert event.event_type == EVENT_REPO_DIRTY
        assert event.source == SOURCE_AGENT
        assert event.data["tool"] == "Write"

    def test_edit_tool(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Edit", {"file_path": "/workspace/test.py"}, "", False,
        )
        event = bus.publish.call_args[0][0]
        assert event.event_type == EVENT_REPO_DIRTY
        assert event.data["tool"] == "Edit"

    def test_write_error_not_emitted(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Write", {"file_path": "/workspace/test.py"}, "Error", True,
        )
        bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# No-op / safe commands
# ---------------------------------------------------------------------------


class TestNoEvents:
    def test_read_tool(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Read", {"file_path": "/workspace/test.py"}, "content", False,
        )
        bus.publish.assert_not_called()

    def test_grep_tool(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Grep", {"pattern": "test"}, "matches", False,
        )
        bus.publish.assert_not_called()

    def test_ls_command(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "ls -la"}, "output", False,
        )
        bus.publish.assert_not_called()

    def test_cat_command(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "cat README.md"}, "content", False,
        )
        bus.publish.assert_not_called()

    def test_git_status(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git status"}, "output", False,
        )
        bus.publish.assert_not_called()

    def test_git_log(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git log --oneline -5"}, "output", False,
        )
        bus.publish.assert_not_called()

    def test_git_diff(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git diff HEAD"}, "output", False,
        )
        bus.publish.assert_not_called()

    def test_empty_command(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": ""}, "", False,
        )
        bus.publish.assert_not_called()

    def test_unknown_tool(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "UnknownTool", {"foo": "bar"}, "result", False,
        )
        bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# Compound commands (multiple git ops in one bash call)
# ---------------------------------------------------------------------------


class TestCompoundCommands:
    def test_commit_and_push(self, runner_and_bus, agent):
        """A single Bash call with both commit and push should emit both events."""
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash",
            {"command": "git commit -m 'change' && git push origin feature/test-branch"},
            "", False,
        )
        assert bus.publish.call_count == 2
        types = {call[0][0].event_type for call in bus.publish.call_args_list}
        assert EVENT_LOCAL_COMMIT in types
        assert EVENT_PUSH in types

    def test_checkout_and_commit(self, runner_and_bus, agent):
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash",
            {"command": "git checkout -b new-branch && git commit -m 'init'"},
            "", False,
        )
        assert bus.publish.call_count == 2
        types = {call[0][0].event_type for call in bus.publish.call_args_list}
        assert EVENT_LOCAL_CHECKOUT in types
        assert EVENT_LOCAL_COMMIT in types


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_string_tool_input(self, runner_and_bus, agent):
        """tool_input can be a plain string instead of dict."""
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", "git commit -m 'via string input'", "", False,
        )
        bus.publish.assert_called_once()
        assert bus.publish.call_args[0][0].event_type == EVENT_LOCAL_COMMIT

    def test_git_commit_in_echo_not_matched(self, runner_and_bus, agent):
        """Commands that merely mention 'git commit' in echo/strings should still match.

        Note: We intentionally cast a wide net — false positives (an extra
        refresh) are harmless; false negatives (missed refresh) degrade UX.
        """
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "echo 'run git commit later'"}, "", False,
        )
        # We accept this false positive — the regex is intentionally broad
        assert bus.publish.call_count == 1

    def test_pr_number_from_url(self, runner_and_bus, agent):
        """PR number extracted from GitHub URL in result."""
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash",
            {"command": "gh pr create --title test"},
            "https://github.com/org/repo/pull/123",
            False,
        )
        event = bus.publish.call_args[0][0]
        assert event.data["number"] == 123

    def test_pr_number_bare(self, runner_and_bus, agent):
        """PR number when result ends with just the number."""
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash",
            {"command": "gh pr create --title test"},
            "55",
            False,
        )
        event = bus.publish.call_args[0][0]
        assert event.data["number"] == 55

    def test_checkout_flag_not_treated_as_branch(self, runner_and_bus, agent):
        """git checkout -- file.txt should not treat '--' as a branch name."""
        runner, bus = runner_and_bus
        runner._emit_repo_events_for_tool(
            agent, "Bash", {"command": "git checkout -- file.txt"}, "", False,
        )
        event = bus.publish.call_args[0][0]
        assert event.data["to_branch"] == "unknown"
