from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_server.services.gitops import GitService
from deathstar_shared.models import ErrorCode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_root=tmp_path,
        projects_root=tmp_path / "projects",
        log_path=tmp_path / "log.txt",
        backup_directory=tmp_path / "backups",
        backup_bucket=None,
        backup_s3_prefix="workspace-backups",
        aws_region="us-west-1",
        log_level="INFO",
        github_token=None,
        tailscale_enabled=False,
        tailscale_hostname=None,
        ssh_user="ubuntu",
        api_token=None,
        github_webhook_secret=None,
        github_poll_interval_seconds=30,
        max_worktrees_per_repo=6,
        max_total_worktrees=16,
        database_url="sqlite://",
    )


def _init_git_repo(repo_path: Path, branch: str = "main") -> Path:
    """Create a minimal git repo with one commit."""
    repo_path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", branch], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo_path, check=True, capture_output=True,
    )
    readme = repo_path / "README.md"
    readme.write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo_path, check=True, capture_output=True,
    )
    return repo_path


# ---------------------------------------------------------------------------
# resolve_target
# ---------------------------------------------------------------------------

class TestResolveTarget:
    def test_valid_path(self, tmp_path):
        settings = _make_settings(tmp_path)
        projects = settings.projects_root
        projects.mkdir(parents=True)
        (projects / "myrepo").mkdir()

        service = GitService(settings)
        target = service.resolve_target("myrepo")

        assert target == (projects / "myrepo").resolve()

    def test_path_traversal_rejected(self, tmp_path):
        settings = _make_settings(tmp_path)
        projects = settings.projects_root
        projects.mkdir(parents=True)

        service = GitService(settings)

        with pytest.raises(AppError) as exc_info:
            service.resolve_target("../../etc")
        assert exc_info.value.code == ErrorCode.INVALID_REQUEST
        assert "escapes" in exc_info.value.message

    def test_nonexistent_path_rejected(self, tmp_path):
        settings = _make_settings(tmp_path)
        settings.projects_root.mkdir(parents=True)

        service = GitService(settings)

        with pytest.raises(AppError) as exc_info:
            service.resolve_target("does-not-exist")
        assert exc_info.value.code == ErrorCode.INVALID_REQUEST
        assert "does not exist" in exc_info.value.message

    def test_dot_path_resolves_to_projects_root(self, tmp_path):
        settings = _make_settings(tmp_path)
        settings.projects_root.mkdir(parents=True)

        service = GitService(settings)
        target = service.resolve_target(".")

        assert target == settings.projects_root.resolve()


# ---------------------------------------------------------------------------
# build_workspace_context
# ---------------------------------------------------------------------------

class TestBuildWorkspaceContext:
    def test_returns_context_string(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)
        (repo_path / "main.py").write_text("print('hello')\n")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)

        service = GitService(settings)
        context = service.build_workspace_context("myrepo")

        assert "Target path:" in context
        assert "main.py" in context

    def test_includes_file_contents(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)
        (repo_path / "hello.py").write_text("x = 42\n")

        service = GitService(settings)
        context = service.build_workspace_context("myrepo")

        assert "x = 42" in context

    def test_single_file_target(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)
        (repo_path / "file.py").write_text("code = True\n")

        service = GitService(settings)
        context = service.build_workspace_context("myrepo/file.py")

        assert "code = True" in context


# ---------------------------------------------------------------------------
# apply_patch
# ---------------------------------------------------------------------------

class TestApplyPatch:
    def test_applies_valid_patch(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)
        (repo_path / "hello.py").write_text("old_value = 1\n")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add file"],
            cwd=repo_path, check=True, capture_output=True,
        )

        patch_text = (
            "--- a/hello.py\n"
            "+++ b/hello.py\n"
            "@@ -1 +1 @@\n"
            "-old_value = 1\n"
            "+new_value = 2\n"
        )

        service = GitService(settings)
        result_root = service.apply_patch("myrepo", patch_text)

        assert (result_root / "hello.py").read_text() == "new_value = 2\n"

    def test_empty_patch_raises(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)

        service = GitService(settings)

        with pytest.raises(AppError) as exc_info:
            service.apply_patch("myrepo", "   ")
        assert exc_info.value.code == ErrorCode.INVALID_PROVIDER_OUTPUT


# ---------------------------------------------------------------------------
# collect_diff_snapshot
# ---------------------------------------------------------------------------

class TestCollectDiffSnapshot:
    def test_collects_dirty_diff(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)

        # Modify a tracked file so it shows as dirty (not just untracked)
        (repo_path / "README.md").write_text("# Modified\n")

        service = GitService(settings)
        snapshot = service.collect_diff_snapshot("myrepo", "main")

        assert snapshot.branch == "main"
        assert snapshot.dirty is True
        assert snapshot.diff_text  # should have some diff

    def test_collects_branch_diff(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)

        # Create a feature branch with changes
        subprocess.run(
            ["git", "switch", "-c", "feature"],
            cwd=repo_path, check=True, capture_output=True,
        )
        (repo_path / "feature.py").write_text("feature code\n")
        subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feature"],
            cwd=repo_path, check=True, capture_output=True,
        )

        service = GitService(settings)
        snapshot = service.collect_diff_snapshot("myrepo", "main")

        assert snapshot.branch == "feature"
        assert snapshot.dirty is False
        assert "feature.py" in snapshot.diff_text

    def test_no_changes_on_same_branch_raises(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)

        service = GitService(settings)

        with pytest.raises(AppError) as exc_info:
            service.collect_diff_snapshot("myrepo", "main")
        assert exc_info.value.code == ErrorCode.INVALID_REQUEST


