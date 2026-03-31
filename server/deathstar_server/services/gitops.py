from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import random
import subprocess
from typing import Iterable

from unidiff import PatchSet, UnidiffParseError

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

_DEATHSTAR_DOMAIN = "deathstar.ai"

_STAR_WARS_CHARACTERS = [
    {"name": "Darth Vader", "email": f"darth.vader@{_DEATHSTAR_DOMAIN}"},
    {"name": "Luke Skywalker", "email": f"luke.skywalker@{_DEATHSTAR_DOMAIN}"},
    {"name": "Princess Leia", "email": f"princess.leia@{_DEATHSTAR_DOMAIN}"},
    {"name": "Han Solo", "email": f"han.solo@{_DEATHSTAR_DOMAIN}"},
    {"name": "Obi-Wan Kenobi", "email": f"obi-wan.kenobi@{_DEATHSTAR_DOMAIN}"},
    {"name": "Yoda", "email": f"yoda@{_DEATHSTAR_DOMAIN}"},
    {"name": "Emperor Palpatine", "email": f"emperor.palpatine@{_DEATHSTAR_DOMAIN}"},
    {"name": "Chewbacca", "email": f"chewbacca@{_DEATHSTAR_DOMAIN}"},
    {"name": "Boba Fett", "email": f"boba.fett@{_DEATHSTAR_DOMAIN}"},
    {"name": "Darth Maul", "email": f"darth.maul@{_DEATHSTAR_DOMAIN}"},
    {"name": "Mace Windu", "email": f"mace.windu@{_DEATHSTAR_DOMAIN}"},
    {"name": "Ahsoka Tano", "email": f"ahsoka.tano@{_DEATHSTAR_DOMAIN}"},
    {"name": "Anakin Skywalker", "email": f"anakin.skywalker@{_DEATHSTAR_DOMAIN}"},
    {"name": "Padmé Amidala", "email": f"padme.amidala@{_DEATHSTAR_DOMAIN}"},
    {"name": "Qui-Gon Jinn", "email": f"qui-gon.jinn@{_DEATHSTAR_DOMAIN}"},
    {"name": "Count Dooku", "email": f"count.dooku@{_DEATHSTAR_DOMAIN}"},
    {"name": "Lando Calrissian", "email": f"lando.calrissian@{_DEATHSTAR_DOMAIN}"},
    {"name": "Kylo Ren", "email": f"kylo.ren@{_DEATHSTAR_DOMAIN}"},
    {"name": "Rey Skywalker", "email": f"rey.skywalker@{_DEATHSTAR_DOMAIN}"},
    {"name": "Finn", "email": f"finn@{_DEATHSTAR_DOMAIN}"},
    {"name": "Poe Dameron", "email": f"poe.dameron@{_DEATHSTAR_DOMAIN}"},
    {"name": "Grand Moff Tarkin", "email": f"grand.moff.tarkin@{_DEATHSTAR_DOMAIN}"},
    {"name": "Jango Fett", "email": f"jango.fett@{_DEATHSTAR_DOMAIN}"},
    {"name": "General Grievous", "email": f"general.grievous@{_DEATHSTAR_DOMAIN}"},
    {"name": "R2-D2", "email": f"r2d2@{_DEATHSTAR_DOMAIN}"},
    {"name": "C-3PO", "email": f"c3po@{_DEATHSTAR_DOMAIN}"},
    {"name": "Din Djarin", "email": f"din.djarin@{_DEATHSTAR_DOMAIN}"},
    {"name": "Grogu", "email": f"grogu@{_DEATHSTAR_DOMAIN}"},
    {"name": "Cassian Andor", "email": f"cassian.andor@{_DEATHSTAR_DOMAIN}"},
    {"name": "K-2SO", "email": f"k2so@{_DEATHSTAR_DOMAIN}"},
    {"name": "Chirrut Îmwe", "email": f"chirrut.imwe@{_DEATHSTAR_DOMAIN}"},
    {"name": "Jyn Erso", "email": f"jyn.erso@{_DEATHSTAR_DOMAIN}"},
    {"name": "Admiral Ackbar", "email": f"admiral.ackbar@{_DEATHSTAR_DOMAIN}"},
    {"name": "Wedge Antilles", "email": f"wedge.antilles@{_DEATHSTAR_DOMAIN}"},
    {"name": "Jabba the Hutt", "email": f"jabba@{_DEATHSTAR_DOMAIN}"},
    {"name": "Asajj Ventress", "email": f"asajj.ventress@{_DEATHSTAR_DOMAIN}"},
    {"name": "Captain Rex", "email": f"captain.rex@{_DEATHSTAR_DOMAIN}"},
    {"name": "Sabine Wren", "email": f"sabine.wren@{_DEATHSTAR_DOMAIN}"},
    {"name": "Hera Syndulla", "email": f"hera.syndulla@{_DEATHSTAR_DOMAIN}"},
    {"name": "Kanan Jarrus", "email": f"kanan.jarrus@{_DEATHSTAR_DOMAIN}"},
    {"name": "Grand Admiral Thrawn", "email": f"thrawn@{_DEATHSTAR_DOMAIN}"},
    {"name": "Nien Nunb", "email": f"nien.nunb@{_DEATHSTAR_DOMAIN}"},
    {"name": "Kit Fisto", "email": f"kit.fisto@{_DEATHSTAR_DOMAIN}"},
    {"name": "Plo Koon", "email": f"plo.koon@{_DEATHSTAR_DOMAIN}"},
    {"name": "Barriss Offee", "email": f"barriss.offee@{_DEATHSTAR_DOMAIN}"},
    {"name": "Saw Gerrera", "email": f"saw.gerrera@{_DEATHSTAR_DOMAIN}"},
    {"name": "Mon Mothma", "email": f"mon.mothma@{_DEATHSTAR_DOMAIN}"},
    {"name": "Bail Organa", "email": f"bail.organa@{_DEATHSTAR_DOMAIN}"},
]


