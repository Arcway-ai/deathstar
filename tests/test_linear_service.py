from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from deathstar_server.errors import AppError
from deathstar_server.services.linear import LinearService
from deathstar_shared.models import ErrorCode


@pytest.fixture
def settings() -> MagicMock:
    s = MagicMock()
    s.linear_api_key = "lin_test_key_123"
    return s


@pytest.fixture
def service(settings: MagicMock) -> LinearService:
    return LinearService(settings)


def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
    headers: dict | None = None,
) -> httpx.Response:
    """Build a fake httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text or ""
    resp.headers = headers or {}
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("No JSON")
    return resp


# ------------------------------------------------------------------
# _require_key
# ------------------------------------------------------------------


class TestRequireKey:
    def test_raises_when_not_configured(self) -> None:
        settings = MagicMock()
        settings.linear_api_key = None
        svc = LinearService(settings)
        with pytest.raises(AppError) as exc_info:
            svc._require_key()
        assert exc_info.value.code == ErrorCode.INTEGRATION_NOT_CONFIGURED

    def test_returns_key(self, service: LinearService) -> None:
        assert service._require_key() == "lin_test_key_123"


# ------------------------------------------------------------------
# _execute — error handling
# ------------------------------------------------------------------


class TestExecuteErrorHandling:
    @pytest.mark.asyncio
    async def test_401_raises_auth_error(self, service: LinearService) -> None:
        resp = _mock_response(status_code=401)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(AppError) as exc_info:
                await service._execute("query { viewer { id } }")
            assert exc_info.value.code == ErrorCode.AUTH_ERROR

    @pytest.mark.asyncio
    async def test_403_raises_auth_error(self, service: LinearService) -> None:
        resp = _mock_response(status_code=403)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(AppError) as exc_info:
                await service._execute("query { viewer { id } }")
            assert exc_info.value.code == ErrorCode.AUTH_ERROR

    @pytest.mark.asyncio
    async def test_500_raises_internal_error(self, service: LinearService) -> None:
        resp = _mock_response(status_code=500, text="Internal Server Error")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(AppError) as exc_info:
                await service._execute("query { viewer { id } }")
            assert exc_info.value.code == ErrorCode.INTERNAL_ERROR

    @pytest.mark.asyncio
    async def test_graphql_error_raises(self, service: LinearService) -> None:
        resp = _mock_response(
            json_data={"errors": [{"message": "Field not found"}]},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(AppError) as exc_info:
                await service._execute("query { bad }")
            assert "Field not found" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_non_json_response_raises(self, service: LinearService) -> None:
        resp = _mock_response(status_code=200, text="<html>Bad Gateway</html>")
        # json() raises ValueError for non-JSON
        resp.json.side_effect = ValueError("No JSON")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(AppError) as exc_info:
                await service._execute("query { viewer { id } }")
            assert exc_info.value.code == ErrorCode.INTERNAL_ERROR
            assert "non-JSON" in str(exc_info.value.message)


# ------------------------------------------------------------------
# _execute — retry logic
# ------------------------------------------------------------------


class TestExecuteRetry:
    @pytest.mark.asyncio
    async def test_ratelimited_graphql_error_retries_then_succeeds(
        self, service: LinearService,
    ) -> None:
        """Linear returns rate limits as HTTP 200 + GraphQL RATELIMITED error."""
        rate_limited = _mock_response(json_data={
            "errors": [{
                "message": "Rate limit exceeded",
                "extensions": {"code": "RATELIMITED"},
            }],
        })
        success = _mock_response(json_data={"data": {"teams": []}})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[rate_limited, success])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client),
            patch("deathstar_server.services.linear.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await service._execute("query { teams }")
        assert result == {"teams": []}
        assert mock_client.post.await_count == 2

    @pytest.mark.asyncio
    async def test_ratelimited_graphql_error_exhausts_retries(
        self, service: LinearService,
    ) -> None:
        rate_limited = _mock_response(json_data={
            "errors": [{
                "message": "Rate limit exceeded",
                "extensions": {"code": "RATELIMITED"},
            }],
        })

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=rate_limited)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client),
            patch("deathstar_server.services.linear.asyncio.sleep", new_callable=AsyncMock),
        ):
            with pytest.raises(AppError) as exc_info:
                await service._execute("query { teams }", max_retries=2)
            assert exc_info.value.code == ErrorCode.RATE_LIMITED

    @pytest.mark.asyncio
    async def test_rate_limit_header_warning(
        self, service: LinearService, caplog: pytest.LogCaptureFixture,
    ) -> None:
        resp = _mock_response(
            json_data={"data": {"ok": True}},
            headers={"X-RateLimit-Requests-Remaining": "50"},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            await service._execute("query { ok }")
        assert "rate limit low" in caplog.text.lower()


# ------------------------------------------------------------------
# High-level methods
# ------------------------------------------------------------------


class TestListTeams:
    @pytest.mark.asyncio
    async def test_returns_teams(self, service: LinearService) -> None:
        teams = [{"id": "t1", "name": "Engineering", "key": "ENG"}]
        resp = _mock_response(json_data={"data": {"teams": {"nodes": teams}}})
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            result = await service.list_teams()
        assert result == teams


class TestListProjectIssues:
    @pytest.mark.asyncio
    async def test_returns_issues(self, service: LinearService) -> None:
        issues = [{"id": "i1", "identifier": "ENG-1", "title": "Task"}]
        resp = _mock_response(
            json_data={"data": {"project": {"issues": {
                "nodes": issues,
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }}}},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            result = await service.list_project_issues("proj-1")
        assert result == issues

    @pytest.mark.asyncio
    async def test_paginates_across_multiple_pages(self, service: LinearService) -> None:
        """Verify cursor-based pagination fetches all pages."""
        page1_resp = _mock_response(json_data={"data": {"project": {"issues": {
            "nodes": [{"id": "i1"}],
            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
        }}}})
        page2_resp = _mock_response(json_data={"data": {"project": {"issues": {
            "nodes": [{"id": "i2"}],
            "pageInfo": {"hasNextPage": True, "endCursor": "cursor-2"},
        }}}})
        page3_resp = _mock_response(json_data={"data": {"project": {"issues": {
            "nodes": [{"id": "i3"}],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }}}})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[page1_resp, page2_resp, page3_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            result = await service.list_project_issues("proj-1")

        assert result == [{"id": "i1"}, {"id": "i2"}, {"id": "i3"}]
        assert mock_client.post.await_count == 3

    @pytest.mark.asyncio
    async def test_returns_empty_for_missing_project(self, service: LinearService) -> None:
        resp = _mock_response(json_data={"data": {"project": None}})
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            result = await service.list_project_issues("nonexistent")
        assert result == []


class TestUpdateIssueState:
    @pytest.mark.asyncio
    async def test_returns_result(self, service: LinearService) -> None:
        resp = _mock_response(
            json_data={
                "data": {
                    "issueUpdate": {
                        "success": True,
                        "issue": {"id": "i1", "identifier": "ENG-1", "state": {"id": "s2", "name": "Done", "type": "completed"}},
                    },
                },
            },
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            result = await service.update_issue_state("i1", "s2")
        assert result["success"] is True


class TestListWorkflowStates:
    @pytest.mark.asyncio
    async def test_returns_states(self, service: LinearService) -> None:
        states = [{"id": "s1", "name": "Todo", "type": "unstarted", "position": 0}]
        resp = _mock_response(
            json_data={"data": {"team": {"states": {"nodes": states}}}},
        )
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            result = await service.list_workflow_states("t1")
        assert result == states

    @pytest.mark.asyncio
    async def test_returns_empty_for_missing_team(self, service: LinearService) -> None:
        resp = _mock_response(json_data={"data": {"team": None}})
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("deathstar_server.services.linear.httpx.AsyncClient", return_value=mock_client):
            result = await service.list_workflow_states("nonexistent")
        assert result == []