# ---------------------------------------------------------------------------
# changed_files
# ---------------------------------------------------------------------------

class TestChangedFiles:
    def test_lists_changed_files(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)
        (repo_path / "new.py").write_text("x = 1\n")

        service = GitService(settings)
        files = service.changed_files(repo_path)

        assert "new.py" in files

    def test_no_changes_returns_empty(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)

        service = GitService(settings)
        files = service.changed_files(repo_path)

        assert files == []


# ---------------------------------------------------------------------------
# ensure_branch
# ---------------------------------------------------------------------------

class TestEnsureBranch:
    def test_creates_new_branch(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)

        service = GitService(settings)
        service.ensure_branch(repo_path, "feature-x")

        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path, check=True, capture_output=True, text=True,
        )
        assert result.stdout.strip() == "feature-x"

    def test_no_op_if_already_on_branch(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)

        service = GitService(settings)
        # Already on main, so this should be a no-op
        service.ensure_branch(repo_path, "main")

        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path, check=True, capture_output=True, text=True,
        )
        assert result.stdout.strip() == "main"

    def test_errors_on_existing_branch(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)

        # Create a branch and switch back
        subprocess.run(
            ["git", "switch", "-c", "existing"],
            cwd=repo_path, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "switch", "main"],
            cwd=repo_path, check=True, capture_output=True,
        )

        service = GitService(settings)

        with pytest.raises(AppError) as exc_info:
            service.ensure_branch(repo_path, "existing")
        assert exc_info.value.code == ErrorCode.INVALID_REQUEST
        assert "already exists" in exc_info.value.message


# ---------------------------------------------------------------------------
# repo_root_for_subpath and current_branch
# ---------------------------------------------------------------------------

class TestRepoHelpers:
    def test_repo_root_for_subpath(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)
        subdir = repo_path / "sub"
        subdir.mkdir()
        (subdir / "file.py").write_text("x = 1\n")

        service = GitService(settings)
        root = service.repo_root_for_subpath("myrepo/sub")

        assert root == repo_path.resolve()

    def test_current_branch(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)

        service = GitService(settings)
        branch = service.current_branch(repo_path)

        assert branch == "main"


# ---------------------------------------------------------------------------
# _normalize_patch
# ---------------------------------------------------------------------------

class TestNormalizePatch:
    def test_adds_space_prefix_to_context_lines(self):
        """LLMs often omit the leading space on context lines."""
        patch = (
            "diff --git a/hello.py b/hello.py\n"
            "--- a/hello.py\n"
            "+++ b/hello.py\n"
            "@@ -1,3 +1,3 @@\n"
            "import os\n"  # missing space prefix
            "-old = 1\n"
            "+new = 2\n"
            "import sys\n"  # missing space prefix
        )
        result = GitService._normalize_patch(patch)
        lines = result.split("\n")
        # The context lines should now start with a space
        assert lines[4] == " import os"
        assert lines[7] == " import sys"

    def test_fixes_empty_lines_in_hunks(self):
        """Empty lines inside hunks should become ' ' (space-only context lines)."""
        patch = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,4 +1,4 @@\n"
            " first\n"
            "\n"  # empty line in hunk
            "-old\n"
            "+new\n"
        )
        result = GitService._normalize_patch(patch)
        lines = result.split("\n")
        assert lines[5] == " "  # empty line converted to space

    def test_preserves_valid_patch(self):
        """A well-formed patch should pass through unchanged (except trailing newline)."""
        patch = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,3 +1,3 @@\n"
            " context\n"
            "-old\n"
            "+new\n"
        )
        result = GitService._normalize_patch(patch)
        assert result == patch

    def test_normalizes_crlf(self):
        """Windows-style line endings should be converted to LF."""
        patch = "diff --git a/f.py b/f.py\r\n--- a/f.py\r\n+++ b/f.py\r\n@@ -1 +1 @@\r\n-old\r\n+new\r\n"
        result = GitService._normalize_patch(patch)
        assert "\r" not in result
        assert result.startswith("diff --git a/f.py b/f.py\n")

    def test_ensures_trailing_newline(self):
        patch = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new"  # no trailing newline
        )
        result = GitService._normalize_patch(patch)
        assert result.endswith("\n")


# ---------------------------------------------------------------------------
# repo_root_for_subpath and current_branch (continued)
# ---------------------------------------------------------------------------

class TestRepoHelpersContinued:
    def test_commit_all(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "myrepo"
        _init_git_repo(repo_path)
        (repo_path / "new.py").write_text("x = 1\n")

        service = GitService(settings)
        sha = service.commit_all(repo_path, "add new file")

        assert len(sha) == 40  # full SHA

        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=repo_path, check=True, capture_output=True, text=True,
        )
        assert "add new file" in log.stdout
