import os

from sqlmodel import SQLModel

from deathstar_server.config import load_settings
from deathstar_server.db.engine import create_db_engine
from deathstar_server.db.session import init_engine
from deathstar_server.db import models  # noqa: F401 — register all models
from deathstar_server.logging import configure_logging
from deathstar_server.services import agent as agent_service  # noqa: F401
from deathstar_server.services.backup import BackupService
from deathstar_server.services.github import GitHubService
from deathstar_server.services.gitops import GitService
from deathstar_server.services.preview.render import RenderPreviewProvider
from deathstar_server.services.worktree import WorktreeManager
from deathstar_server.web.conversations import ConversationStore
from deathstar_server.services.event_bus import EventBus
from deathstar_server.web.document_store import DocumentStore
from deathstar_server.web.feedback import FeedbackStore
from deathstar_server.web.memory_bank import MemoryBank
from deathstar_server.web.queue_store import QueueStore
from deathstar_server.services.agent_runner import AgentRunner
from deathstar_server.services.queue_worker import QueueWorker

settings = load_settings()
configure_logging(settings.log_path, settings.log_level)

# The Agent SDK uses the Claude CLI authenticated via OAuth (subscription).
# Remove API keys from os.environ so the SDK subprocess doesn't inherit them
# — the SDK transport merges os.environ as a base layer, and a leaked API key
# forces the CLI onto pay-per-token billing.
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("CLAUDE_API_KEY", None)

git_service = GitService(settings)
github_service = GitHubService(settings)
backup_service = BackupService(settings)
worktree_manager = WorktreeManager(settings)
render_preview = RenderPreviewProvider(settings)

# Database — SQLModel engine (PostgreSQL in production, SQLite for dev/tests)
engine = create_db_engine(settings.database_url)
init_engine(engine)

# SQLite (dev/test): create tables directly — no Alembic needed.
# PostgreSQL (production): Alembic migrations own the schema.
# Run `alembic upgrade head` as part of the deploy step.
if settings.database_url.startswith("sqlite"):
    SQLModel.metadata.create_all(engine)

conversation_store = ConversationStore(engine)
memory_bank = MemoryBank(engine)
feedback_store = FeedbackStore(engine)
document_store = DocumentStore(engine)
event_bus = EventBus()
queue_store = QueueStore(engine)
agent_runner = AgentRunner(conversation_store, worktree_manager, event_bus, settings, git_service, github_service)
queue_worker = QueueWorker(queue_store, conversation_store, worktree_manager, event_bus, agent_runner)
# Wake the queue worker immediately when any agent releases a branch lock,
# so queued messages for that branch are picked up without waiting for the
# next poll interval.
agent_runner.set_on_branch_release(queue_worker.notify)
