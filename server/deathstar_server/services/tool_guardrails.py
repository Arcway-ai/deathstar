"""Tiered guardrails for agent tool invocations.

Classifies every tool call into one of three tiers:

* **HARD_DENY** — Catastrophic / irreversible operations that are always blocked,
  even if the user explicitly approves.  If someone genuinely needs these, they
  should SSH to the instance directly.
* **REQUIRE_APPROVAL** — Destructive but sometimes-legitimate operations.  In
  interactive mode the user is prompted; in headless / queue-worker mode the
  action is denied with an explanation.
* **AUTO_ACCEPT** — Everything else.  Safe to execute without prompting.

Design notes:
  - All patterns are compiled once at module load time.
  - HARD_DENY rules are checked first so the most critical guards fire first.
  - The module is intentionally stateless — it returns a verdict and the caller
    (``agent_runner.can_use_tool``) decides what to do based on agent context.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class GuardrailTier(str, Enum):
    HARD_DENY = "hard_deny"
    REQUIRE_APPROVAL = "require_approval"
    AUTO_ACCEPT = "auto_accept"


@dataclass(frozen=True)
class GuardrailRule:
    tier: GuardrailTier
    category: str
    pattern: re.Pattern[str]
    reason: str
    tool: str = "Bash"  # "Bash", "Write", or "Edit"


@dataclass(frozen=True)
class GuardrailVerdict:
    tier: GuardrailTier
    rule: GuardrailRule | None  # Matched rule, or None for AUTO_ACCEPT
    command_preview: str  # Truncated input for logging (max 200 chars)


# ---------------------------------------------------------------------------
# Rule definitions — (category, regex_pattern, human-readable reason)
# ---------------------------------------------------------------------------

# ── HARD DENY — always blocked, no override ──────────────────────────────

_HARD_DENY_BASH: list[tuple[str, str, str]] = [
    # Filesystem — catastrophic
    (
        "filesystem",
        r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/\s*$",
        "rm -rf / would destroy the entire filesystem",
    ),
    (
        "filesystem",
        r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+/(?:usr|var|etc|home|opt|boot|root)\b",
        "Recursive deletion of system directories is catastrophic",
    ),
    (
        "filesystem",
        r"\bmkfs\b",
        "Creating a filesystem destroys all data on the target device",
    ),
    (
        "filesystem",
        r"\bdd\b.*\bof=/dev/",
        "Writing raw data to a device can destroy partitions",
    ),
    # System — host-level
    (
        "system",
        r"\b(?:shutdown|reboot|poweroff|halt)\b",
        "Shutting down or rebooting the host is not allowed from an agent",
    ),
    # Infrastructure — full teardown
    (
        "infrastructure",
        r"\bterraform\s+destroy\b",
        "Terraform destroy tears down infrastructure — run from the CLI instead",
    ),
    (
        "infrastructure",
        r"\bpulumi\s+destroy\b",
        "Pulumi destroy tears down infrastructure",
    ),
    # Database — irrecoverable schema destruction
    (
        "database",
        r"\bDROP\s+DATABASE\b",
        "DROP DATABASE is irreversible and destroys all data",
    ),
]


# ── REQUIRE APPROVAL — blocked in headless mode, prompted interactively ──

_REQUIRE_APPROVAL_BASH: list[tuple[str, str, str]] = [
    # Git — destructive history rewriting
    (
        "git",
        r"\bgit\s+reset\s+--hard\b",
        "git reset --hard discards all uncommitted changes",
    ),
    (
        "git",
        r"\bgit\s+clean\s+-[a-zA-Z]*f",
        "git clean -f permanently deletes untracked files",
    ),
    (
        "git",
        r"\bgit\s+checkout\s+--\s+\.",
        "git checkout -- . discards all working-tree changes",
    ),
    (
        "git",
        r"\bgit\s+restore\s+(?:--?\s*)?\.",
        "git restore . discards all working-tree changes",
    ),
    (
        "git",
        r"\bgit\s+branch\s+-D\b",
        "git branch -D force-deletes a branch without merge check",
    ),
    # Filesystem — significant but not catastrophic
    (
        "filesystem",
        r"\brm\s+-[a-zA-Z]*r",
        "Recursive file deletion — verify the target path",
    ),
    (
        "filesystem",
        r"\bshred\b",
        "shred irreversibly overwrites file contents",
    ),
    # Database — data destruction
    (
        "database",
        r"\bDROP\s+TABLE\b",
        "DROP TABLE permanently removes the table and its data",
    ),
    (
        "database",
        r"\bDROP\s+SCHEMA\b",
        "DROP SCHEMA removes an entire schema",
    ),
    (
        "database",
        r"\bTRUNCATE\b",
        "TRUNCATE deletes all rows without per-row logging",
    ),
    (
        "database",
        r"\bDELETE\s+FROM\s+\w+\s*;",
        "DELETE FROM without a WHERE clause removes all rows",
    ),
    (
        "database",
        r"\bDELETE\s+FROM\s+\w+\s*$",
        "DELETE FROM without a WHERE clause removes all rows",
    ),
    # Container / Docker — data loss
    (
        "container",
        r"\bdocker\s+(?:rm|rmi)\b",
        "Removing Docker containers or images",
    ),
    (
        "container",
        r"\bdocker\s+system\s+prune\b",
        "docker system prune removes all unused containers, images, and networks",
    ),
    (
        "container",
        r"\bdocker\s+volume\s+rm\b",
        "Removing a Docker volume permanently deletes its data",
    ),
    (
        "container",
        r"\bdocker[\s-]compose\s+down\s+.*-v\b",
        "docker-compose down -v removes attached volumes",
    ),
    # Infrastructure — auto-approve bypasses human review
    (
        "infrastructure",
        r"\bterraform\s+apply\s+.*-auto-approve\b",
        "Terraform apply with -auto-approve bypasses the plan review step",
    ),
    # Supply chain — arbitrary code execution via package install
    (
        "supply_chain",
        r"\bcurl\b.*\|\s*(?:ba)?sh\b",
        "Piping curl output to a shell executes arbitrary remote code",
    ),
    (
        "supply_chain",
        r"\bwget\b.*\|\s*(?:ba)?sh\b",
        "Piping wget output to a shell executes arbitrary remote code",
    ),
    # Permission / security — privilege escalation
    (
        "permissions",
        r"\bchmod\s+777\b",
        "chmod 777 makes files world-readable/writable/executable",
    ),
    (
        "permissions",
        r"\bchmod\s+-[a-zA-Z]*R.*\s+/",
        "Recursive chmod on system paths can break OS permissions",
    ),
    (
        "permissions",
        r"\bchown\s+-[a-zA-Z]*R",
        "Recursive chown can break file ownership across a tree",
    ),
    # Credential / secret exposure via bash redirection
    (
        "credentials",
        r">\s*~?/\.ssh/",
        "Writing to the SSH directory could overwrite keys",
    ),
    (
        "credentials",
        r">\s*~?/\.aws/",
        "Writing to the AWS credentials directory",
    ),
    (
        "credentials",
        r"\bauthorized_keys\b",
        "Modifying SSH authorized_keys changes who can access this machine",
    ),
    # Process management — could disrupt the agent itself
    (
        "process",
        r"\bkill\s+-9\b",
        "kill -9 forcefully terminates a process with no cleanup",
    ),
    (
        "process",
        r"\bpkill\s+-9\b",
        "pkill -9 forcefully terminates processes by name",
    ),
    (
        "process",
        r"\bsystemctl\s+(?:stop|disable|mask)\b",
        "Stopping or disabling system services could break the environment",
    ),
    # Kubernetes — cluster-level destruction
    (
        "kubernetes",
        r"\bkubectl\s+delete\b",
        "kubectl delete removes resources from the cluster",
    ),
]


# ── REQUIRE APPROVAL for Write/Edit — sensitive file paths ───────────────

_REQUIRE_APPROVAL_FILES: list[tuple[str, str, str]] = [
    (
        "credentials",
        r"\.env(?:\.|$)",
        "Writing to .env files may expose or modify secrets",
    ),
    (
        "credentials",
        r"(?:^|/)\.ssh/",
        "Writing to the .ssh directory could overwrite keys or config",
    ),
    (
        "credentials",
        r"(?:^|/)\.aws/",
        "Writing to the .aws directory could overwrite credentials",
    ),
    (
        "credentials",
        r"authorized_keys$",
        "Modifying authorized_keys changes SSH access",
    ),
    (
        "supply_chain",
        r"\.github/workflows/",
        "Modifying GitHub Actions workflows is a supply-chain risk",
    ),
    (
        "infrastructure",
        r"(?:^|/)\.terraform/",
        "Writing inside .terraform can corrupt Terraform state",
    ),
]


# ---------------------------------------------------------------------------
# Compilation — runs once at import time
# ---------------------------------------------------------------------------


def _compile_rules() -> list[GuardrailRule]:
    rules: list[GuardrailRule] = []

    # HARD_DENY first so they're checked before REQUIRE_APPROVAL
    for category, pattern, reason in _HARD_DENY_BASH:
        rules.append(GuardrailRule(
            tier=GuardrailTier.HARD_DENY,
            category=category,
            pattern=re.compile(pattern, re.IGNORECASE),
            reason=reason,
            tool="Bash",
        ))

    for category, pattern, reason in _REQUIRE_APPROVAL_BASH:
        rules.append(GuardrailRule(
            tier=GuardrailTier.REQUIRE_APPROVAL,
            category=category,
            pattern=re.compile(pattern, re.IGNORECASE),
            reason=reason,
            tool="Bash",
        ))

    for category, pattern, reason in _REQUIRE_APPROVAL_FILES:
        rules.append(GuardrailRule(
            tier=GuardrailTier.REQUIRE_APPROVAL,
            category=category,
            pattern=re.compile(pattern, re.IGNORECASE),
            reason=reason,
            tool="Write",  # Also matched for "Edit"
        ))

    return rules


_COMPILED_RULES: list[GuardrailRule] = _compile_rules()


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _extract_command(tool_input: dict | str) -> str:
    if isinstance(tool_input, dict):
        return str(tool_input.get("command", ""))
    return str(tool_input) if tool_input else ""


def _extract_file_path(tool_input: dict | str) -> str:
    if isinstance(tool_input, dict):
        return str(tool_input.get("file_path", ""))
    return str(tool_input) if tool_input else ""


def classify_tool_use(tool_name: str, tool_input: dict | str) -> GuardrailVerdict:
    """Classify a tool invocation into a guardrail tier.

    Returns a ``GuardrailVerdict``.  If no rule matches, the tier is
    ``AUTO_ACCEPT``.  Rules are checked in compiled order (HARD_DENY
    first, then REQUIRE_APPROVAL), and first match wins.
    """
    if tool_name == "Bash":
        command = _extract_command(tool_input)
        if not command:
            return GuardrailVerdict(GuardrailTier.AUTO_ACCEPT, None, "")
        preview = command[:200]
        for rule in _COMPILED_RULES:
            if rule.tool != "Bash":
                continue
            if rule.pattern.search(command):
                return GuardrailVerdict(rule.tier, rule, preview)
        return GuardrailVerdict(GuardrailTier.AUTO_ACCEPT, None, preview)

    if tool_name in ("Write", "Edit"):
        file_path = _extract_file_path(tool_input)
        if not file_path:
            return GuardrailVerdict(GuardrailTier.AUTO_ACCEPT, None, "")
        preview = file_path[:200]
        for rule in _COMPILED_RULES:
            if rule.tool not in ("Write", "Edit"):
                continue
            if rule.pattern.search(file_path):
                return GuardrailVerdict(rule.tier, rule, preview)
        return GuardrailVerdict(GuardrailTier.AUTO_ACCEPT, None, preview)

    # All other tools (Read, Glob, Grep, etc.) are inherently safe
    return GuardrailVerdict(GuardrailTier.AUTO_ACCEPT, None, "")
