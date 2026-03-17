from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import subprocess
from typing import Iterable

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_shared.models import ErrorCode

logger = logging.getLogger(__name__)

IGNORED_DIRECTORIES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".terraform",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}

TEXT_FILE_SUFFIXES = {
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".go",
    ".graphql",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".tf",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

TEXT_FILE_NAMES = {"Dockerfile", "Makefile", "Procfile"}


@dataclass(frozen=True)
class DiffSnapshot:
    repo_root: Path
    branch: str
    pathspec: str
    diff_text: str
    changed_files: list[str]
    dirty: bool


class GitService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def resolve_target(self, workspace_subpath: str) -> Path:
        base = self.settings.projects_root.resolve()
        target = (base / workspace_subpath).resolve()
        if not target.is_relative_to(base):
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"workspace_subpath escapes the projects root: {workspace_subpath}",
                status_code=400,
            )
        if not target.exists():
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"workspace_subpath does not exist on the remote box: {workspace_subpath}",
                status_code=400,
            )
        return target

    def repo_root_for_subpath(self, workspace_subpath: str) -> Path:
        target = self.resolve_target(workspace_subpath)
        cwd = target if target.is_dir() else target.parent
        completed = self._run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            cwd=cwd,
        )
        return Path(completed.stdout.strip()).resolve()

    def current_branch(self, repo_root: Path) -> str:
        return self._run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
        ).stdout.strip()

    def has_uncommitted_changes(self, repo_root: Path, pathspec: str = ".") -> bool:
        return bool(
            self._run(
                ["git", "-C", str(repo_root), "status", "--porcelain", "--", pathspec],
                cwd=repo_root,
            ).stdout.strip()
        )

    def build_workspace_context(
        self,
        workspace_subpath: str,
        *,
        max_files: int = 20,
        max_chars_per_file: int = 5000,
        max_total_chars: int = 24000,
    ) -> str:
        target = self.resolve_target(workspace_subpath)
        files = list(self.select_files(target, max_files=max_files))

        sections = [f"Target path: {target}"]

        try:
            repo_root = self.repo_root_for_subpath(workspace_subpath)
            sections.append(f"Git repo root: {repo_root}")
            status = self.status_short(repo_root, self._pathspec(repo_root, target))
            if status:
                sections.append(f"Git status:\n{status}")
        except AppError:
            logger.debug("workspace_subpath %s is not inside a git repo, skipping git context", workspace_subpath)

        if target.is_dir():
            tree_lines = [str(path.relative_to(target)) for path in files]
            sections.append("Selected file tree:\n" + ("\n".join(tree_lines) if tree_lines else "<empty>"))

        remaining_chars = max_total_chars
        content_sections: list[str] = []
        for file_path in files:
            if remaining_chars <= 0:
                break

            snippet = self.read_text(file_path, max_chars_per_file=max_chars_per_file)
            if snippet is None:
                continue

            if len(snippet) > remaining_chars:
                snippet = snippet[:remaining_chars] + "\n...[truncated]"

            label_root = target.parent if target.is_file() else target
            relative = file_path.relative_to(label_root)
            content_sections.append(f"File: {relative}\n{snippet}")
            remaining_chars -= len(snippet)

        if content_sections:
            sections.append("Selected file contents:\n" + "\n\n".join(content_sections))

        return "\n\n".join(sections)

    def apply_patch(self, workspace_subpath: str, patch_text: str) -> Path:
        if not patch_text.strip():
            raise AppError(
                ErrorCode.INVALID_PROVIDER_OUTPUT,
                "provider did not return a patch",
                status_code=502,
            )

        repo_root = self.repo_root_for_subpath(workspace_subpath)
        self._run(
            ["git", "-C", str(repo_root), "apply", "--recount", "--whitespace=nowarn", "-"],
            cwd=repo_root,
            input_text=patch_text,
        )
        return repo_root

    def collect_diff_snapshot(self, workspace_subpath: str, base_branch: str) -> DiffSnapshot:
        target = self.resolve_target(workspace_subpath)
        repo_root = self.repo_root_for_subpath(workspace_subpath)
        pathspec = self._pathspec(repo_root, target)
        branch = self.current_branch(repo_root)
        dirty = self.has_uncommitted_changes(repo_root, pathspec)

        sections: list[str] = []

        if dirty:
            staged = self._run(
                ["git", "-C", str(repo_root), "diff", "--cached", "--patch", "--stat", "--", pathspec],
                cwd=repo_root,
            ).stdout.strip()
            unstaged = self._run(
                ["git", "-C", str(repo_root), "diff", "--patch", "--stat", "--", pathspec],
                cwd=repo_root,
            ).stdout.strip()
            if staged:
                sections.append("Staged changes:\n" + staged)
            if unstaged:
                sections.append("Unstaged changes:\n" + unstaged)
            changed_files = self.changed_files(repo_root, pathspec)
        else:
            if branch == base_branch:
                raise AppError(
                    ErrorCode.INVALID_REQUEST,
                    f"no changes found relative to {base_branch}",
                    status_code=400,
                )
            diff = self._run(
                ["git", "-C", str(repo_root), "diff", "--patch", "--stat", f"{base_branch}...HEAD", "--", pathspec],
                cwd=repo_root,
            ).stdout.strip()
            if not diff:
                raise AppError(
                    ErrorCode.INVALID_REQUEST,
                    f"no diff found relative to {base_branch}",
                    status_code=400,
                )
            sections.append(diff)
            changed_files = self._run(
                ["git", "-C", str(repo_root), "diff", "--name-only", f"{base_branch}...HEAD", "--", pathspec],
                cwd=repo_root,
            ).stdout.splitlines()

        return DiffSnapshot(
            repo_root=repo_root,
            branch=branch,
            pathspec=pathspec,
            diff_text="\n\n".join(section for section in sections if section),
            changed_files=[line.strip() for line in changed_files if line.strip()],
            dirty=dirty,
        )

    def changed_files(self, repo_root: Path, pathspec: str = ".") -> list[str]:
        lines = self._run(
            ["git", "-C", str(repo_root), "status", "--porcelain", "--", pathspec],
            cwd=repo_root,
        ).stdout.splitlines()
        files: list[str] = []
        for line in lines:
            candidate = line[3:].strip()
            if candidate:
                files.append(candidate)
        return files

    def status_short(self, repo_root: Path, pathspec: str = ".") -> str:
        return self._run(
            ["git", "-C", str(repo_root), "status", "--short", "--", pathspec],
            cwd=repo_root,
        ).stdout.strip()

    def ensure_branch(self, repo_root: Path, branch: str) -> None:
        if self.current_branch(repo_root) == branch:
            return

        exists = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", branch],
            cwd=repo_root,
            text=True,
            capture_output=True,
        )
        if exists.returncode == 0:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"branch already exists: {branch}. Pass a different --head-branch.",
                status_code=400,
            )

        self._run(["git", "-C", str(repo_root), "switch", "-c", branch], cwd=repo_root)

    def commit_all(self, repo_root: Path, message: str) -> str:
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = self.settings.git_author_name
        env["GIT_AUTHOR_EMAIL"] = self.settings.git_author_email
        env["GIT_COMMITTER_NAME"] = self.settings.git_author_name
        env["GIT_COMMITTER_EMAIL"] = self.settings.git_author_email

        self._run(["git", "-C", str(repo_root), "add", "-A"], cwd=repo_root, env=env)
        self._run(["git", "-C", str(repo_root), "commit", "-m", message], cwd=repo_root, env=env)
        return self._run(["git", "-C", str(repo_root), "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()

    def remote_origin_url(self, repo_root: Path) -> str:
        return self._run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            cwd=repo_root,
        ).stdout.strip()

    def _pathspec(self, repo_root: Path, target: Path) -> str:
        if target == repo_root:
            return "."
        return str(target.relative_to(repo_root))

    def select_files(self, target: Path, *, max_files: int) -> Iterable[Path]:
        if target.is_file():
            yield target
            return

        count = 0
        for root, dirs, files in os.walk(target):
            dirs[:] = sorted(directory for directory in dirs if directory not in IGNORED_DIRECTORIES)
            for file_name in sorted(files):
                candidate = Path(root) / file_name
                if not self._is_probably_text(candidate):
                    continue
                yield candidate
                count += 1
                if count >= max_files:
                    return

    def _is_probably_text(self, path: Path) -> bool:
        if path.name in TEXT_FILE_NAMES or path.suffix.lower() in TEXT_FILE_SUFFIXES:
            return True
        try:
            sample = path.read_bytes()[:1024]
        except OSError:
            return False
        return b"\x00" not in sample

    def read_text(self, path: Path, *, max_chars_per_file: int) -> str | None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if len(content) > max_chars_per_file:
            return content[:max_chars_per_file] + "\n...[truncated]"
        return content

    def _run(
        self,
        command: list[str],
        *,
        cwd: Path,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                cwd=cwd,
                check=True,
                text=True,
                input=input_text,
                capture_output=True,
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or "").strip()
            logger.debug("git command failed: %s", stderr)
            code, status = self._classify_git_error(stderr)
            raise AppError(
                code,
                (stderr[:200] if stderr else "git command failed"),
                status_code=status,
            ) from exc

    @staticmethod
    def _classify_git_error(stderr: str) -> tuple[ErrorCode, int]:
        """Classify a git error as client (400) or server (500) based on stderr content."""
        server_indicators = (
            "permission denied",
            "no space left on device",
            "disk quota exceeded",
            "cannot lock ref",
            "unable to create",
            "loose object",
            "corrupt",
            "bad object",
            "broken pipe",
        )
        lower = stderr.lower()
        for indicator in server_indicators:
            if indicator in lower:
                return ErrorCode.INTERNAL_ERROR, 500
        return ErrorCode.INVALID_REQUEST, 400
