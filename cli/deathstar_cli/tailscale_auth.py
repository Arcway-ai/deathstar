from __future__ import annotations

import getpass

import httpx
import typer

OAUTH_TOKEN_URL = "https://api.tailscale.com/api/v2/oauth/token"
CREATE_KEY_URL = "https://api.tailscale.com/api/v2/tailnet/-/keys"


def prompt_for_credentials() -> tuple[str, str]:
    """Prompt the user for their Tailscale OAuth client ID and client secret."""
    client_id = input("Tailscale OAuth client ID: ").strip()
    if not client_id:
        raise typer.BadParameter("client ID cannot be empty")

    client_secret = getpass.getpass("Tailscale OAuth client secret: ")
    if not client_secret:
        raise typer.BadParameter("client secret cannot be empty")

    return client_id, client_secret


def get_oauth_token(client_id: str, client_secret: str) -> str:
    """Exchange OAuth client credentials for an access token."""
    response = httpx.post(
        OAUTH_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        headers={"Accept": "application/json"},
        timeout=30.0,
    )
    if not response.is_success:
        detail = response.text
        try:
            detail = response.json().get("message", detail)
        except Exception:
            pass
        raise typer.BadParameter(
            f"Tailscale OAuth token exchange failed ({response.status_code}): {detail}\n"
            "Check that your client ID and client secret are correct."
        )
    data = response.json()

    token = data.get("access_token")
    if not token:
        raise typer.BadParameter("Tailscale OAuth response did not include an access token")
    return token


def create_auth_key(
    access_token: str,
    *,
    reusable: bool = True,
    ephemeral: bool = True,
    preauthorized: bool = True,
    tags: list[str] | None = None,
    description: str = "DeathStar",
) -> str:
    """Create a Tailscale auth key using an OAuth access token."""
    capabilities: dict = {
        "devices": {
            "create": {
                "reusable": reusable,
                "ephemeral": ephemeral,
                "preauthorized": preauthorized,
            },
        },
    }

    if tags:
        capabilities["devices"]["create"]["tags"] = tags

    body: dict = {
        "capabilities": capabilities,
        "description": description,
    }

    response = httpx.post(
        CREATE_KEY_URL,
        json=body,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )
    if not response.is_success:
        detail = response.text
        try:
            detail = response.json().get("message", detail)
        except Exception:
            pass
        hint = ""
        if "must have tags" in detail:
            hint = (
                "\n\nOAuth-created auth keys require at least one tag. "
                "Set DEATHSTAR_TAILSCALE_ADVERTISE_TAGS=tag:deathstar in .env "
                "and make sure the tag is defined in your tailnet ACLs:\n"
                '  "tagOwners": { "tag:deathstar": ["autogroup:admin"] }'
            )
        raise typer.BadParameter(
            f"Tailscale API returned {response.status_code}: {detail}{hint}"
        )
    data = response.json()

    key = data.get("key")
    if not key:
        raise typer.BadParameter("Tailscale API response did not include an auth key")
    return key
