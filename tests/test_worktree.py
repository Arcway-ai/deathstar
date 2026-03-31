"""Tests for WorktreeManager — git worktree creation, listing, cleanup."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from deathstar_server.config import Settings
from deathstar_server.services.worktree import WorktreeManager


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
        max_worktrees_per_repo=3,
        max_total_worktrees=16,
    )


def _init_repo(repo_path: Path) -> None:
    """Create a git repo with an initial commit and a feature branch."""
    repo_path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo_path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo_path), capture_output=True, check=True,
    )
    (repo_path / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=str(repo_path), capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(repo_path), capture_output=True, check=True,
    )
    # Create a feature branch (without switching to it)
    subprocess.run(
        ["git", "branch", "feature/auth"],
        cwd=str(repo_path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "branch", "bugfix/login"],
        cwd=str(repo_path), capture_output=True, check=True,
    )


class TestBranchSlug:
    def test_simple_branch(self):
        slug = WorktreeManager._branch_slug("feature/auth")
        assert slug.startswith("feature-auth-")
        assert len(slug) <= 60

    def test_complex_branch(self):
        slug = WorktreeManager._branch_slug("user/john.doe/JIRA-1234/fix-the-thing")
        assert "/" not in slug
        assert "." not in slug

    def test_collision_resistance(self):
        slug1 = WorktreeManager._branch_slug("feature/auth")
        slug2 = WorktreeManager._branch_slug("feature-auth")
        # Different branches should produce different slugs due to hash suffix
        assert slug1 != slug2


class TestResolveWorkingDir:
    def test_none_branch_returns_primary(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "my-repo"
        _init_repo(repo_path)
        mgr = WorktreeManager(settings)

        result = mgr.resolve_working_dir("my-repo", None)
        assert result == repo_path

    def test_current_branch_returns_primary(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "my-repo"
        _init_repo(repo_path)
        mgr = WorktreeManager(settings)

        # Primary is on 'main' (or 'master')
        current = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_path), capture_output=True, text=True, check=True,
        ).stdout.strip()

        result = mgr.resolve_working_dir("my-repo", current)
        assert result == repo_path

    def test_different_branch_creates_worktree(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "my-repo"
        _init_repo(repo_path)
        mgr = WorktreeManager(settings)

        result = mgr.resolve_working_dir("my-repo", "feature/auth")
        assert result != repo_path
        assert result.is_dir()
        assert ".worktrees" in str(result)

        # Verify the worktree is on the right branch
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(result), capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert branch == "feature/auth"


class TestEnsureWorktree:
    def test_creates_worktree(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "my-repo"
        _init_repo(repo_path)
        mgr = WorktreeManager(settings)

        wt_path = mgr.ensure_worktree(repo_path, "feature/auth")
        assert wt_path.is_dir()

    def test_idempotent(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "my-repo"
        _init_repo(repo_path)
        mgr = WorktreeManager(settings)

        path1 = mgr.ensure_worktree(repo_path, "feature/auth")
        path2 = mgr.ensure_worktree(repo_path, "feature/auth")
        assert path1 == path2

    def test_nonexistent_branch_raises(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "my-repo"
        _init_repo(repo_path)
        mgr = WorktreeManager(settings)

        from deathstar_server.errors import AppError
        with pytest.raises(AppError, match="does not exist"):
            mgr.ensure_worktree(repo_path, "nonexistent/branch")

    def test_limit_enforced(self, tmp_path):
        settings = _make_settings(tmp_path)  # max_worktrees_per_repo=3
        repo_path = settings.projects_root / "my-repo"
        _init_repo(repo_path)
        # Create more branches
        for i in range(4):
            subprocess.run(
                ["git", "branch", f"test-branch-{i}"],
                cwd=str(repo_path), capture_output=True, check=True,
            )
        mgr = WorktreeManager(settings)

        mgr.ensure_worktree(repo_path, "test-branch-0")
        mgr.ensure_worktree(repo_path, "test-branch-1")
        mgr.ensure_worktree(repo_path, "test-branch-2")

        from deathstar_server.errors import AppError
        with pytest.raises(AppError, match="worktree limit reached"):
            mgr.ensure_worktree(repo_path, "test-branch-3")


class TestListWorktrees:
    def test_lists_primary_and_worktrees(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "my-repo"
        _init_repo(repo_path)
        mgr = WorktreeManager(settings)

        mgr.ensure_worktree(repo_path, "feature/auth")

        worktrees = mgr.list_worktrees(repo_path)
        assert len(worktrees) == 2

        primary = [w for w in worktrees if w.is_primary]
        assert len(primary) == 1
        assert primary[0].path == repo_path

        non_primary = [w for w in worktrees if not w.is_primary]
        assert len(non_primary) == 1
        assert non_primary[0].branch == "feature/auth"


class TestRemoveWorktree:
    def test_removes_worktree(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "my-repo"
        _init_repo(repo_path)
        mgr = WorktreeManager(settings)

        wt_path = mgr.ensure_worktree(repo_path, "feature/auth")
        assert wt_path.is_dir()

        mgr.remove_worktree(repo_path, "feature/auth")

        worktrees = mgr.list_worktrees(repo_path)
        non_primary = [w for w in worktrees if not w.is_primary]
        assert len(non_primary) == 0


class TestCleanupStale:
    def test_removes_only_stale(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "my-repo"
        _init_repo(repo_path)
        mgr = WorktreeManager(settings)

        mgr.ensure_worktree(repo_path, "feature/auth")
        mgr.ensure_worktree(repo_path, "bugfix/login")

        # Only feature/auth is active
        removed = mgr.cleanup_stale(repo_path, {"feature/auth"})
        assert removed == 1

        worktrees = mgr.list_worktrees(repo_path)
        branches = {w.branch for w in worktrees if not w.is_primary}
        assert "feature/auth" in branches
        assert "bugfix/login" not in branches

    def test_empty_active_removes_all(self, tmp_path):
        settings = _make_settings(tmp_path)
        repo_path = settings.projects_root / "my-repo"
        _init_repo(repo_path)
        mgr = WorktreeManager(settings)

        mgr.ensure_worktree(repo_path, "feature/auth")
        mgr.ensure_worktree(repo_path, "bugfix/login")

        removed = mgr.cleanup_stale(repo_path, set())
        assert removed == 2

        worktrees = mgr.list_worktrees(repo_path)
        assert all(w.is_primary for w in worktrees)
