from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deathstar_server.errors import AppError
from deathstar_shared.models import ErrorCode

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

    from sqlmodel import SQLModel
    from deathstar_server.db.engine import create_db_engine
    from deathstar_server.web.conversations import ConversationStore

    test_engine = create_db_engine(f"sqlite:///{tmp_path}/deathstar.db")
    SQLModel.metadata.create_all(test_engine)
    convo_store = ConversationStore(test_engine)

    # Create mock app_state module
    mock_app_state = MagicMock()
    mock_app_state.settings = mock_settings
    mock_app_state.backup_service = mock_backup
    mock_app_state.git_service = mock_git
    mock_app_state.conversation_store = convo_store

    # Event bus — mock with a no-op publish
    mock_event_bus = MagicMock()
    mock_event_bus.publish.return_value = 0
    mock_app_state.event_bus = mock_event_bus

    # Inject mock before importing app/routes
    for mod_name in list(sys.modules):
        if mod_name.startswith("deathstar_server.app") or \
           mod_name.startswith("deathstar_server.routes") or \
           mod_name.startswith("deathstar_server.web"):
            sys.modules.pop(mod_name, None)

    sys.modules["deathstar_server.app_state"] = mock_app_state

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


# ---------------------------------------------------------------------------
# Queue endpoints  (POST /queue, GET /queue, DELETE /queue/{id})
# ---------------------------------------------------------------------------

def _build_web_app_with_queue(tmp_path: Path, api_token: str | None = None):
    """Like _build_web_app but wires a real QueueStore into mock_app_state
    and returns (client, mock_app_state, queue_store) for queue-specific tests."""
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

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
    mock_git.resolve_target.side_effect = lambda subpath: projects_root / subpath

    mock_backup = MagicMock()
    mock_backup.latest_log_lines.return_value = []

    from sqlmodel import SQLModel
    from deathstar_server.db.engine import create_db_engine
    from deathstar_server.web.conversations import ConversationStore
    from deathstar_server.web.queue_store import QueueStore

    test_engine = create_db_engine(f"sqlite:///{tmp_path}/deathstar.db")
    SQLModel.metadata.create_all(test_engine)
    convo_store = ConversationStore(test_engine)
    queue_store = QueueStore(test_engine)

    mock_app_state = MagicMock()
    mock_app_state.settings = mock_settings
    mock_app_state.backup_service = mock_backup
    mock_app_state.git_service = mock_git
    mock_app_state.conversation_store = convo_store
    mock_app_state.queue_store = queue_store
    # queue_worker.interrupt_if_current is a no-op in unit tests
    mock_app_state.queue_worker.interrupt_if_current.return_value = None
    mock_app_state.queue_worker.notify.return_value = None
    mock_event_bus = MagicMock()
    mock_event_bus.publish.return_value = 0
    mock_app_state.event_bus = mock_event_bus
    # Set up a real AgentRunner so list_active() works correctly in tests
    from deathstar_server.services.agent_runner import AgentRunner
    mock_worktree = MagicMock()
    mock_git_service = MagicMock()
    mock_github_service = MagicMock()
    mock_app_state.agent_runner = AgentRunner(
        convo_store, mock_worktree, mock_event_bus,
        mock_settings, mock_git_service, mock_github_service,
    )

    for mod_name in list(sys.modules):
        if mod_name.startswith("deathstar_server.app") or \
           mod_name.startswith("deathstar_server.routes") or \
           mod_name.startswith("deathstar_server.web"):
            sys.modules.pop(mod_name, None)

    sys.modules["deathstar_server.app_state"] = mock_app_state

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

    return TestClient(app), mock_app_state, queue_store


@pytest.fixture
def queue_client(tmp_path):
    client, mock_app_state, queue_store = _build_web_app_with_queue(tmp_path)
    yield client, mock_app_state, queue_store


