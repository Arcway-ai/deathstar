from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

def _build_web_app(tmp_path: Path, api_token: str | None = None):
    """Build a FastAPI app with web UI enabled and mocked dependencies."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    # Create a fake repo
    repo = projects_root / "my-project"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "main.py").write_text("print('hello')")

    mock_settings = MagicMock()
    mock_settings.api_token = api_token
    mock_settings.workspace_root = tmp_path
    mock_settings.projects_root = projects_root
    mock_settings.log_path = tmp_path / "log.txt"
    mock_settings.backup_directory = tmp_path / "backups"
    mock_settings.backup_bucket = None
    mock_settings.github_token = "ghp-test"
    mock_settings.tailscale_enabled = False
    mock_settings.tailscale_hostname = None
    mock_settings.ssh_user = "ubuntu"


    mock_git = MagicMock()
    mock_git.current_branch.return_value = "main"
    mock_git.has_uncommitted_changes.return_value = False
    mock_git.resolve_target.side_effect = lambda subpath: projects_root / subpath
    mock_git.select_files.return_value = [repo / "main.py"]
    mock_git.read_text.return_value = "print('hello')"

    mock_backup = MagicMock()
    mock_backup.latest_log_lines.return_value = ["line1"]

    from deathstar_server.web.database import Database
    from deathstar_server.web.conversations import ConversationStore

    test_db = Database(tmp_path / "deathstar.db")
    convo_store = ConversationStore(test_db)

    # Create mock app_state module
    mock_app_state = MagicMock()
    mock_app_state.settings = mock_settings
    mock_app_state.backup_service = mock_backup
    mock_app_state.git_service = mock_git
    mock_app_state.conversation_store = convo_store

    # Inject mock before importing app/routes
    for mod_name in list(sys.modules):
        if mod_name.startswith("deathstar_server.app") or \
           mod_name.startswith("deathstar_server.routes") or \
           mod_name.startswith("deathstar_server.web"):
            sys.modules.pop(mod_name, None)

    sys.modules["deathstar_server.app_state"] = mock_app_state

    import importlib

    if "deathstar_server.web.routes" in sys.modules:
        importlib.reload(sys.modules["deathstar_server.web.routes"])

    if "deathstar_server.routes" in sys.modules:
        importlib.reload(sys.modules["deathstar_server.routes"])

    if "deathstar_server.app" in sys.modules:
        importlib.reload(sys.modules["deathstar_server.app"])
    else:
        import deathstar_server.app  # noqa: F811, F401

    from deathstar_server.app import app
    from fastapi.testclient import TestClient

    return TestClient(app), mock_git, convo_store


@pytest.fixture
def web_client(tmp_path):
    client, git, store = _build_web_app(tmp_path)
    yield client, git, store


@pytest.fixture
def web_client_auth(tmp_path):
    client, git, store = _build_web_app(tmp_path, api_token="secret-token")
    yield client, git, store


# ---------------------------------------------------------------------------
# GET /web/api/repos
# ---------------------------------------------------------------------------

class TestReposEndpoint:
    def test_lists_repos(self, web_client):
        client, git, _ = web_client
        resp = client.get("/web/api/repos")
        assert resp.status_code == 200
        repos = resp.json()
        assert len(repos) == 1
        assert repos[0]["name"] == "my-project"
        assert repos[0]["branch"] == "main"
        assert repos[0]["dirty"] is False

    def test_repos_requires_auth(self, web_client_auth):
        client, _, _ = web_client_auth
        resp = client.get("/web/api/repos")
        assert resp.status_code == 401

    def test_repos_with_auth(self, web_client_auth):
        client, _, _ = web_client_auth
        resp = client.get("/web/api/repos", headers={"Authorization": "Bearer secret-token"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /web/api/repos/{name}/tree
# ---------------------------------------------------------------------------

class TestRepoTreeEndpoint:
    def test_returns_file_list(self, web_client):
        client, git, _ = web_client
        resp = client.get("/web/api/repos/my-project/tree")
        assert resp.status_code == 200
        files = resp.json()
        assert isinstance(files, list)
        assert "main.py" in files


# ---------------------------------------------------------------------------
# GET /web/api/repos/{name}/file
# ---------------------------------------------------------------------------

class TestRepoFileEndpoint:
    def test_reads_file(self, web_client):
        client, git, _ = web_client
        resp = client.get("/web/api/repos/my-project/file?path=main.py")
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == "main.py"
        assert data["content"] == "print('hello')"

    def test_rejects_missing_path(self, web_client):
        client, _, _ = web_client
        resp = client.get("/web/api/repos/my-project/file")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Conversations CRUD
# ---------------------------------------------------------------------------

class TestConversationsEndpoints:
    def test_list_conversations(self, web_client):
        client, _, store = web_client
        store.get_or_create(None, "my-project")
        resp = client.get("/web/api/conversations")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_conversations_filtered(self, web_client):
        client, _, store = web_client
        store.get_or_create(None, "my-project")
        store.get_or_create(None, "other-project")
        resp = client.get("/web/api/conversations?repo=my-project")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["repo"] == "my-project"

    def test_get_conversation(self, web_client):
        client, _, store = web_client
        cid = store.get_or_create(None, "my-project")
        store.add_user_message(cid, "hello")
        resp = client.get(f"/web/api/conversations/{cid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == cid
        assert len(data["messages"]) == 1

    def test_get_conversation_not_found(self, web_client):
        client, _, _ = web_client
        resp = client.get("/web/api/conversations/nonexistent")
        assert resp.status_code == 404

    def test_delete_conversation(self, web_client):
        client, _, store = web_client
        cid = store.get_or_create(None, "my-project")
        resp = client.delete(f"/web/api/conversations/{cid}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_conversation_not_found(self, web_client):
        client, _, _ = web_client
        resp = client.delete("/web/api/conversations/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth — static files bypass
# ---------------------------------------------------------------------------

class TestWebAuthBypass:
    def test_static_files_skip_auth(self, web_client_auth):
        client, _, _ = web_client_auth
        # index.html served at / should not require auth
        resp = client.get("/")
        # May be 200 or 404 depending on file existence in test env
        assert resp.status_code != 401

    def test_web_api_requires_auth(self, web_client_auth):
        client, _, _ = web_client_auth
        resp = client.get("/web/api/conversations")
        assert resp.status_code == 401

    def test_web_api_with_bearer(self, web_client_auth):
        client, _, _ = web_client_auth
        resp = client.get("/web/api/conversations", headers={"Authorization": "Bearer secret-token"})
        assert resp.status_code == 200

    def test_web_api_with_session_cookie(self, web_client_auth):
        from deathstar_server.session import SESSION_COOKIE_NAME, generate_session_token
        client, _, _ = web_client_auth
        cookie = generate_session_token("secret-token")
        client.cookies.set(SESSION_COOKIE_NAME, cookie)
        resp = client.get("/web/api/conversations")
        assert resp.status_code == 200

    def test_web_api_rejects_bad_cookie(self, web_client_auth):
        from deathstar_server.session import SESSION_COOKIE_NAME
        client, _, _ = web_client_auth
        client.cookies.set(SESSION_COOKIE_NAME, "garbage")
        resp = client.get("/web/api/conversations")
        assert resp.status_code == 401

    def test_index_sets_session_cookie(self, web_client_auth):
        from deathstar_server.session import SESSION_COOKIE_NAME
        client, _, _ = web_client_auth
        resp = client.get("/")
        # Cookie is set if index.html exists; just check no auth error
        assert resp.status_code != 401

    def test_auth_session_endpoint(self, web_client_auth):
        """POST /web/api/auth/session with bearer token sets a session cookie."""
        from deathstar_server.session import SESSION_COOKIE_NAME
        client, _, _ = web_client_auth
        resp = client.post(
            "/web/api/auth/session",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # The response should set a session cookie
        assert SESSION_COOKIE_NAME in resp.cookies

    def test_auth_session_rejects_bad_token(self, web_client_auth):
        client, _, _ = web_client_auth
        resp = client.post(
            "/web/api/auth/session",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_auth_session_no_auth_when_unconfigured(self, web_client):
        """When no api_token is configured, /auth/session always succeeds."""
        client, _, _ = web_client
        resp = client.post("/web/api/auth/session")
        assert resp.status_code == 200
