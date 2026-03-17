from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_server.providers.base import ProviderResult
from deathstar_server.providers.registry import ProviderRegistry
from deathstar_server.services.gitops import DiffSnapshot, GitService
from deathstar_server.services.github import GitHubService
from deathstar_server.services.workflow import (
    WorkflowService,
    _extract_json_object,
    _extract_unified_diff,
    _generate_branch_name,
)
from deathstar_shared.models import (
    ErrorCode,
    ProviderName,
    UsageMetrics,
    WorkflowKind,
    WorkflowRequest,
    WorkflowResponse,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_root=tmp_path,
        projects_root=tmp_path / "projects",
        log_path=tmp_path / "log.txt",
        backup_directory=tmp_path / "backups",
        backup_bucket=None,
        backup_s3_prefix="workspace-backups",
        aws_region="us-west-1",
        log_level="INFO",
        openai_api_key="sk-test",
        anthropic_api_key="ant-test",
        google_api_key="goog-test",
        github_token="ghp-test",
        openai_api_base_url="https://api.openai.com/v1",
        anthropic_api_base_url="https://api.anthropic.com/v1",
        anthropic_api_version="2023-06-01",
        google_api_base_url="https://generativelanguage.googleapis.com/v1beta",
        default_openai_model="gpt-4o-mini",
        default_anthropic_model="claude-sonnet-4-5-20250514",
        default_google_model="gemini-2.0-flash",
        default_vertex_model="gemini-2.0-flash",
        vertex_project_id=None,
        vertex_location="us-central1",
        vertex_service_account_key=None,
        git_author_name="DeathStar",
        git_author_email="deathstar@local",
        tailscale_enabled=False,
        tailscale_hostname=None,
        ssh_user="ec2-user",
        api_token=None,
        enable_web_ui=False,
    )


def _make_provider_result(text: str = "response text", model: str = "gpt-4o-mini") -> ProviderResult:
    return ProviderResult(
        text=text,
        model=model,
        usage=UsageMetrics(input_tokens=10, output_tokens=5, total_tokens=15),
        remote_response_id="resp-1",
    )


@pytest.fixture
def workflow_deps(tmp_path):
    settings = _make_settings(tmp_path)
    providers = MagicMock(spec=ProviderRegistry)
    providers.providers = {
        ProviderName.OPENAI: MagicMock(default_model="gpt-4o-mini"),
        ProviderName.ANTHROPIC: MagicMock(default_model="claude-sonnet-4-5-20250514"),
        ProviderName.GOOGLE: MagicMock(default_model="gemini-2.0-flash"),
    }
    providers.generate_text = AsyncMock(return_value=_make_provider_result())
    git = MagicMock(spec=GitService)
    github = MagicMock(spec=GitHubService)
    service = WorkflowService(settings, providers, git, github)
    return service, providers, git, github


# ---------------------------------------------------------------------------
# Prompt workflow
# ---------------------------------------------------------------------------

class TestPromptWorkflow:
    @pytest.mark.asyncio
    async def test_basic_execution(self, workflow_deps):
        service, providers, git, github = workflow_deps
        request = WorkflowRequest(
            workflow=WorkflowKind.PROMPT,
            provider=ProviderName.OPENAI,
            prompt="Explain Python",
        )

        result = await service.execute(request)

        assert isinstance(result, WorkflowResponse)
        assert result.status == "succeeded"
        assert result.content == "response text"
        assert result.workflow == WorkflowKind.PROMPT
        assert result.provider == ProviderName.OPENAI
        assert result.usage is not None
        providers.generate_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_with_workspace_subpath(self, workflow_deps):
        service, providers, git, github = workflow_deps
        git.build_workspace_context.return_value = "file tree..."

        request = WorkflowRequest(
            workflow=WorkflowKind.PROMPT,
            provider=ProviderName.OPENAI,
            prompt="Explain this code",
            workspace_subpath="myrepo",
        )

        result = await service.execute(request)

        assert result.status == "succeeded"
        git.build_workspace_context.assert_called_once_with("myrepo")
        call_kwargs = providers.generate_text.call_args.kwargs
        assert "file tree..." in call_kwargs["prompt"]


# ---------------------------------------------------------------------------
# Patch workflow
# ---------------------------------------------------------------------------

