from deathstar_server.config import load_settings
from deathstar_server.logging import configure_logging
from deathstar_server.providers.registry import ProviderRegistry
from deathstar_server.services.backup import BackupService
from deathstar_server.services.github import GitHubService
from deathstar_server.services.gitops import GitService
from deathstar_server.services.workflow import WorkflowService

settings = load_settings()
configure_logging(settings.log_path, settings.log_level)

provider_registry = ProviderRegistry(settings)
git_service = GitService(settings)
github_service = GitHubService(settings)
backup_service = BackupService(settings)
workflow_service = WorkflowService(settings, provider_registry, git_service, github_service)

# Web UI conversation store + memory bank — only initialised when web UI is enabled
conversation_store = None
memory_bank = None
if settings.enable_web_ui:
    from deathstar_server.web.conversations import ConversationStore
    from deathstar_server.web.memory_bank import MemoryBank

    conversation_store = ConversationStore(settings.workspace_root / "deathstar" / "conversations")
    memory_bank = MemoryBank(settings.workspace_root / "deathstar" / "memory_bank")
