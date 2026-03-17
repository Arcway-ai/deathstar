from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile

import httpx

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_shared.models import ErrorCode

SSH_REMOTE_RE = re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^.]+?)(?:\.git)?$")
HTTPS_REMOTE_RE = re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^.]+?)(?:\.git)?$")


class GitHubService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

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
            raise AppError(
                ErrorCode.AUTH_ERROR,
                f"failed to push branch to GitHub: {stderr}",
                status_code=401,
            ) from exc
        finally:
            askpass_path.unlink(missing_ok=True)

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