class TestQueueEndpoints:
    def test_enqueue_creates_item(self, queue_client):
        client, _, store = queue_client
        resp = client.post(
            "/web/api/queue",
            json={
                "repo": "my-project",
                "branch": "main",
                "message": "do work",
                "workflow": "prompt",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["message"] == "do work"
        assert data["repo"] == "my-project"

    def test_enqueue_unknown_repo_returns_404(self, queue_client):
        client, mock_app_state, _ = queue_client
        mock_app_state.git_service.resolve_target.side_effect = AppError(
            ErrorCode.INVALID_REQUEST, "not found", status_code=404
        )
        resp = client.post(
            "/web/api/queue",
            json={"repo": "ghost", "message": "hi", "workflow": "prompt"},
        )
        assert resp.status_code == 404

    def test_list_queue_returns_pending(self, queue_client):
        client, _, store = queue_client
        # Enqueue two items
        store.enqueue(conversation_id="c1", repo="my-project", message="a")
        store.enqueue(conversation_id="c1", repo="my-project", message="b")
        resp = client.get("/web/api/queue")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_queue_filters_by_repo(self, queue_client):
        client, _, store = queue_client
        store.enqueue(conversation_id="c1", repo="my-project", message="a")
        store.enqueue(conversation_id="c2", repo="other-project", message="b")
        resp = client.get("/web/api/queue?repo=my-project")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["repo"] == "my-project"

    def test_cancel_pending_item(self, queue_client):
        client, _, store = queue_client
        item = store.enqueue(
            conversation_id="c1", repo="my-project", message="cancel me"
        )
        resp = client.delete(f"/web/api/queue/{item['id']}")
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is True
        # Item no longer appears in pending list
        assert store.list_pending() == []

    def test_cancel_nonexistent_returns_404(self, queue_client):
        client, _, _ = queue_client
        resp = client.delete("/web/api/queue/nonexistent-id")
        assert resp.status_code == 404

    def test_cancel_processing_item_calls_interrupt(self, queue_client):
        """DELETE on a processing item must call interrupt_if_current."""
        client, mock_app_state, store = queue_client
        store.enqueue(conversation_id="c1", repo="my-project", message="running")
        claimed = store.claim_next()
        assert claimed is not None

        resp = client.delete(f"/web/api/queue/{claimed['id']}")
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is True
        mock_app_state.queue_worker.interrupt_if_current.assert_called_once_with(
            str(claimed["id"])
        )

    def test_cancel_already_completed_returns_404(self, queue_client):
        client, _, store = queue_client
        store.enqueue(conversation_id="c1", repo="my-project", message="done")
        claimed = store.claim_next()
        assert claimed is not None
        store.mark_completed(str(claimed["id"]), "msg-1")

        resp = client.delete(f"/web/api/queue/{claimed['id']}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /agent/sessions
# ---------------------------------------------------------------------------

class TestAgentSessionsEndpoint:
    def test_returns_empty_when_no_sessions(self, queue_client):
        client, _, _ = queue_client
        import deathstar_server.app_state as app_state_mod  # noqa: PLC0415
        original = dict(app_state_mod.agent_runner._agents)
        try:
            app_state_mod.agent_runner._agents.clear()
            resp = client.get("/web/api/agent/sessions")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            app_state_mod.agent_runner._agents.update(original)

    def test_returns_active_sessions(self, queue_client):
        client, _, _ = queue_client
        import deathstar_server.app_state as app_state_mod  # noqa: PLC0415
        from deathstar_server.services.agent_runner import AgentStatus, RunningAgent  # noqa: PLC0415

        fake_agent = MagicMock(spec=RunningAgent)
        fake_agent.conversation_id = "conv-test"
        fake_agent.repo = "my-project"
        fake_agent.branch = "main"
        fake_agent.workflow = "prompt"
        fake_agent.status = AgentStatus.RUNNING
        fake_agent.created_at = time.time()
        fake_agent.last_active = time.time()

        original = dict(app_state_mod.agent_runner._agents)
        try:
            app_state_mod.agent_runner._agents["conv-test"] = fake_agent
            resp = client.get("/web/api/agent/sessions")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["conversation_id"] == "conv-test"
            assert data[0]["repo"] == "my-project"
            assert data[0]["branch"] == "main"
            assert data[0]["status"] == "running"
        finally:
            app_state_mod.agent_runner._agents.clear()
            app_state_mod.agent_runner._agents.update(original)

    def test_excludes_completed_sessions(self, queue_client):
        """Completed agents are not returned by list_active()."""
        client, _, _ = queue_client
        import deathstar_server.app_state as app_state_mod  # noqa: PLC0415
        from deathstar_server.services.agent_runner import AgentStatus, RunningAgent  # noqa: PLC0415

        completed = MagicMock(spec=RunningAgent)
        completed.conversation_id = "conv-done"
        completed.repo = "my-project"
        completed.branch = "main"
        completed.workflow = "prompt"
        completed.status = AgentStatus.COMPLETED
        completed.created_at = time.time()
        completed.last_active = time.time()

        original = dict(app_state_mod.agent_runner._agents)
        try:
            app_state_mod.agent_runner._agents["conv-done"] = completed
            resp = client.get("/web/api/agent/sessions")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            app_state_mod.agent_runner._agents.clear()
            app_state_mod.agent_runner._agents.update(original)
