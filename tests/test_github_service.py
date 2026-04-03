"""Tests for GitHubService using githubkit."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from deathstar_shared.models import ErrorCode


@pytest.fixture
def settings():
    s = MagicMock()
    s.github_token = "ghp_test123"
    return s


@pytest.fixture
def service(settings):
    from deathstar_server.services.github import GitHubService
    return GitHubService(settings)


class TestRequireToken:
    def test_returns_token(self, service):
        assert service._require_token() == "ghp_test123"

    def test_raises_when_not_configured(self, settings):
        settings.github_token = None
        from deathstar_server.services.github import GitHubService
        svc = GitHubService(settings)
        from deathstar_server.errors import AppError
        with pytest.raises(AppError) as exc_info:
            svc._require_token()
        assert exc_info.value.code == ErrorCode.INTEGRATION_NOT_CONFIGURED


class TestParseRemote:
    def test_parses_ssh(self, service):
        owner, repo = service._parse_remote("git@github.com:Arcway-ai/deathstar.git")
        assert owner == "Arcway-ai"
        assert repo == "deathstar"

    def test_parses_https(self, service):
        owner, repo = service._parse_remote("https://github.com/Arcway-ai/deathstar.git")
        assert owner == "Arcway-ai"
        assert repo == "deathstar"

    def test_parses_https_no_git_suffix(self, service):
        owner, repo = service._parse_remote("https://github.com/owner/repo")
        assert owner == "owner"
        assert repo == "repo"

    def test_raises_on_unsupported(self, service):
        from deathstar_server.errors import AppError
        with pytest.raises(AppError) as exc_info:
            service._parse_remote("https://gitlab.com/foo/bar.git")
        assert exc_info.value.code == ErrorCode.INVALID_REQUEST


class TestParsePrUrl:
    def test_valid_url(self):
        from deathstar_server.services.github import GitHubService
        owner, repo, number = GitHubService.parse_pr_url("https://github.com/Arcway-ai/deathstar/pull/4")
        assert owner == "Arcway-ai"
        assert repo == "deathstar"
        assert number == 4

    def test_invalid_url(self):
        from deathstar_server.services.github import GitHubService
        from deathstar_server.errors import AppError
        with pytest.raises(AppError):
            GitHubService.parse_pr_url("https://github.com/Arcway-ai/deathstar/issues/4")


class TestClient:
    def test_creates_githubkit_client(self, service):
        gh = service._client()
        from githubkit import GitHub
        assert isinstance(gh, GitHub)


class TestFuzzyReplace:
    """Test the text replacement logic used for applying suggestions."""

    def test_exact_match(self):
        from deathstar_server.services.github import GitHubService
        result = GitHubService._fuzzy_replace("hello world", "hello", "goodbye")
        assert result == "goodbye world"

    def test_no_match_returns_none(self):
        from deathstar_server.services.github import GitHubService
        result = GitHubService._fuzzy_replace("hello world", "missing", "replacement")
        assert result is None

    def test_whitespace_tolerance(self):
        from deathstar_server.services.github import GitHubService
        content = "def foo():\n    pass\n"
        original = "def foo():\n    pass"
        result = GitHubService._fuzzy_replace(content, original, "def bar():\n    pass")
        assert result is not None
        assert "bar" in result


class TestReplaceByLines:
    def test_replace_single_line(self):
        from deathstar_server.services.github import GitHubService
        content = "line1\nline2\nline3\n"
        result = GitHubService._replace_by_lines(content, 2, 2, "replaced")
        assert result is not None
        assert "replaced" in result
        assert "line1" in result
        assert "line3" in result

    def test_out_of_range_returns_none(self):
        from deathstar_server.services.github import GitHubService
        content = "line1\nline2\n"
        assert GitHubService._replace_by_lines(content, 0, 1, "x") is None
        assert GitHubService._replace_by_lines(content, 1, 5, "x") is None


class TestCheckSuggestionSafety:
    def test_safe_when_no_imports_removed(self):
        from deathstar_server.services.github import GitHubService
        original = "import os\nprint(os.path)\n"
        modified = "import os\nimport sys\nprint(os.path)\n"
        assert GitHubService._check_suggestion_safety(original, modified, "test") is None

    def test_blocks_when_used_import_removed(self):
        from deathstar_server.services.github import GitHubService
        original = "import os\nprint(os.path)\n"
        modified = "print(os.path)\n"  # removed 'import os' but still uses os
        reason = GitHubService._check_suggestion_safety(original, modified, "test")
        assert reason is not None
        assert "os" in reason


class TestExtractIdentifiers:
    def test_python_from_import(self):
        from deathstar_server.services.github import GitHubService
        code = "from os.path import join, exists\n"
        ids = GitHubService._extract_identifiers_from_imports(code)
        assert "join" in ids
        assert "exists" in ids

    def test_python_import(self):
        from deathstar_server.services.github import GitHubService
        code = "import os\n"
        ids = GitHubService._extract_identifiers_from_imports(code)
        assert "os" in ids

    def test_js_import(self):
        from deathstar_server.services.github import GitHubService
        code = "import { useState, useEffect } from 'react';\n"
        ids = GitHubService._extract_identifiers_from_imports(code)
        assert "useState" in ids
        assert "useEffect" in ids

    def test_alias(self):
        from deathstar_server.services.github import GitHubService
        code = "from pathlib import Path as P\n"
        ids = GitHubService._extract_identifiers_from_imports(code)
        assert "P" in ids
        assert "Path" not in ids


class TestRaiseForGithubError:
    def test_auth_error(self):
        from deathstar_server.errors import AppError
        from deathstar_server.services.github import _raise_for_github_error
        from githubkit.exception import RequestFailed

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        exc = RequestFailed(mock_resp)
        with pytest.raises(AppError) as exc_info:
            _raise_for_github_error(exc, "test")
        assert exc_info.value.code == ErrorCode.AUTH_ERROR

    def test_other_error(self):
        from deathstar_server.errors import AppError
        from deathstar_server.services.github import _raise_for_github_error
        from githubkit.exception import RequestFailed

        mock_resp = MagicMock()
        mock_resp.status_code = 422
        exc = RequestFailed(mock_resp)
        with pytest.raises(AppError) as exc_info:
            _raise_for_github_error(exc, "test")
        assert exc_info.value.code == ErrorCode.INVALID_REQUEST
