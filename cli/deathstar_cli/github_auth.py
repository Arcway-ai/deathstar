from __future__ import annotations

import shutil
import subprocess
import webbrowser

import typer

from githubkit import GitHub
from githubkit.auth import OAuthDeviceAuthStrategy

REQUIRED_SCOPES = "repo"

NEW_TOKEN_URL = (
    "https://github.com/settings/tokens/new"
    "?scopes=repo"
    "&description=DeathStar"
)


def token_from_gh_cli() -> str | None:
    """Try to extract a token from an existing `gh` CLI login."""
    if not shutil.which("gh"):
        return None

    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    token = result.stdout.strip()
    return token if token else None


def login_via_gh_cli() -> str:
    """Run `gh auth login` interactively, then return the token."""
    typer.echo("Launching gh auth login...")
    subprocess.run(["gh", "auth", "login", "-s", REQUIRED_SCOPES], check=True)

    result = subprocess.run(
        ["gh", "auth", "token"],
        capture_output=True,
        text=True,
        check=True,
    )
    token = result.stdout.strip()
    if not token:
        raise typer.BadParameter("gh auth login succeeded but no token was returned")
    return token


def guided_pat_creation() -> str:
    """Open the browser to GitHub's token creation page and prompt the user to paste the token."""
    typer.echo("Opening GitHub in your browser to create a personal access token...")
    typer.echo(f"  URL: {NEW_TOKEN_URL}")
    typer.echo("")
    typer.echo("Steps:")
    typer.echo("  1. Set the token name (e.g. 'DeathStar')")
    typer.echo("  2. The 'repo' scope should already be selected")
    typer.echo("  3. Click 'Generate token'")
    typer.echo("  4. Copy the token and paste it below")
    typer.echo("")

    if typer.confirm("Open browser now?", default=True):
        try:
            webbrowser.open(NEW_TOKEN_URL)
        except Exception:  # noqa: BLE001
            typer.echo("Could not open browser automatically. Visit the URL above manually.")

    import getpass

    token = getpass.getpass("Paste your GitHub token: ")
    if not token.strip():
        raise typer.BadParameter("no token provided")
    return token.strip()


def run_device_flow(client_id: str) -> str:
    """Run the GitHub OAuth Device Flow using githubkit.

    githubkit handles the polling loop, interval backoff, and error
    handling internally via OAuthDeviceAuthStrategy.
    """

    def on_verification(data) -> None:
        user_code = data.user_code
        verification_uri = data.verification_uri

        typer.echo("")
        typer.echo(f"Open this URL in your browser:  {verification_uri}")
        typer.echo(f"Enter this code:                {user_code}")
        typer.echo("")

        try:
            webbrowser.open(str(verification_uri))
        except Exception:  # noqa: BLE001
            pass

        typer.echo("Waiting for authorization...")

    github = GitHub(OAuthDeviceAuthStrategy(
        client_id,
        on_verification=on_verification,
        scopes=[REQUIRED_SCOPES],
    ))

    try:
        auth = github.auth.exchange_token(github)
    except Exception as exc:
        raise typer.BadParameter(f"GitHub OAuth device flow failed: {exc}") from exc

    token = auth.token
    if not token:
        raise typer.BadParameter("device flow succeeded but no token was returned")
    return token
