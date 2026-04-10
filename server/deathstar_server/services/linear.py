from __future__ import annotations

import logging
from typing import Any

import httpx

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_shared.models import ErrorCode

logger = logging.getLogger(__name__)

_LINEAR_API_URL = "https://api.linear.app/graphql"

# Rate limit warning threshold — Linear's limit is 1500 req/hr.
_RATE_LIMIT_WARN_THRESHOLD = 200


class LinearService:
    """GraphQL client for the Linear API.

    Follows the GitHubService pattern: takes Settings, exposes typed async
    methods, and maps errors to AppError.  Uses httpx.AsyncClient for
    HTTP and raw GraphQL queries (no codegen SDK).

    Authentication uses a raw API key in the ``Authorization`` header
    (no ``Bearer`` prefix, per Linear docs).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # Low-level GraphQL transport
    # ------------------------------------------------------------------

    def _require_key(self) -> str:
        key = self._settings.linear_api_key
        if not key:
            raise AppError(
                ErrorCode.INTEGRATION_NOT_CONFIGURED,
                "Linear integration is not configured — set LINEAR_API_KEY",
                status_code=400,
            )
        return key

    async def _execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """Execute a GraphQL query against the Linear API.

        Retries on 429 (rate-limited) with exponential backoff.
        """
        import asyncio

        key = self._require_key()
        headers = {
            "Authorization": key,
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        attempt = 0
        while True:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    _LINEAR_API_URL,
                    json=payload,
                    headers=headers,
                )

            # Track rate limits
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining:
                try:
                    if int(remaining) < _RATE_LIMIT_WARN_THRESHOLD:
                        logger.warning(
                            "Linear rate limit low: %s requests remaining",
                            remaining,
                        )
                except ValueError:
                    pass

            if resp.status_code == 429:
                attempt += 1
                if attempt > max_retries:
                    raise AppError(
                        ErrorCode.RATE_LIMITED,
                        "Linear API rate limit exceeded after retries",
                        status_code=429,
                    )
                wait = 2 ** attempt
                logger.warning("Linear 429 — retrying in %ds (attempt %d/%d)", wait, attempt, max_retries)
                await asyncio.sleep(wait)
                continue

            if resp.status_code in (401, 403):
                raise AppError(
                    ErrorCode.AUTH_ERROR,
                    f"Linear rejected the request (HTTP {resp.status_code})",
                    status_code=resp.status_code,
                )

            if resp.status_code >= 400:
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    f"Linear API error (HTTP {resp.status_code}): {resp.text[:300]}",
                    status_code=502,
                )

            body = resp.json()
            if "errors" in body:
                errors = body["errors"]
                msg = errors[0].get("message", str(errors)) if errors else "unknown"
                raise AppError(
                    ErrorCode.INTERNAL_ERROR,
                    f"Linear GraphQL error: {msg}",
                    status_code=502,
                )

            return body.get("data", {})

    # ------------------------------------------------------------------
    # Teams
    # ------------------------------------------------------------------

    async def list_teams(self) -> list[dict[str, Any]]:
        """Return all teams the API key has access to."""
        query = """
        query {
            teams {
                nodes {
                    id
                    name
                    key
                }
            }
        }
        """
        data = await self._execute(query)
        return data.get("teams", {}).get("nodes", [])

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    async def list_projects(self, team_id: str) -> list[dict[str, Any]]:
        """List projects accessible to a team."""
        query = """
        query($teamId: String!) {
            team(id: $teamId) {
                projects {
                    nodes {
                        id
                        name
                        slugId
                        state
                        url
                    }
                }
            }
        }
        """
        data = await self._execute(query, {"teamId": team_id})
        team = data.get("team")
        if not team:
            return []
        return team.get("projects", {}).get("nodes", [])

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Fetch a single project by ID."""
        query = """
        query($id: String!) {
            project(id: $id) {
                id
                name
                slugId
                state
                url
                teams {
                    nodes {
                        id
                        name
                        key
                    }
                }
            }
        }
        """
        data = await self._execute(query, {"id": project_id})
        return data.get("project")

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    async def list_project_issues(self, project_id: str) -> list[dict[str, Any]]:
        """List all issues for a project."""
        query = """
        query($projectId: String!) {
            project(id: $projectId) {
                issues {
                    nodes {
                        id
                        identifier
                        title
                        description
                        priority
                        url
                        branchName
                        state {
                            name
                            type
                        }
                        assignee {
                            name
                            displayName
                        }
                    }
                }
            }
        }
        """
        data = await self._execute(query, {"projectId": project_id})
        project = data.get("project")
        if not project:
            return []
        return project.get("issues", {}).get("nodes", [])

    async def get_issue(self, issue_id: str) -> dict[str, Any] | None:
        """Fetch a single issue by ID."""
        query = """
        query($id: String!) {
            issue(id: $id) {
                id
                identifier
                title
                description
                priority
                url
                branchName
                state {
                    id
                    name
                    type
                }
                assignee {
                    name
                    displayName
                }
                project {
                    id
                    name
                }
            }
        }
        """
        data = await self._execute(query, {"id": issue_id})
        return data.get("issue")

    async def update_issue_state(self, issue_id: str, state_id: str) -> dict[str, Any]:
        """Update the workflow state of an issue."""
        query = """
        mutation($id: String!, $stateId: String!) {
            issueUpdate(id: $id, input: { stateId: $stateId }) {
                success
                issue {
                    id
                    identifier
                    state {
                        id
                        name
                        type
                    }
                }
            }
        }
        """
        data = await self._execute(query, {"id": issue_id, "stateId": state_id})
        return data.get("issueUpdate", {})

    # ------------------------------------------------------------------
    # Workflow States
    # ------------------------------------------------------------------

    async def list_workflow_states(self, team_id: str) -> list[dict[str, Any]]:
        """List all workflow states for a team (backlog, todo, in_progress, done, cancelled)."""
        query = """
        query($teamId: String!) {
            team(id: $teamId) {
                states {
                    nodes {
                        id
                        name
                        type
                        position
                    }
                }
            }
        }
        """
        data = await self._execute(query, {"teamId": team_id})
        team = data.get("team")
        if not team:
            return []
        return team.get("states", {}).get("nodes", [])

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    async def create_webhook(
        self,
        team_id: str,
        url: str,
        secret: str,
    ) -> dict[str, Any]:
        """Create a webhook subscription for a team."""
        query = """
        mutation($teamId: String!, $url: String!, $secret: String!) {
            webhookCreate(input: {
                teamId: $teamId,
                url: $url,
                secret: $secret,
                resourceTypes: ["Issue", "Project"]
            }) {
                success
                webhook {
                    id
                    url
                    enabled
                }
            }
        }
        """
        data = await self._execute(query, {
            "teamId": team_id,
            "url": url,
            "secret": secret,
        })
        return data.get("webhookCreate", {})
