from __future__ import annotations

import subprocess

VERSION = "0.10.1"


def git_commit_sha() -> str | None:
    """Return the short git commit SHA of the local repo, or None if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def full_version() -> str:
    """Return VERSION+commit, e.g. '0.2.0+abc1234'."""
    sha = git_commit_sha()
    return f"{VERSION}+{sha}" if sha else VERSION