class TestPatchWorkflow:
    @pytest.mark.asyncio
    async def test_requires_workspace_subpath(self, workflow_deps):
        service, providers, git, github = workflow_deps

        request = WorkflowRequest(
            workflow=WorkflowKind.PATCH,
            provider=ProviderName.OPENAI,
            prompt="Fix the bug",
            workspace_subpath=".",
        )

        result = await service.execute(request)

        assert result.status == "failed"
        assert result.error is not None
        assert result.error.code == ErrorCode.INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_extract_diff_and_return(self, workflow_deps):
        service, providers, git, github = workflow_deps
        diff_text = "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new"
        providers.generate_text = AsyncMock(return_value=_make_provider_result(text=diff_text))
        git.build_workspace_context.return_value = "context"

        request = WorkflowRequest(
            workflow=WorkflowKind.PATCH,
            provider=ProviderName.OPENAI,
            prompt="Fix bug",
            workspace_subpath="myrepo",
            write_changes=False,
        )

        result = await service.execute(request)

        assert result.status == "succeeded"
        assert "diff --git" in result.content

    @pytest.mark.asyncio
    async def test_apply_when_write_changes(self, workflow_deps):
        service, providers, git, github = workflow_deps
        diff_text = "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new"
        providers.generate_text = AsyncMock(return_value=_make_provider_result(text=diff_text))
        git.build_workspace_context.return_value = "context"
        git.apply_patch.return_value = Path("/fake/repo")
        git.changed_files.return_value = ["foo.py"]
        git.status_short.return_value = " M foo.py"

        request = WorkflowRequest(
            workflow=WorkflowKind.PATCH,
            provider=ProviderName.OPENAI,
            prompt="Fix bug",
            workspace_subpath="myrepo",
            write_changes=True,
        )

        result = await service.execute(request)

        assert result.status == "succeeded"
        assert "Patch applied" in result.content
        git.apply_patch.assert_called_once()


# ---------------------------------------------------------------------------
# PR workflow
# ---------------------------------------------------------------------------

class TestPRWorkflow:
    @pytest.mark.asyncio
    async def test_requires_workspace_subpath(self, workflow_deps):
        service, providers, git, github = workflow_deps

        request = WorkflowRequest(
            workflow=WorkflowKind.PR,
            provider=ProviderName.OPENAI,
            prompt="Create PR",
            workspace_subpath=".",
        )

        result = await service.execute(request)

        assert result.status == "failed"
        assert result.error.code == ErrorCode.INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_extracts_json_and_creates_pr(self, workflow_deps):
        service, providers, git, github = workflow_deps

        pr_json = json.dumps({"title": "Fix bug", "body": "This fixes the bug", "summary": "Bug fix"})
        providers.generate_text = AsyncMock(return_value=_make_provider_result(text=pr_json))
        git.collect_diff_snapshot.return_value = DiffSnapshot(
            repo_root=Path("/fake/repo"),
            branch="feature",
            pathspec=".",
            diff_text="some diff",
            changed_files=["foo.py"],
            dirty=True,
        )
        git.commit_all.return_value = "abc123"
        github.push_branch = MagicMock()
        github.create_pull_request = AsyncMock(return_value="https://github.com/org/repo/pull/1")

        request = WorkflowRequest(
            workflow=WorkflowKind.PR,
            provider=ProviderName.OPENAI,
            prompt="Create PR for bug fix",
            workspace_subpath="myrepo",
            open_pr=True,
        )

        result = await service.execute(request)

        assert result.status == "succeeded"
        assert result.content == "Bug fix"
        assert result.artifacts["pull_request_url"] == "https://github.com/org/repo/pull/1"
        assert result.artifacts["title"] == "Fix bug"

    @pytest.mark.asyncio
    async def test_pr_without_open_pr(self, workflow_deps):
        service, providers, git, github = workflow_deps

        pr_json = json.dumps({"title": "Feature X", "body": "Implements X", "summary": "New feature"})
        providers.generate_text = AsyncMock(return_value=_make_provider_result(text=pr_json))
        git.collect_diff_snapshot.return_value = DiffSnapshot(
            repo_root=Path("/fake/repo"),
            branch="feature",
            pathspec=".",
            diff_text="some diff",
            changed_files=["bar.py"],
            dirty=False,
        )

        request = WorkflowRequest(
            workflow=WorkflowKind.PR,
            provider=ProviderName.OPENAI,
            prompt="Summarize changes",
            workspace_subpath="myrepo",
            open_pr=False,
        )

        result = await service.execute(request)

        assert result.status == "succeeded"
        github.push_branch.assert_not_called()
        github.create_pull_request.assert_not_called()


# ---------------------------------------------------------------------------
# Review workflow
# ---------------------------------------------------------------------------

