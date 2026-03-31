import os

from deathstar_server.config import load_settings
from deathstar_server.logging import configure_logging
from deathstar_server.services import agent as agent_service  # noqa: F401
from deathstar_server.services.backup import BackupService
from deathstar_server.services.github import GitHubService
from deathstar_server.services.gitops import GitService
from deathstar_server.services.worktree import WorktreeManager
from deathstar_server.web.database import Database
from deathstar_server.web.conversations import ConversationStore
from deathstar_server.services.event_bus import EventBus
from deathstar_server.web.feedback import FeedbackStore
from deathstar_server.web.memory_bank import MemoryBank

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

# SQLite database — single file, backed up with the rest of /workspace
db = Database(settings.workspace_root / "deathstar" / "deathstar.db")

conversation_store = ConversationStore(db)
memory_bank = MemoryBank(db)
feedback_store = FeedbackStore(db)
event_bus = EventBus()
