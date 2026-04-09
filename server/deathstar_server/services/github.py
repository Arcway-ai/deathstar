from __future__ import annotations

import base64
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

from githubkit import GitHub, TokenAuthStrategy
from githubkit.exception import RequestFailed

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_shared.models import ErrorCode, ReviewFinding, ReviewVerdict

logger = logging.getLogger(__name__)

SSH_REMOTE_RE = re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^.]+?)(?:\.git)?$")
HTTPS_REMOTE_RE = re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^.]+?)(?:\.git)?$")


_PROTECTED_BRANCHES = frozenset({"main", "master"})


def _raise_for_github_error(exc: RequestFailed, context: str) -> None:
    """Map githubkit RequestFailed to AppError."""
    status = exc.response.status_code
    if status in (401, 403):
        raise AppError(
            ErrorCode.AUTH_ERROR,
            f"GitHub rejected the request: {context} (HTTP {status})",
            status_code=status,
        ) from exc
    raise AppError(
        ErrorCode.INVALID_REQUEST,
        f"GitHub API error: {context} (HTTP {status})",
        status_code=502,
    ) from exc


class GitHubService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self) -> GitHub:
        """Create a githubkit client with the configured token."""
        token = self._require_token()
        return GitHub(TokenAuthStrategy(token), auto_retry=True)

    # ------------------------------------------------------------------
    # Git CLI operations (not API calls)
    # ------------------------------------------------------------------

    def ensure_remote_origin(self, repo_root: Path) -> None:
        """Ensure the repo has an HTTPS-based ``origin`` remote for GitHub."""
        try:
            url = self._origin_url(repo_root)
        except AppError:
            token = self.settings.github_token
            if not token:
                return
            repo_name = repo_root.name
            logger.info("repo %s has no origin remote", repo_name)
            return

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
            if token and token in stderr:
                stderr = stderr.replace(token, "***")
            raise AppError(
                ErrorCode.AUTH_ERROR,
                f"failed to push branch to GitHub: {stderr}",
                status_code=401,
            ) from exc
        finally:
            askpass_path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get_repo_full_name(self, repo_root: Path) -> str:
        """Return ``owner/repo`` for a local git repository."""
        owner, repo = self._parse_remote(self._origin_url(repo_root))
        return f"{owner}/{repo}"

    # ------------------------------------------------------------------
    # GitHub API operations via githubkit
    # ------------------------------------------------------------------

    async def create_pull_request(
        self,
        *,
        repo_root: Path,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
        draft: bool,
    ) -> dict:
        owner, repo = self._parse_remote(self._origin_url(repo_root))
        gh = self._client()
        try:
            resp = await gh.rest.pulls.async_create(
                owner, repo,
                title=title, body=body, head=head_branch, base=base_branch, draft=draft,
            )
        except RequestFailed as exc:
            _raise_for_github_error(exc, "PR creation failed")
        pr = resp.parsed_data
        return {
            "number": pr.number,
            "url": str(pr.html_url),
            "title": pr.title,
            "state": pr.state.value if hasattr(pr.state, "value") else pr.state,
            "user": pr.user.login if pr.user else "unknown",
            "head_branch": head_branch,
            "base_branch": base_branch,
            "draft": getattr(pr, "draft", False) or False,
            "additions": getattr(pr, "additions", None),
            "deletions": getattr(pr, "deletions", None),
            "changed_files": getattr(pr, "changed_files", None),
        }

    async def find_pull_request_for_branch(
        self,
        *,
        repo_root: Path,
        branch: str,
    ) -> dict | None:
        """Find an open PR whose head matches *branch*, or ``None``.

        Uses the single-PR GET endpoint so that ``mergeable`` and
        ``mergeable_state`` are included (the list endpoint omits them).
        """
        owner, repo = self._parse_remote(self._origin_url(repo_root))
        gh = self._client()
        try:
            resp = await gh.rest.pulls.async_list(
                owner, repo,
                state="open",
                head=f"{owner}:{branch}",
                per_page=1,
            )
        except RequestFailed as exc:
            logger.warning("failed to look up PR for branch %s: %s", branch, exc)
            return None
        if not resp.parsed_data:
            return None
        pr = resp.parsed_data[0]
        result = {
            "number": pr.number,
            "title": pr.title,
            "state": pr.state.value if hasattr(pr.state, "value") else pr.state,
            "user": pr.user.login if pr.user else "unknown",
            "head_branch": pr.head.ref,
            "base_branch": pr.base.ref,
            "updated_at": pr.updated_at.isoformat() if pr.updated_at else "",
            "additions": getattr(pr, "additions", None),
            "deletions": getattr(pr, "deletions", None),
            "changed_files": getattr(pr, "changed_files", None),
            "draft": getattr(pr, "draft", False) or False,
            "url": str(pr.html_url),
        }

        # The list endpoint doesn't include mergeable or body — fetch via GET
        # for the single PR to get the merge-conflict state and description.
        try:
            detail = await gh.rest.pulls.async_get(owner, repo, pr.number)
            pr_detail = detail.parsed_data
            result["mergeable"] = getattr(pr_detail, "mergeable", None)
            result["mergeable_state"] = getattr(pr_detail, "mergeable_state", None)
            result["body"] = getattr(pr_detail, "body", None) or ""
        except RequestFailed:
            logger.debug("failed to fetch mergeable state for PR #%s", pr.number)
            result["mergeable"] = None
            result["mergeable_state"] = None
            result["body"] = ""

        return result

    async def list_pull_requests(
        self,
        *,
        repo_root: Path,
        state: str = "open",
    ) -> list[dict]:
        owner, repo = self._parse_remote(self._origin_url(repo_root))
        gh = self._client()
        try:
            resp = await gh.rest.pulls.async_list(
                owner, repo,
                state=state, per_page=30, sort="updated", direction="desc",
            )
        except RequestFailed as exc:
            _raise_for_github_error(exc, "listing PRs")
        results = []
        for pr in resp.parsed_data:
            results.append({
                "number": pr.number,
                "title": pr.title,
                "state": pr.state.value if hasattr(pr.state, "value") else pr.state,
                "user": pr.user.login if pr.user else "unknown",
                "head_branch": pr.head.ref,
                "base_branch": pr.base.ref,
                "updated_at": pr.updated_at.isoformat() if pr.updated_at else "",
                "additions": getattr(pr, "additions", None),
                "deletions": getattr(pr, "deletions", None),
                "changed_files": getattr(pr, "changed_files", None),
                "draft": getattr(pr, "draft", False) or False,
                "url": str(pr.html_url),
            })
        return results

    async def fetch_pr_diff(self, *, owner: str, repo: str, pr_number: int) -> str:
        gh = self._client()
        try:
            resp = await gh.arequest(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{pr_number}",
                headers={"Accept": "application/vnd.github.v3.diff"},
            )
        except RequestFailed as exc:
            _raise_for_github_error(exc, "fetching PR diff")
        return resp.text

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
        gh = self._client()
        try:
            files_resp = await gh.rest.pulls.async_list_files(
                owner, repo, pr_number, per_page=100,
            )
        except RequestFailed as exc:
            logger.warning("failed to list PR files for %s#%d: %s", repo, pr_number, exc)
            return {}

        changed_files = sorted(
            files_resp.parsed_data,
            key=lambda f: len(f.patch or "") if hasattr(f, "patch") else 0,
            reverse=True,
        )

        result: dict[str, str] = {}
        total_chars = 0

        for file_info in changed_files[:max_files]:
            filename = file_info.filename
            status = file_info.status
            if status == "removed" or not filename:
                continue

            try:
                content_resp = await gh.rest.repos.async_get_content(
                    owner, repo, filename, ref=branch,
                )
                content_data = content_resp.parsed_data
                # get_content can return a list for directories
                if isinstance(content_data, list):
                    continue
                if getattr(content_data, "size", 0) > 1_000_000:
                    continue
                if getattr(content_data, "encoding", None) != "base64":
                    continue
                raw_content = getattr(content_data, "content", "")
                content = base64.b64decode(raw_content).decode("utf-8")
            except (RequestFailed, UnicodeDecodeError, AttributeError):
                continue

            if len(content) > max_chars_per_file:
                content = content[:max_chars_per_file] + "\n\n[... file truncated]"

            if total_chars + len(content) > max_total_chars:
                break

            result[filename] = content
            total_chars += len(content)

        return result

    async def fetch_pr_info(self, *, owner: str, repo: str, pr_number: int) -> dict:
        gh = self._client()
        try:
            resp = await gh.rest.pulls.async_get(owner, repo, pr_number)
            # Return as dict for backward compat with callers that access via ["key"]
            return resp.json()
        except RequestFailed as exc:
            _raise_for_github_error(exc, "fetching PR info")

    @staticmethod
    def parse_pr_url(url: str) -> tuple[str, str, int]:
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

    async def fetch_pr_review_comments(
        self,
        *,
        owner: str,
        repo: str,
        pr_number: int,
    ) -> list[dict]:
        """Fetch existing review comments on a PR for context."""
        gh = self._client()
        comments: list[dict] = []

        # Get top-level PR reviews (approve/request changes/comment)
        try:
            reviews_resp = await gh.rest.pulls.async_list_reviews(
                owner, repo, pr_number, per_page=50,
            )
            for review in reviews_resp.parsed_data:
                if review.body and review.body.strip():
                    comments.append({
                        "type": "review",
                        "user": review.user.login if review.user else "unknown",
                        "state": review.state,
                        "body": review.body.strip(),
                    })
        except RequestFailed:
            pass

        # Get inline review comments (file-level and line-level)
        try:
            inline_resp = await gh.rest.pulls.async_list_review_comments(
                owner, repo, pr_number, per_page=100,
            )
            for comment in inline_resp.parsed_data:
                comments.append({
                    "type": "inline",
                    "user": comment.user.login if comment.user else "unknown",
                    "path": comment.path,
                    "line": getattr(comment, "line", None) or getattr(comment, "original_line", None),
                    "body": comment.body.strip() if comment.body else "",
                })
        except RequestFailed:
            pass

        # Get issue comments (general PR discussion)
        try:
            issue_resp = await gh.rest.issues.async_list_comments(
                owner, repo, pr_number, per_page=50,
            )
            for comment in issue_resp.parsed_data:
                if comment.body and comment.body.strip():
                    user = comment.user.login if comment.user else "unknown"
                    # Skip bot comments
                    if user.endswith("[bot]") or user in ("github-actions",):
                        continue
                    comments.append({
                        "type": "comment",
                        "user": user,
                        "body": comment.body.strip(),
                    })
        except RequestFailed:
            pass

        return comments

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
        gh = self._client()

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

        try:
            resp = await gh.rest.pulls.async_create_review(
                owner, repo, pr_number,
                body=summary,
                event=event_map.get(verdict, "COMMENT"),
                comments=comments,
            )
        except RequestFailed as exc:
            error_detail = ""
            try:
                error_detail = exc.response.json().get("message", "")
            except Exception:
                error_detail = exc.response.text[:300]
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"GitHub review submission failed ({exc.response.status_code}): {error_detail}",
                status_code=502,
            ) from exc

        return resp.json()

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
        gh = self._client()

        # Get PR info to find the head branch
        pr_info = await self.fetch_pr_info(owner=owner, repo=repo, pr_number=pr_number)
        branch = pr_info["head"]["ref"]
        if branch in ("main", "master"):
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                "cannot apply suggestions directly to main/master",
                status_code=400,
            )

        # 1. Get HEAD ref
        try:
            ref_resp = await gh.rest.git.async_get_ref(owner, repo, f"heads/{branch}")
            head_sha = ref_resp.parsed_data.object.sha
        except RequestFailed as exc:
            _raise_for_github_error(exc, "getting branch ref")

        # 2. Get the commit to find the tree
        try:
            commit_resp = await gh.rest.git.async_get_commit(owner, repo, head_sha)
            base_tree_sha = commit_resp.parsed_data.tree.sha
        except RequestFailed as exc:
            _raise_for_github_error(exc, "getting commit")

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
            try:
                content_resp = await gh.rest.repos.async_get_content(
                    owner, repo, file_path, ref=branch,
                )
                content_data = content_resp.parsed_data
                if isinstance(content_data, list):
                    raise AppError(ErrorCode.INTERNAL_ERROR, f"{file_path} is a directory", status_code=502)
                original_content = base64.b64decode(content_data.content).decode("utf-8")
            except RequestFailed as exc:
                _raise_for_github_error(exc, f"fetching {file_path}")

            file_content = original_content

            # Apply suggestions bottom-up
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
                        end = finding.line_end or finding.line_start
                        result = self._replace_by_lines(
                            file_content, finding.line_start, end, finding.suggested_code,
                        )
                    if result is not None:
                        safety_reason = self._check_suggestion_safety(
                            file_content, result, finding.title,
                        )
                        if safety_reason:
                            skipped_titles.append(f"{finding.title} (blocked: {safety_reason})")
                        else:
                            file_content = result
                            applied_titles.append(finding.title)
                    else:
                        skipped_titles.append(finding.title)

            if file_content == original_content:
                continue

            # Create a new blob
            try:
                blob_resp = await gh.rest.git.async_create_blob(
                    owner, repo,
                    content=base64.b64encode(file_content.encode("utf-8")).decode("ascii"),
                    encoding="base64",
                )
                blob_sha = blob_resp.parsed_data.sha
            except RequestFailed as exc:
                _raise_for_github_error(exc, f"creating blob for {file_path}")

            tree_entries.append({
                "path": file_path,
                "mode": "100644",
                "type": "blob",
                "sha": blob_sha,
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
        try:
            tree_resp = await gh.rest.git.async_create_tree(
                owner, repo,
                base_tree=base_tree_sha,
                tree=tree_entries,
            )
            new_tree_sha = tree_resp.parsed_data.sha
        except RequestFailed as exc:
            _raise_for_github_error(exc, "creating tree")

        # 5. Create a new commit
        try:
            new_commit_resp = await gh.rest.git.async_create_commit(
                owner, repo,
                message=commit_message,
                tree=new_tree_sha,
                parents=[head_sha],
            )
            new_commit_sha = new_commit_resp.parsed_data.sha
        except RequestFailed as exc:
            _raise_for_github_error(exc, "creating commit")

        # 6. Update the branch ref
        try:
            await gh.rest.git.async_update_ref(
                owner, repo, f"heads/{branch}",
                sha=new_commit_sha,
            )
        except RequestFailed as exc:
            _raise_for_github_error(exc, "updating branch ref")

        return {
            "commit_sha": new_commit_sha,
            "files_changed": len(tree_entries),
            "commit_url": f"https://github.com/{owner}/{repo}/commit/{new_commit_sha}",
            "applied": applied_titles,
            "skipped": skipped_titles,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Static text-manipulation helpers (unchanged)
    # ------------------------------------------------------------------

    @staticmethod
    def _replace_by_lines(
        content: str, start: int, end: int, replacement: str,
    ) -> str | None:
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

        norm_content = _norm(content)
        norm_original = _norm(original)
        if norm_original in norm_content:
            norm_lines = norm_content.splitlines()
            orig_lines = norm_original.splitlines()
            for i in range(len(norm_lines) - len(orig_lines) + 1):
                if norm_lines[i : i + len(orig_lines)] == orig_lines:
                    return _replace_at_line_index(content, orig_lines, i, replacement)

        stripped = original.strip("\n\r ")
        if stripped != original and stripped in content:
            return content.replace(stripped, replacement, 1)

        def _strip_lines(text: str) -> list[str]:
            return [line.strip() for line in text.replace("\r\n", "\n").splitlines() if line.strip()]

        stripped_original = _strip_lines(original)
        if len(stripped_original) >= 1:
            content_lines = content.replace("\r\n", "\n").splitlines()
            content_stripped = [line.strip() for line in content_lines]
            for i in range(len(content_lines)):
                window = [s for s in content_stripped[i : i + len(content_lines)] if s][:len(stripped_original)]
                if window == stripped_original:
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
        identifiers: set[str] = set()

        def _resolve_alias(name: str) -> str:
            parts = re.split(r"\s+as\s+", name.strip())
            return parts[-1].strip()

        for line in code.splitlines():
            stripped = line.strip().rstrip(";")

            m = re.match(r"^from\s+\S+\s+import\s+(.+)$", stripped)
            if m:
                imports_part = m.group(1).strip(" ()")
                for name in imports_part.split(","):
                    name = name.strip()
                    if name and name != "\\":
                        identifiers.add(_resolve_alias(name))
                continue

            m = re.match(r"^import\s+type\s+\{([^}]+)\}\s+from\s+", stripped)
            if m:
                for name in m.group(1).split(","):
                    resolved = _resolve_alias(name)
                    if resolved:
                        identifiers.add(resolved)
                continue

            m = re.match(r"^import\s+\{([^}]+)\}\s+from\s+", stripped)
            if m:
                for name in m.group(1).split(","):
                    resolved = _resolve_alias(name)
                    if resolved:
                        identifiers.add(resolved)
                continue

            m = re.match(r"^import\s+(\w+)\s+from\s+", stripped)
            if m:
                identifiers.add(m.group(1))
                continue

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
        original_imports = GitHubService._extract_identifiers_from_imports(original_content)
        modified_imports = GitHubService._extract_identifiers_from_imports(modified_content)

        removed_imports = original_imports - modified_imports
        if not removed_imports:
            return None

        non_import_lines = []
        for line in modified_content.splitlines():
            stripped = line.strip()
            if (
                stripped.startswith(("import ", "from ", "#", "//", "/*", "*"))
                or not stripped
            ):
                continue
            non_import_lines.append(stripped)

        non_import_text = "\n".join(non_import_lines)

        still_used = []
        for ident in removed_imports:
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
