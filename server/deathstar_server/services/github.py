from __future__ import annotations

import base64
import os
from pathlib import Path
import re
import subprocess
import tempfile

import logging

import httpx

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_shared.models import ErrorCode, ReviewFinding, ReviewVerdict

logger = logging.getLogger(__name__)

SSH_REMOTE_RE = re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^.]+?)(?:\.git)?$")
HTTPS_REMOTE_RE = re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^.]+?)(?:\.git)?$")


_PROTECTED_BRANCHES = frozenset({"main", "master"})


class GitHubService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_remote_origin(self, repo_root: Path) -> None:
        """Ensure the repo has an HTTPS-based ``origin`` remote for GitHub.

        If origin is missing, we try to infer the GitHub URL from the repo name.
        If origin uses SSH (``git@github.com:…``), it gets rewritten to HTTPS so
        that ``GIT_ASKPASS`` token injection works at push time.
        """
        try:
            url = self._origin_url(repo_root)
        except AppError:
            # No origin at all — try to add one from repo directory name
            token = self.settings.github_token
            if not token:
                return  # Can't infer without GitHub access
            repo_name = repo_root.name
            # Best-effort: try common owner patterns
            logger.info("repo %s has no origin remote", repo_name)
            return

        # Rewrite SSH → HTTPS so GIT_ASKPASS works
        ssh_match = SSH_REMOTE_RE.match(url)
        if ssh_match:
            owner, repo = ssh_match.group("owner"), ssh_match.group("repo")
            https_url = f"https://github.com/{owner}/{repo}.git"
            subprocess.run(
                ["git", "-C", str(repo_root), "remote", "set-url", "origin", https_url],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            logger.info("rewrote SSH origin to HTTPS: %s → %s", url, https_url)

    async def create_pull_request(
        self,
        *,
        repo_root: Path,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
        draft: bool,
    ) -> str:
        token = self._require_token()
        owner, repo = self._parse_remote(self._origin_url(repo_root))
        payload = {
            "title": title,
            "body": body,
            "head": head_branch,
            "base": base_branch,
            "draft": draft,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                json=payload,
                headers=headers,
            )

        if response.status_code in {401, 403}:
            raise AppError(
                ErrorCode.AUTH_ERROR,
                f"GitHub rejected the PR request (HTTP {response.status_code})",
                status_code=response.status_code,
            )
        if response.status_code >= 400:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"GitHub PR creation failed (HTTP {response.status_code})",
                status_code=response.status_code,
            )

        data = response.json()
        return str(data["html_url"])

    def push_branch(self, repo_root: Path, branch: str) -> None:
        if branch in _PROTECTED_BRANCHES:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"refusing to push directly to protected branch '{branch}' — create a feature branch instead",
                status_code=400,
            )
        token = self._require_token()
        askpass_content = (
            "#!/bin/sh\n"
            'case "$1" in\n'
            '  *Username*) echo "x-access-token" ;;\n'
            '  *Password*) echo "$GITHUB_TOKEN" ;;\n'
            '  *) echo "" ;;\n'
            "esac\n"
        )

        fd, askpass_name = tempfile.mkstemp(prefix="deathstar-askpass-")
        try:
            os.write(fd, askpass_content.encode())
        finally:
            os.close(fd)
        askpass_path = Path(askpass_name)
        askpass_path.chmod(0o700)

        env = os.environ.copy()
        env["GIT_ASKPASS"] = str(askpass_path)
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GITHUB_TOKEN"] = token

        try:
            subprocess.run(
                ["git", "-C", str(repo_root), "push", "--set-upstream", "origin", branch],
                cwd=repo_root,
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or str(exc)).strip()
            # Sanitize token from error output
            if token and token in stderr:
                stderr = stderr.replace(token, "***")
            raise AppError(
                ErrorCode.AUTH_ERROR,
                f"failed to push branch to GitHub: {stderr}",
                status_code=401,
            ) from exc
        finally:
            askpass_path.unlink(missing_ok=True)

    async def list_pull_requests(
        self,
        *,
        repo_root: Path,
        state: str = "open",
    ) -> list[dict]:
        """List pull requests for a repo via GitHub API."""
        token = self._require_token()
        owner, repo = self._parse_remote(self._origin_url(repo_root))
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls",
                params={"state": state, "per_page": 30, "sort": "updated", "direction": "desc"},
                headers=headers,
            )
        if not response.is_success:
            raise AppError(
                ErrorCode.AUTH_ERROR,
                f"GitHub API error ({response.status_code})",
                status_code=502,
            )
        results = []
        for pr in response.json():
            results.append({
                "number": pr["number"],
                "title": pr["title"],
                "state": pr["state"],
                "user": pr["user"]["login"],
                "head_branch": pr["head"]["ref"],
                "base_branch": pr["base"]["ref"],
                "updated_at": pr["updated_at"],
                "additions": pr.get("additions"),
                "deletions": pr.get("deletions"),
                "changed_files": pr.get("changed_files"),
                "draft": pr.get("draft", False),
                "url": pr["html_url"],
            })
        return results

    async def fetch_pr_diff(self, *, owner: str, repo: str, pr_number: int) -> str:
        """Fetch the diff of a PR via GitHub API."""
        token = self._require_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3.diff",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
                headers=headers,
            )
        if not response.is_success:
            raise AppError(
                ErrorCode.AUTH_ERROR,
                f"GitHub API error fetching PR diff ({response.status_code})",
                status_code=502,
            )
        return response.text

    async def fetch_pr_changed_files(
        self,
        *,
        owner: str,
        repo: str,
        pr_number: int,
        branch: str,
        max_files: int = 15,
        max_chars_per_file: int = 8000,
        max_total_chars: int = 80_000,
    ) -> dict[str, str]:
        """Fetch the full contents of files changed in a PR.

        Returns a mapping of file path → file contents for the head branch.
        Respects token budget limits to avoid blowing up prompt size.
        """
        token = self._require_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            # List files changed in the PR (paginated, up to 300)
            files_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files",
                params={"per_page": 100},
                headers=headers,
            )
            if not files_resp.is_success:
                return {}

            changed_files = files_resp.json()
            # Sort by patch size descending so we prioritise files with the most changes
            changed_files.sort(key=lambda f: len(f.get("patch", "")), reverse=True)

            result: dict[str, str] = {}
            total_chars = 0

            for file_info in changed_files[:max_files]:
                filename = file_info.get("filename", "")
                status = file_info.get("status", "")
                # Skip removed files and binary files
                if status == "removed" or not filename:
                    continue

                try:
                    content_resp = await client.get(
                        f"https://api.github.com/repos/{owner}/{repo}/contents/{filename}",
                        params={"ref": branch},
                        headers=headers,
                    )
                    if not content_resp.is_success:
                        continue

                    content_data = content_resp.json()
                    # Skip large files (>1MB base64)
                    if content_data.get("size", 0) > 1_000_000:
                        continue
                    if content_data.get("encoding") != "base64":
                        continue

                    content = base64.b64decode(content_data["content"]).decode("utf-8")
                except (UnicodeDecodeError, KeyError):
                    continue

                if len(content) > max_chars_per_file:
                    content = content[:max_chars_per_file] + "\n\n[... file truncated]"

                if total_chars + len(content) > max_total_chars:
                    break

                result[filename] = content
                total_chars += len(content)

            return result

    async def fetch_pr_info(self, *, owner: str, repo: str, pr_number: int) -> dict:
        """Fetch PR metadata via GitHub API."""
        token = self._require_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}",
                headers=headers,
            )
        if not response.is_success:
            raise AppError(
                ErrorCode.AUTH_ERROR,
                f"GitHub API error ({response.status_code})",
                status_code=502,
            )
        return response.json()

    @staticmethod
    def parse_pr_url(url: str) -> tuple[str, str, int]:
        """Parse a GitHub PR URL into (owner, repo, number)."""
        match = re.match(
            r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)",
            url,
        )
        if not match:
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"not a valid GitHub PR URL: {url}",
                status_code=400,
            )
        return match.group("owner"), match.group("repo"), int(match.group("number"))

    async def submit_review(
        self,
        *,
        owner: str,
        repo: str,
        pr_number: int,
        summary: str,
        verdict: ReviewVerdict,
        findings: list[ReviewFinding],
    ) -> dict:
        """Post a PR review with inline comments to GitHub."""
        token = self._require_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        event_map = {
            ReviewVerdict.APPROVE: "APPROVE",
            ReviewVerdict.REQUEST_CHANGES: "REQUEST_CHANGES",
            ReviewVerdict.COMMENT: "COMMENT",
        }

        comments = []
        for f in findings:
            if not f.file or f.line_start is None:
                continue
            comment: dict = {
                "path": f.file,
                "line": f.line_end or f.line_start,
                "side": "RIGHT",
                "body": f"**{f.severity.value.upper()}**: {f.title}\n\n{f.body}",
            }
            if f.line_end and f.line_start and f.line_end > f.line_start:
                comment["start_line"] = f.line_start
                comment["start_side"] = "RIGHT"
            if f.suggested_code:
                comment["body"] += f"\n\n```suggestion\n{f.suggested_code}\n```"
            comments.append(comment)

        payload = {
            "body": summary,
            "event": event_map.get(verdict, "COMMENT"),
            "comments": comments,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
                json=payload,
                headers=headers,
            )

        if not response.is_success:
            error_body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            error_msg = error_body.get("message", response.text[:300]) if isinstance(error_body, dict) else response.text[:300]
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"GitHub review submission failed ({response.status_code}): {error_msg}",
                status_code=502,
            )

        return response.json()

    @staticmethod
    def _replace_by_lines(
        content: str, start: int, end: int, replacement: str,
    ) -> str | None:
        """Replace lines *start* through *end* (1-indexed, inclusive) with *replacement*."""
        raw_lines = content.replace("\r\n", "\n").splitlines(keepends=True)
        if start < 1 or end > len(raw_lines):
            return None
        before = "".join(raw_lines[: start - 1])
        after = "".join(raw_lines[end:])
        if not replacement.endswith("\n") and after:
            replacement += "\n"
        return before + replacement + after

    @staticmethod
    def _fuzzy_replace(content: str, original: str, replacement: str) -> str | None:
        """Try to replace *original* in *content*, tolerating minor whitespace differences.

        Returns the modified content on success, or ``None`` if no match was found.
        """
        # 1. Exact match
        if original in content:
            return content.replace(original, replacement, 1)

        def _norm(text: str) -> str:
            return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").splitlines())

        def _replace_at_line_index(content: str, match_lines: list[str], i: int, replacement: str) -> str:
            raw_lines = content.replace("\r\n", "\n").splitlines(keepends=True)
            before = "".join(raw_lines[:i])
            after = "".join(raw_lines[i + len(match_lines) :])
            if not replacement.endswith("\n") and after:
                replacement += "\n"
            return before + replacement + after

        # 2. Normalize line endings + strip trailing whitespace per line
        norm_content = _norm(content)
        norm_original = _norm(original)
        if norm_original in norm_content:
            norm_lines = norm_content.splitlines()
            orig_lines = norm_original.splitlines()
            for i in range(len(norm_lines) - len(orig_lines) + 1):
                if norm_lines[i : i + len(orig_lines)] == orig_lines:
                    return _replace_at_line_index(content, orig_lines, i, replacement)

        # 3. Strip leading/trailing blank lines from original and retry
        stripped = original.strip("\n\r ")
        if stripped != original and stripped in content:
            return content.replace(stripped, replacement, 1)

        # 4. Ignore leading whitespace (indentation differences) — compare
        # only the stripped content of each line.
        def _strip_lines(text: str) -> list[str]:
            return [line.strip() for line in text.replace("\r\n", "\n").splitlines() if line.strip()]

        stripped_original = _strip_lines(original)
        if len(stripped_original) >= 1:
            content_lines = content.replace("\r\n", "\n").splitlines()
            content_stripped = [line.strip() for line in content_lines]
            for i in range(len(content_lines)):
                # Find a window where the stripped lines match
                window = [s for s in content_stripped[i : i + len(content_lines)] if s][:len(stripped_original)]
                if window == stripped_original:
                    # Count how many raw lines this spans
                    matched = 0
                    j = i
                    while matched < len(stripped_original) and j < len(content_lines):
                        if content_lines[j].strip():
                            matched += 1
                        j += 1
                    return _replace_at_line_index(content, content_lines[i:j], i, replacement)

        return None

    @staticmethod
    def _extract_identifiers_from_imports(code: str) -> set[str]:
        """Extract imported identifiers from Python and JS/TS import statements."""
        identifiers: set[str] = set()

        def _resolve_alias(name: str) -> str:
            """Return the local alias if 'as' is present, otherwise the name."""
            parts = re.split(r"\s+as\s+", name.strip())
            return parts[-1].strip()

        for line in code.splitlines():
            stripped = line.strip().rstrip(";")

            # Python: from foo import bar, baz  /  from foo import (bar, baz)
            m = re.match(r"^from\s+\S+\s+import\s+(.+)$", stripped)
            if m:
                imports_part = m.group(1).strip(" ()")
                for name in imports_part.split(","):
                    name = name.strip()
                    if name and name != "\\":
                        identifiers.add(_resolve_alias(name))
                continue

            # JS/TS: import type { foo, bar } from '...'
            m = re.match(r"^import\s+type\s+\{([^}]+)\}\s+from\s+", stripped)
            if m:
                for name in m.group(1).split(","):
                    resolved = _resolve_alias(name)
                    if resolved:
                        identifiers.add(resolved)
                continue

            # JS/TS: import { foo, bar } from '...'
            m = re.match(r"^import\s+\{([^}]+)\}\s+from\s+", stripped)
            if m:
                for name in m.group(1).split(","):
                    resolved = _resolve_alias(name)
                    if resolved:
                        identifiers.add(resolved)
                continue

            # JS/TS: import foo from '...'
            m = re.match(r"^import\s+(\w+)\s+from\s+", stripped)
            if m:
                identifiers.add(m.group(1))
                continue

            # Python: import foo / import foo as bar
            m = re.match(r"^import\s+(.+)$", stripped)
            if m:
                for name in m.group(1).split(","):
                    resolved = _resolve_alias(name)
                    if resolved:
                        identifiers.add(resolved.split(".")[0])
                continue

        return identifiers

    @staticmethod
    def _check_suggestion_safety(
        original_content: str, modified_content: str, finding_title: str,
    ) -> str | None:
        """Check if a suggestion would break the file by removing used identifiers.

        Returns a reason string if the suggestion is unsafe, or None if safe.
        """
        # Extract identifiers from import lines in both versions
        original_imports = GitHubService._extract_identifiers_from_imports(original_content)
        modified_imports = GitHubService._extract_identifiers_from_imports(modified_content)

        removed_imports = original_imports - modified_imports
        if not removed_imports:
            return None

        # Check if any removed identifiers are still referenced in non-import lines
        non_import_lines = []
        for line in modified_content.splitlines():
            stripped = line.strip()
            # Skip import lines, comments, and empty lines
            if (
                stripped.startswith(("import ", "from ", "#", "//", "/*", "*"))
                or not stripped
            ):
                continue
            non_import_lines.append(stripped)

        non_import_text = "\n".join(non_import_lines)

        still_used = []
        for ident in removed_imports:
            # Use word boundary matching to avoid false positives
            # e.g., "Path" should not match "PathLike"
            if re.search(rf"\b{re.escape(ident)}\b", non_import_text):
                still_used.append(ident)

        if still_used:
            reason = (
                f"suggestion '{finding_title}' would remove import(s) "
                f"still used in the file: {', '.join(sorted(still_used))}"
            )
            logger.warning("safety check blocked: %s", reason)
            return reason

        return None

    async def apply_file_changes(
        self,
        *,
        owner: str,
        repo: str,
        pr_number: int,
        findings: list[ReviewFinding],
        commit_message: str | None = None,
    ) -> dict:
        """Commit accepted suggestions to the PR branch via GitHub Git Data API."""
        token = self._require_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        # Get PR info to find the head branch
        pr_info = await self.fetch_pr_info(owner=owner, repo=repo, pr_number=pr_number)
        branch = pr_info["head"]["ref"]
        if branch in ("main", "master"):
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "cannot apply suggestions directly to main/master",
                status_code=400,
            )

        async with httpx.AsyncClient(timeout=60.0) as client:
            # 1. Get HEAD ref
            ref_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/ref/heads/{branch}",
                headers=headers,
            )
            if not ref_resp.is_success:
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    f"failed to get branch ref ({ref_resp.status_code})",
                    status_code=502,
                )
            head_sha = ref_resp.json()["object"]["sha"]

            # 2. Get the commit to find the tree
            commit_resp = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}/git/commits/{head_sha}",
                headers=headers,
            )
            if not commit_resp.is_success:
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    f"failed to get commit ({commit_resp.status_code})",
                    status_code=502,
                )
            base_tree_sha = commit_resp.json()["tree"]["sha"]

            # 3. Group findings by file and apply changes
            file_changes: dict[str, list[ReviewFinding]] = {}
            for f in findings:
                if f.suggested_code is not None and f.original_code is not None:
                    file_changes.setdefault(f.file, []).append(f)

            if not file_changes:
                raise AppError(
                    ErrorCode.INVALID_REQUEST,
                    "no findings with both original_code and suggested_code to apply",
                    status_code=400,
                )

            tree_entries = []
            applied_titles: list[str] = []
            skipped_titles: list[str] = []

            for file_path, file_findings in file_changes.items():
                # Fetch current file content
                content_resp = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}",
                    params={"ref": branch},
                    headers=headers,
                )
                if not content_resp.is_success:
                    raise AppError(
                        ErrorCode.INTERNAL_ERROR,
                        f"failed to fetch {file_path} ({content_resp.status_code})",
                        status_code=502,
                    )

                content_data = content_resp.json()
                original_content = base64.b64decode(content_data["content"]).decode("utf-8")
                file_content = original_content

                # Apply suggestions bottom-up (by line number descending) so that
                # earlier line numbers aren't shifted by later replacements.
                sorted_findings = sorted(
                    file_findings,
                    key=lambda f: f.line_start or 0,
                    reverse=True,
                )
                for finding in sorted_findings:
                    if finding.original_code and finding.suggested_code is not None:
                        result = self._fuzzy_replace(
                            file_content, finding.original_code, finding.suggested_code,
                        )
                        if result is None and finding.line_start:
                            # Fallback: replace by line numbers from the review
                            end = finding.line_end or finding.line_start
                            result = self._replace_by_lines(
                                file_content, finding.line_start, end, finding.suggested_code,
                            )
                        if result is not None:
                            # Safety check: verify the suggestion doesn't remove
                            # imports/identifiers that are still used in the file
                            safety_reason = self._check_suggestion_safety(
                                file_content, result, finding.title,
                            )
                            if safety_reason:
                                skipped_titles.append(
                                    f"{finding.title} (blocked: {safety_reason})"
                                )
                            else:
                                file_content = result
                                applied_titles.append(finding.title)
                        else:
                            skipped_titles.append(finding.title)

                # Only include files that actually changed
                if file_content == original_content:
                    continue

                # Create a new blob
                blob_resp = await client.post(
                    f"https://api.github.com/repos/{owner}/{repo}/git/blobs",
                    json={
                        "content": base64.b64encode(file_content.encode("utf-8")).decode("ascii"),
                        "encoding": "base64",
                    },
                    headers=headers,
                )
                if not blob_resp.is_success:
                    raise AppError(
                        ErrorCode.INTERNAL_ERROR,
                        f"failed to create blob for {file_path} ({blob_resp.status_code})",
                        status_code=502,
                    )

                tree_entries.append({
                    "path": file_path,
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_resp.json()["sha"],
                })

            if not tree_entries:
                skipped_detail = ", ".join(skipped_titles[:3]) if skipped_titles else "unknown"
                raise AppError(
                    ErrorCode.INVALID_REQUEST,
                    f"no suggestions could be matched to the current file contents "
                    f"(skipped: {skipped_detail}). The code may have changed since the review.",
                    status_code=400,
                )

            # Build a contextual commit message
            if not commit_message:
                summary_items = [f"- {t}" for t in applied_titles[:8]]
                commit_message = (
                    f"Apply {len(applied_titles)} review suggestion"
                    f"{'s' if len(applied_titles) != 1 else ''}\n\n"
                    + "\n".join(summary_items)
                )
                if len(applied_titles) > 8:
                    commit_message += f"\n- ... and {len(applied_titles) - 8} more"

            # 4. Create a new tree
            tree_resp = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/git/trees",
                json={"base_tree": base_tree_sha, "tree": tree_entries},
                headers=headers,
            )
            if not tree_resp.is_success:
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    f"failed to create tree ({tree_resp.status_code})",
                    status_code=502,
                )
            new_tree_sha = tree_resp.json()["sha"]

            # 5. Create a new commit
            new_commit_resp = await client.post(
                f"https://api.github.com/repos/{owner}/{repo}/git/commits",
                json={
                    "message": commit_message,
                    "tree": new_tree_sha,
                    "parents": [head_sha],
                },
                headers=headers,
            )
            if not new_commit_resp.is_success:
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    f"failed to create commit ({new_commit_resp.status_code})",
                    status_code=502,
                )
            new_commit_sha = new_commit_resp.json()["sha"]

            # 6. Update the branch ref
            update_resp = await client.patch(
                f"https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{branch}",
                json={"sha": new_commit_sha},
                headers=headers,
            )
            if not update_resp.is_success:
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    f"failed to update branch ref ({update_resp.status_code})",
                    status_code=502,
                )

        return {
            "commit_sha": new_commit_sha,
            "files_changed": len(tree_entries),
            "commit_url": f"https://github.com/{owner}/{repo}/commit/{new_commit_sha}",
            "applied": applied_titles,
            "skipped": skipped_titles,
        }

    def _origin_url(self, repo_root: Path) -> str:
        try:
            completed = subprocess.run(
                ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
                cwd=repo_root,
                check=True,
                text=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or exc.stdout or str(exc)).strip()
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"unable to determine git remote origin: {stderr}",
                status_code=400,
            ) from exc
        return completed.stdout.strip()

    def _require_token(self) -> str:
        if not self.settings.github_token:
            raise AppError(
                ErrorCode.INTEGRATION_NOT_CONFIGURED,
                "GitHub integration is not configured on the remote runtime",
                status_code=400,
            )
        return self.settings.github_token

    def _parse_remote(self, remote_url: str) -> tuple[str, str]:
        for pattern in (SSH_REMOTE_RE, HTTPS_REMOTE_RE):
            match = pattern.match(remote_url)
            if match:
                return match.group("owner"), match.group("repo")
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            f"unsupported git remote for GitHub PR automation: {remote_url}",
            status_code=400,
        )
