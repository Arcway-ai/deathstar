from __future__ import annotations

import shutil
import subprocess
import time
import webbrowser

import httpx
import typer

DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
VERIFICATION_URL = "https://github.com/login/device"

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
    """Run the GitHub OAuth Device Flow."""
    response = httpx.post(
        DEVICE_CODE_URL,
        data={"client_id": client_id, "scope": REQUIRED_SCOPES},
        headers={"Accept": "application/json"},
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()

    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data.get("verification_uri", VERIFICATION_URL)
    interval = data.get("interval", 5)
    expires_in = data.get("expires_in", 900)

    typer.echo("")
    typer.echo(f"Open this URL in your browser:  {verification_uri}")
    typer.echo(f"Enter this code:                {user_code}")
    typer.echo("")

    try:
        webbrowser.open(verification_uri)
    except Exception:  # noqa: BLE001
        pass

    typer.echo("Waiting for authorization...")

    return _poll_for_token(client_id, device_code, interval, expires_in)


def _poll_for_token(client_id: str, device_code: str, interval: int, expires_in: int) -> str:
    deadline = time.time() + expires_in

    while time.time() < deadline:
        time.sleep(interval)

        response = httpx.post(
            ACCESS_TOKEN_URL,
            data={
                "client_id": client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval = data.get("interval", interval + 5)
            continue
        if error == "expired_token":
            raise typer.BadParameter("device code expired before authorization was completed")
        if error == "access_denied":
            raise typer.BadParameter("authorization was denied by the user")
        if error:
            raise typer.BadParameter(f"GitHub OAuth error: {error}")

        token = data.get("access_token")
        if token:
            return token

    raise typer.BadParameter("timed out waiting for GitHub authorization")
