"""Git worktree manager for parallel agent sessions."""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_shared.models import ErrorCode

logger = logging.getLogger(__name__)

_WORKTREES_DIR = ".worktrees"


@dataclass(frozen=True)
class WorktreeInfo:
    path: Path
    branch: str
    head_sha: str
    is_primary: bool


class WorktreeManager:
    """Manages git worktrees for isolated parallel agent sessions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve_working_dir(self, repo: str, branch: str | None) -> Path:
        """Return the working directory for a repo+branch combo.

        If branch is None or matches the primary checkout's current branch,
        returns the primary directory.  Otherwise creates/returns a worktree.
        """
        # Path traversal validation
        if ".." in repo or repo.startswith("/"):
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"invalid repo name: {repo}",
                status_code=400,
            )
        repo_root = (self.settings.projects_root / repo).resolve()
        projects_root = self.settings.projects_root.resolve()
        if not repo_root.is_relative_to(projects_root):
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"repo path escapes projects root: {repo}",
                status_code=400,
            )
        if not repo_root.is_dir():
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"repo directory does not exist: {repo}",
                status_code=400,
            )

        if branch is None:
            return repo_root

        # Check if branch matches current checkout
        primary_branch = self._current_branch(repo_root)
        if branch == primary_branch:
            return repo_root

        # Need a worktree
        return self.ensure_worktree(repo_root, branch)

    def ensure_worktree(self, repo_root: Path, branch: str) -> Path:
        """Create a worktree for branch if it doesn't exist, return its path."""
        slug = self._branch_slug(branch)
        worktree_dir = repo_root / _WORKTREES_DIR
        worktree_path = worktree_dir / slug

        if worktree_path.is_dir():
            # Verify it's still a valid worktree pointing to the right branch
            actual = self._current_branch(worktree_path)
            if actual == branch:
                return worktree_path
            # Stale worktree — remove and recreate
            logger.warning(
                "worktree at %s has branch %s, expected %s — recreating",
                worktree_path, actual, branch,
            )
            self._remove_worktree(repo_root, worktree_path)

        # Enforce per-repo limit
        existing = self.list_worktrees(repo_root)
        non_primary = [w for w in existing if not w.is_primary]
        if len(non_primary) >= self.settings.max_worktrees_per_repo:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"worktree limit reached ({self.settings.max_worktrees_per_repo} per repo)",
                status_code=429,
            )

        # Enforce global worktree limit across all repos
        total = self._count_total_worktrees()
        if total >= self.settings.max_total_worktrees:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"global worktree limit reached ({self.settings.max_total_worktrees} total)",
                status_code=429,
            )

        worktree_dir.mkdir(parents=True, exist_ok=True)

        # Check if the branch exists locally or as a remote tracking branch
        branch_exists = self._branch_exists(repo_root, branch)

        if branch_exists:
            self._run(
                ["git", "worktree", "add", str(worktree_path), branch],
                cwd=repo_root,
            )
        else:
            # Try to create from remote tracking branch
            remote_ref = f"origin/{branch}"
            remote_exists = self._ref_exists(repo_root, remote_ref)
            if remote_exists:
                self._run(
                    ["git", "worktree", "add", "-b", branch, str(worktree_path), remote_ref],
                    cwd=repo_root,
                )
            else:
                raise AppError(
                    ErrorCode.INVALID_REQUEST,
                    f"branch '{branch}' does not exist locally or on remote",
                    status_code=400,
                )

        logger.info("created worktree for branch %s at %s", branch, worktree_path)
        self._ensure_gitignore(repo_root)
        return worktree_path

    def remove_worktree(self, repo_root: Path, branch: str) -> None:
        """Remove the worktree for a given branch."""
        slug = self._branch_slug(branch)
        worktree_path = repo_root / _WORKTREES_DIR / slug
        if worktree_path.is_dir():
            self._remove_worktree(repo_root, worktree_path)

    def list_worktrees(self, repo_root: Path) -> list[WorktreeInfo]:
        """List all worktrees for a repo using git worktree list --porcelain."""
        result = self._run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=repo_root,
        )

        worktrees: list[WorktreeInfo] = []
        current_path: Path | None = None
        current_branch: str = ""
        current_sha: str = ""

        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                if current_path is not None:
                    worktrees.append(WorktreeInfo(
                        path=current_path,
                        branch=current_branch,
                        head_sha=current_sha,
                        is_primary=(current_path == repo_root),
                    ))
                current_path = Path(line[9:])
                current_branch = ""
                current_sha = ""
            elif line.startswith("HEAD "):
                current_sha = line[5:]
            elif line.startswith("branch "):
                # branch refs/heads/feature/auth → feature/auth
                current_branch = line[7:].removeprefix("refs/heads/")
            elif line == "detached":
                current_branch = "(detached)"

        # Don't forget the last entry
        if current_path is not None:
            worktrees.append(WorktreeInfo(
                path=current_path,
                branch=current_branch,
                head_sha=current_sha,
                is_primary=(current_path == repo_root),
            ))

        return worktrees

    def cleanup_stale(self, repo_root: Path, active_branches: set[str]) -> int:
        """Remove worktrees whose branches are not in the active set.

        Returns the number of worktrees removed.
        """
        worktrees = self.list_worktrees(repo_root)
        removed = 0
        for wt in worktrees:
            if wt.is_primary:
                continue
            if wt.branch not in active_branches:
                try:
                    self._remove_worktree(repo_root, wt.path)
                    removed += 1
                    logger.info("cleaned up stale worktree: %s (branch=%s)", wt.path, wt.branch)
                except AppError:
                    logger.warning("failed to clean up worktree: %s", wt.path, exc_info=True)
        return removed

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _count_total_worktrees(self) -> int:
        """Count all non-primary worktrees across all repos."""
        total = 0
        projects = self.settings.projects_root
        if not projects.is_dir():
            return 0
        for entry in projects.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if not (entry / ".git").exists():
                continue
            try:
                wts = self.list_worktrees(entry)
                total += sum(1 for w in wts if not w.is_primary)
            except AppError:
                pass
        return total

    @staticmethod
    def _branch_slug(branch: str) -> str:
        """Convert a branch name to a filesystem-safe slug.

        feature/auth → feature-auth
        Adds a short hash suffix for collision safety.
        """
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", branch).strip("-").lower()
        slug = slug[:50] or "branch"
        # Add 6-char hash suffix for collision resistance
        suffix = hashlib.sha256(branch.encode()).hexdigest()[:6]
        return f"{slug}-{suffix}"

    @staticmethod
    def _current_branch(path: Path) -> str:
        """Get the current branch of a working directory."""
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            logger.warning("failed to get current branch for %s: %s", path, stderr)
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"cannot determine current branch: {stderr[:200]}",
                status_code=500,
            )
        return result.stdout.strip()

    @staticmethod
    def _branch_exists(repo_root: Path, branch: str) -> bool:
        """Check if a branch exists locally."""
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", branch],
            capture_output=True, text=True, check=False,
        )
        return result.returncode == 0

    @staticmethod
    def _ref_exists(repo_root: Path, ref: str) -> bool:
        """Check if a git ref exists."""
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", ref],
            capture_output=True, text=True, check=False,
        )
        return result.returncode == 0

    def _remove_worktree(self, repo_root: Path, worktree_path: Path) -> None:
        """Remove a worktree using git worktree remove --force."""
        self._run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=repo_root,
        )
        logger.info("removed worktree at %s", worktree_path)

    @staticmethod
    def _ensure_gitignore(repo_root: Path) -> None:
        """Ensure .worktrees/ is in .gitignore."""
        gitignore = repo_root / ".gitignore"
        pattern = f"/{_WORKTREES_DIR}/"
        if gitignore.is_file():
            content = gitignore.read_text()
            if pattern in content:
                return
            if not content.endswith("\n"):
                content += "\n"
            content += f"{pattern}\n"
            gitignore.write_text(content)
        else:
            # Don't create a .gitignore just for this — best-effort only
            pass

    def _run(
        self,
        command: list[str],
        *,
        cwd: Path,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                cwd=cwd,
                check=True,
                text=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or "").strip()
            logger.warning("git worktree command failed: %s", stderr)
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                stderr[:500] if stderr else "git worktree command failed",
                status_code=500,
            ) from exc