class TestReviewWorkflow:
    @pytest.mark.asyncio
    async def test_collects_diff_and_returns_review(self, workflow_deps):
        service, providers, git, github = workflow_deps
        providers.generate_text = AsyncMock(return_value=_make_provider_result(text="## Findings\nLooks good"))
        git.collect_diff_snapshot.return_value = DiffSnapshot(
            repo_root=Path("/fake/repo"),
            branch="feature",
            pathspec=".",
            diff_text="diff output",
            changed_files=["main.py"],
            dirty=False,
        )

        request = WorkflowRequest(
            workflow=WorkflowKind.REVIEW,
            provider=ProviderName.OPENAI,
            prompt="Review my code",
            workspace_subpath="myrepo",
        )

        result = await service.execute(request)

        assert result.status == "succeeded"
        assert "Findings" in result.content
        assert result.artifacts["branch"] == "feature"

    @pytest.mark.asyncio
    async def test_requires_workspace_subpath(self, workflow_deps):
        service, providers, git, github = workflow_deps

        request = WorkflowRequest(
            workflow=WorkflowKind.REVIEW,
            provider=ProviderName.OPENAI,
            prompt="Review",
            workspace_subpath=".",
        )

        result = await service.execute(request)

        assert result.status == "failed"
        assert result.error.code == ErrorCode.INVALID_REQUEST


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_app_error_caught(self, workflow_deps):
        service, providers, git, github = workflow_deps
        providers.generate_text = AsyncMock(
            side_effect=AppError(ErrorCode.AUTH_ERROR, "bad key", status_code=401)
        )

        request = WorkflowRequest(
            workflow=WorkflowKind.PROMPT,
            provider=ProviderName.OPENAI,
            prompt="hi",
        )

        result = await service.execute(request)

        assert result.status == "failed"
        assert result.error.code == ErrorCode.AUTH_ERROR
        assert "bad key" in result.error.message

    @pytest.mark.asyncio
    async def test_unexpected_exception_caught(self, workflow_deps):
        service, providers, git, github = workflow_deps
        providers.generate_text = AsyncMock(side_effect=RuntimeError("boom"))

        request = WorkflowRequest(
            workflow=WorkflowKind.PROMPT,
            provider=ProviderName.OPENAI,
            prompt="hi",
        )

        result = await service.execute(request)

        assert result.status == "failed"
        assert result.error.code == ErrorCode.INTERNAL_ERROR


# ---------------------------------------------------------------------------
# _extract_unified_diff
# ---------------------------------------------------------------------------

class TestExtractUnifiedDiff:
    def test_valid_diff(self):
        diff = "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new"
        assert _extract_unified_diff(diff).startswith("diff --git")

    def test_fenced_diff(self):
        text = "Here is the diff:\n```diff\ndiff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new\n```"
        result = _extract_unified_diff(text)
        assert result.startswith("diff --git")

    def test_plain_patch_format(self):
        text = "--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new"
        result = _extract_unified_diff(text)
        assert result.startswith("--- a/foo.py")

    def test_diff_with_leading_text(self):
        text = "Some explanation\ndiff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-old\n+new"
        result = _extract_unified_diff(text)
        assert result.startswith("diff --git")

    def test_invalid_text_raises(self):
        with pytest.raises(AppError) as exc_info:
            _extract_unified_diff("This is just plain text")
        assert exc_info.value.code == ErrorCode.INVALID_PROVIDER_OUTPUT

    def test_empty_text_raises(self):
        with pytest.raises(AppError):
            _extract_unified_diff("")


# ---------------------------------------------------------------------------
# _extract_json_object
# ---------------------------------------------------------------------------

class TestExtractJsonObject:
    def test_valid_json(self):
        text = '{"title": "Fix", "body": "Fixed it"}'
        result = _extract_json_object(text)
        assert result["title"] == "Fix"

    def test_json_in_markdown_fences(self):
        text = '```json\n{"title": "Fix", "body": "Done"}\n```'
        result = _extract_json_object(text)
        assert result["title"] == "Fix"

    def test_json_embedded_in_text(self):
        text = 'Here is the result:\n{"title": "X", "body": "Y"}\nDone.'
        result = _extract_json_object(text)
        assert result["title"] == "X"

    def test_invalid_text_raises(self):
        with pytest.raises(AppError) as exc_info:
            _extract_json_object("no json here")
        assert exc_info.value.code == ErrorCode.INVALID_PROVIDER_OUTPUT

    def test_json_array_raises(self):
        with pytest.raises(AppError) as exc_info:
            _extract_json_object("[1, 2, 3]")
        assert exc_info.value.code == ErrorCode.INVALID_PROVIDER_OUTPUT

    def test_nested_json(self):
        text = '{"title": "Fix", "metadata": {"key": "val"}}'
        result = _extract_json_object(text)
        assert result["metadata"]["key"] == "val"

    def test_json_with_escaped_quotes(self):
        text = '{"title": "Fix \\"bug\\"", "body": "Done"}'
        result = _extract_json_object(text)
        assert "bug" in result["title"]


# ---------------------------------------------------------------------------
# _generate_branch_name
# ---------------------------------------------------------------------------

class TestGenerateBranchName:
    def test_basic_generation(self):
        name = _generate_branch_name("Fix the login bug")
        assert name.startswith("deathstar/")
        assert "fix-the-login-bug" in name

    def test_special_characters_stripped(self):
        name = _generate_branch_name("Add feature: new UI!!!")
        assert ":" not in name
        assert "!" not in name

    def test_long_title_truncated(self):
        name = _generate_branch_name("A" * 100)
        # slug is limited to 40 characters
        parts = name.split("/", 1)
        slug_part = parts[1].split("-", 2)[-1]  # skip the timestamp
        assert len(slug_part) <= 40

    def test_empty_title_uses_default(self):
        name = _generate_branch_name("!!!")
        assert "change" in name