def _random_star_wars_character() -> dict[str, str]:
    return random.choice(_STAR_WARS_CHARACTERS)


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
        branch = self._run(
            ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
        ).stdout.strip()

        # During rebase, HEAD is detached — provide a useful label instead
        if branch == "HEAD":
            git_dir = repo_root / ".git"
            rebase_merge = git_dir / "rebase-merge"
            rebase_apply = git_dir / "rebase-apply"
            if rebase_merge.is_dir():
                head_name = (rebase_merge / "head-name").read_text().strip().removeprefix("refs/heads/")
                onto_sha = (rebase_merge / "onto").read_text().strip()[:7]
                return f"{head_name} (rebasing onto {onto_sha})"
            if rebase_apply.is_dir():
                head_name_file = rebase_apply / "head-name"
                if head_name_file.exists():
                    head_name = head_name_file.read_text().strip().removeprefix("refs/heads/")
                    return f"{head_name} (rebasing)"
                return "HEAD (rebasing)"

        return branch

    def primary_branch(self, repo_root: Path) -> str:
        """Return the current branch of the primary checkout."""
        return self.current_branch(repo_root)

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
            full_tree = self.full_file_tree(target)
            sections.append("Complete file tree:\n" + ("\n".join(full_tree) if full_tree else "<empty>"))
            selected_tree = [str(path.relative_to(target)) for path in files]
            if len(selected_tree) < len(full_tree):
                sections.append("Files with contents included below:\n" + "\n".join(selected_tree))

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

    @staticmethod
    def _normalize_patch(patch_text: str) -> str:
        """Fix common LLM-generated patch issues before applying.

        Handles: Windows line endings, missing context-line space prefix,
        blank lines inside hunks, and missing trailing newlines.
        """
        import re as _re

        # Normalize line endings
        text = patch_text.replace("\r\n", "\n").replace("\r", "\n")

        lines = text.split("\n")
        # Drop the trailing empty string produced by a final newline
        if lines and lines[-1] == "":
            lines = lines[:-1]
        fixed: list[str] = []
        in_hunk = False

        for line in lines:
            # Track whether we're inside a hunk
            if line.startswith("diff --git ") or line.startswith("--- ") or line.startswith("+++ "):
                in_hunk = False
                fixed.append(line)
                continue

            if _re.match(r"^@@ .+ @@", line):
                in_hunk = True
                fixed.append(line)
                continue

            if in_hunk:
                # Lines inside a hunk must start with ' ', '+', '-', or '\'
                if line == "":
                    # Empty line in a hunk = context line (should be ' ')
                    fixed.append(" ")
                elif not line.startswith((" ", "+", "-", "\\")):
                    # Missing prefix — treat as context line
                    fixed.append(" " + line)
                else:
                    fixed.append(line)
            else:
                fixed.append(line)

        result = "\n".join(fixed)
        # Ensure patch ends with newline
        if result and not result.endswith("\n"):
            result += "\n"
        return result

    def apply_patch(self, workspace_subpath: str, patch_text: str) -> Path:
        if not patch_text.strip():
            raise AppError(
                ErrorCode.INVALID_PROVIDER_OUTPUT,
                "provider did not return a patch",
                status_code=502,
            )

        repo_root = self.repo_root_for_subpath(workspace_subpath)
        normalized = self._normalize_patch(patch_text)

        # Pre-validate: parse patch structure and check file paths
        self._validate_patch(repo_root, normalized)

        # 3-tier fallback: strict → fuzzy → zero-context
        strategies = [
            (["git", "-C", str(repo_root), "apply", "--recount", "--whitespace=nowarn", "-"], "strict"),
            (["git", "-C", str(repo_root), "apply", "--recount", "--whitespace=nowarn", "--fuzz=1", "-"], "fuzz=1"),
            (["git", "-C", str(repo_root), "apply", "--recount", "--whitespace=nowarn", "--unidiff-zero", "-"], "unidiff-zero"),
        ]

        last_error: AppError | None = None
        for cmd, label in strategies:
            try:
                self._run(cmd, cwd=repo_root, input_text=normalized)
                if label != "strict":
                    logger.warning("patch applied with %s strategy (context mismatch)", label)
                break
            except AppError as exc:
                last_error = exc
                logger.debug("patch strategy %s failed: %s", label, exc.message[:200])
        else:
            # All strategies failed — provide diagnostic message
            diagnosis = self._diagnose_patch_failure(
                last_error.message if last_error else "", normalized
            )
            raise AppError(
                ErrorCode.INVALID_PROVIDER_OUTPUT,
                f"Could not apply patch after 3 strategies. {diagnosis}",
                status_code=502,
            )

        # Post-validate: check that patched Python files still parse
        self._validate_syntax_post_patch(repo_root)

        return repo_root

    @staticmethod
    def _validate_patch(repo_root: Path, patch_text: str) -> None:
        """Best-effort patch validation. Checks file paths if parseable.

        unidiff is stricter than git apply, so parse failures are logged
        as warnings and do NOT block the patch — git apply may still succeed.
        Only confirmed-bad file paths (targeting nonexistent files) raise.
        """
        try:
            patchset = PatchSet.from_string(patch_text)
        except UnidiffParseError as exc:
            # unidiff can't parse it, but git apply might still work — just warn
            logger.warning("unidiff could not parse patch (will still try git apply): %s", exc)
            # Fall back to regex-based file path extraction
            import re
            for match in re.finditer(r"^--- a/(.+)$", patch_text, re.MULTILINE):
                rel_path = match.group(1).strip()
                if rel_path == "/dev/null":
                    continue
                full_path = repo_root / rel_path
                if not full_path.exists():
                    raise AppError(
                        ErrorCode.INVALID_PROVIDER_OUTPUT,
                        f"patch targets nonexistent file: {rel_path}. "
                        "The LLM may have hallucinated this path.",
                        status_code=502,
                    )
            return

        for patched_file in patchset:
            target_path = patched_file.path
            if not target_path or target_path == "/dev/null":
                continue
            # Strip a/ or b/ prefix from git diff paths
            if target_path.startswith(("a/", "b/")):
                target_path = target_path[2:]

            full_path = repo_root / target_path
            if patched_file.is_added_file:
                logger.info("patch creates new file: %s", target_path)
            elif not full_path.exists():
                raise AppError(
                    ErrorCode.INVALID_PROVIDER_OUTPUT,
                    f"patch targets nonexistent file: {target_path}. "
                    "The LLM may have hallucinated this path.",
                    status_code=502,
                )

    @staticmethod
    def _validate_syntax_post_patch(repo_root: Path) -> None:
        """Check that modified Python files still have valid syntax."""
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), "diff", "--name-only", "--cached"],
                capture_output=True, text=True, check=False,
            )
            # Also check unstaged changes
            result2 = subprocess.run(
                ["git", "-C", str(repo_root), "diff", "--name-only"],
                capture_output=True, text=True, check=False,
            )
            changed = set(result.stdout.splitlines() + result2.stdout.splitlines())
        except (subprocess.CalledProcessError, FileNotFoundError):
            return

        for rel_path in changed:
            if not rel_path.strip().endswith(".py"):
                continue
            full = repo_root / rel_path.strip()
            if not full.is_file():
                continue
            try:
                source = full.read_text(encoding="utf-8", errors="replace")
                compile(source, str(full), "exec")
            except SyntaxError as exc:
                # Revert the patch so we don't leave broken files
                subprocess.run(
                    ["git", "-C", str(repo_root), "checkout", "."],
                    capture_output=True, text=True,
                )
                raise AppError(
                    ErrorCode.INVALID_PROVIDER_OUTPUT,
                    f"patch produced invalid Python syntax in {rel_path}:{exc.lineno}: {exc.msg}",
                    status_code=502,
                ) from exc

    @staticmethod
    def _diagnose_patch_failure(stderr: str, patch_text: str) -> str:
        """Translate git apply errors into actionable messages."""
        lower = stderr.lower()
        if "does not match" in lower or "context" in lower:
            return (
                "Context lines don't match the actual file. "
                "The LLM likely hallucinated file contents. "
                "Try re-running — the two-pass workflow should fetch fresh file contents."
            )
        if "no such file" in lower or "does not exist" in lower:
            return (
                "Patch references files that don't exist in the repository. "
                "Check that file paths match the actual repo structure."
            )
        if "already exists" in lower:
            return "Patch tries to create a file that already exists."
        if "corrupt" in lower or "trailing" in lower:
            return "Patch has formatting issues (trailing whitespace or corruption)."
        return stderr[:500] if stderr else "Unknown patch application error."

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
        character = _random_star_wars_character()
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = character["name"]
        env["GIT_AUTHOR_EMAIL"] = character["email"]
        env["GIT_COMMITTER_NAME"] = character["name"]
        env["GIT_COMMITTER_EMAIL"] = character["email"]
        # Corepack env so pre-commit hooks that invoke yarn/pnpm don't prompt
        env["COREPACK_ENABLE_AUTO_INSTALL"] = "1"

        self._run(["git", "-C", str(repo_root), "add", "-A"], cwd=repo_root, env=env)
        self._run(["git", "-C", str(repo_root), "commit", "-m", message], cwd=repo_root, env=env)
        return self._run(["git", "-C", str(repo_root), "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()

    @staticmethod
    def install_deps(repo_root: Path) -> str | None:
        """Install project dependencies so git hooks (husky, etc.) work.

        Detects the package manager from lock files and runs install.
        Returns a short status string, or None if no package manager detected.
        """
        import shutil

        cwd = str(repo_root)

        # Enable corepack so the repo's packageManager field is respected
        # (e.g. "yarn@4.x" gets the exact version instead of a global install).
        corepack_env = {**os.environ, "COREPACK_ENABLE_AUTO_INSTALL": "1"}
        if shutil.which("corepack"):
            subprocess.run(
                ["corepack", "enable"],
                cwd=cwd, capture_output=True, text=True, check=False,
                timeout=30, env=corepack_env,
            )

        # Detect package manager from lock files (yarn before npm — a repo
        # may have both if npm was run accidentally, but yarn.lock is canonical).
        if (repo_root / "yarn.lock").exists():
            pkg_mgr, run_cmd = "yarn", ["yarn", "install"]
        elif (repo_root / "pnpm-lock.yaml").exists():
            pkg_mgr, run_cmd = "pnpm", ["pnpm", "install"]
        elif (repo_root / "package-lock.json").exists() and shutil.which("npm"):
            pkg_mgr, run_cmd = "npm", ["npm", "install", "--ignore-scripts=false"]
        else:
            pkg_mgr = None

        if pkg_mgr:
            subprocess.run(
                run_cmd,
                cwd=cwd, capture_output=True, text=True, check=False,
                timeout=120, env=corepack_env,
            )
            # Run husky install / prepare if present
            pkg_json = repo_root / "package.json"
            if pkg_json.exists():
                import json as _json
                try:
                    scripts = _json.loads(pkg_json.read_text()).get("scripts", {})
                    if "prepare" in scripts:
                        subprocess.run(
                            [pkg_mgr, "run", "prepare"],
                            cwd=cwd, capture_output=True, text=True, check=False,
                            timeout=30, env=corepack_env,
                        )
                except (ValueError, OSError):
                    pass
            return pkg_mgr
        elif (repo_root / "requirements.txt").exists() and shutil.which("pip"):
            subprocess.run(
                ["pip", "install", "-r", "requirements.txt"],
                cwd=cwd, capture_output=True, text=True, check=False,
                timeout=120,
            )
            return "pip"
        elif (repo_root / "pyproject.toml").exists() and shutil.which("uv"):
            subprocess.run(
                ["uv", "sync"],
                cwd=cwd, capture_output=True, text=True, check=False,
                timeout=120,
            )
            return "uv"
        return None

    def remote_origin_url(self, repo_root: Path) -> str:
        return self._run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            cwd=repo_root,
        ).stdout.strip()

    def _pathspec(self, repo_root: Path, target: Path) -> str:
        if target == repo_root:
            return "."
        return str(target.relative_to(repo_root))

    def full_file_tree(self, target: Path, *, max_files: int = 500) -> list[str]:
        """Return repo-relative paths for all text files, up to max_files.

        Unlike select_files, this returns a much larger list (paths only, no
        content) so that LLMs know which files actually exist.
        """
        if target.is_file():
            return [target.name]
        paths: list[str] = []
        for root, dirs, files in os.walk(target):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRECTORIES)
            for file_name in sorted(files):
                candidate = Path(root) / file_name
                if not self._is_probably_text(candidate):
                    continue
                paths.append(str(candidate.relative_to(target)))
                if len(paths) >= max_files:
                    return paths
        return paths

    def read_files_by_paths(
        self,
        workspace_subpath: str,
        file_paths: list[str],
        *,
        max_chars_per_file: int = 8000,
    ) -> dict[str, str]:
        """Read specific files by repo-relative path. Returns {path: content}."""
        target = self.resolve_target(workspace_subpath)
        repo_root = target if target.is_dir() else target.parent
        result: dict[str, str] = {}
        for rel_path in file_paths:
            full = (repo_root / rel_path).resolve()
            if not full.is_relative_to(repo_root):
                continue
            content = self.read_text(full, max_chars_per_file=max_chars_per_file)
            if content is not None:
                result[rel_path] = content
        return result

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
                (stderr[:500] if stderr else "git command failed"),
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
