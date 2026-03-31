from __future__ import annotations

import hashlib
import hmac


def _sign(payload: bytes, secret: str) -> str:
    """Generate a GitHub-style HMAC-SHA256 signature."""
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _push_payload(repo_name: str = "my-repo") -> dict:
    return {
        "ref": "refs/heads/main",
        "repository": {"name": repo_name},
        "sender": {"login": "octocat"},
        "commits": [
            {
                "id": "abc1234567890",
                "message": "Update README",
                "author": {"name": "Octocat"},
            }
        ],
    }


def _pr_payload(repo_name: str = "my-repo") -> dict:
    return {
        "action": "opened",
        "repository": {"name": repo_name},
        "sender": {"login": "octocat"},
        "pull_request": {
            "number": 42,
            "title": "Add feature",
            "state": "open",
            "head": {"ref": "feature-branch"},
        },
    }


class TestWebhookSignatureVerification:
    """Test HMAC-SHA256 signature verification."""

    def _verify(self, payload, sig, secret):
        # Import the function directly — it has no app_state dependency
        # at function level (only the endpoint does).
        from deathstar_server.web.webhooks import _verify_signature
        return _verify_signature(payload, sig, secret)

    def test_valid_signature(self):
        secret = "test-webhook-secret-1234"
        payload = b'{"test": true}'
        sig = _sign(payload, secret)
        assert self._verify(payload, sig, secret) is True

    def test_invalid_signature(self):
        secret = "test-webhook-secret-1234"
        payload = b'{"test": true}'
        assert self._verify(payload, "sha256=invalid", secret) is False

    def test_wrong_prefix(self):
        secret = "test-webhook-secret-1234"
        payload = b'{"test": true}'
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert self._verify(payload, f"sha1={sig}", secret) is False


class TestWebhookEventTranslation:
    """Test GitHub event → RepoEvent translation."""

    def _translate(self, gh_event, repo_name, payload):
        from deathstar_server.web.webhooks import _translate_webhook
        return _translate_webhook(gh_event, repo_name, payload)

    def test_push_event(self):
        payload = _push_payload("my-repo")
        event = self._translate("push", "my-repo", payload)

        assert event is not None
        assert event.event_type == "push"
        assert event.repo == "my-repo"
        assert event.source == "github"
        assert event.data["ref"] == "refs/heads/main"
        assert event.data["sender"] == "octocat"
        assert len(event.data["commits"]) == 1
        assert event.data["commits"][0]["sha"] == "abc1234"

    def test_pull_request_event(self):
        payload = _pr_payload("my-repo")
        event = self._translate("pull_request", "my-repo", payload)

        assert event is not None
        assert event.event_type == "pr_update"
        assert event.data["action"] == "opened"
        assert event.data["number"] == 42
        assert event.data["title"] == "Add feature"

    def test_status_event(self):
        payload = {
            "sha": "abc1234567890",
            "state": "success",
            "context": "ci/test",
            "target_url": "https://ci.example.com/123",
            "repository": {"name": "my-repo"},
            "sender": {"login": "github-actions"},
        }
        event = self._translate("status", "my-repo", payload)

        assert event is not None
        assert event.event_type == "ci_status"
        assert event.data["state"] == "success"

    def test_unknown_event_ignored(self):
        event = self._translate("fork", "my-repo", {"sender": {"login": "x"}})
        assert event is None
