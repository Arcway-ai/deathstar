# CLAUDE.md

## Project Overview

DeathStar is a Terraform-built remote AI coding workstation on AWS. A local Python CLI (`deathstar`) manages infrastructure and talks to a remote FastAPI control API that runs provider-agnostic AI workflows (OpenAI, Anthropic, Google, Vertex AI).

## Architecture

- `cli/deathstar_cli/` — Local CLI (Typer). Manages Terraform, secrets, and remote API calls.
- `server/deathstar_server/` — Remote FastAPI control API. Runs inside Docker on the EC2 instance.
- `shared/deathstar_shared/` — Pydantic request/response models shared between CLI and server.
- `terraform/` — AWS infrastructure (VPC, EC2, IAM, S3, security groups).
- `bootstrap/` — Cloud-init and host setup scripts (Terraform templates).
- `docker/` — Dockerfile and docker-compose for the control API container.
- `server/deathstar_server/web/` — Web UI API routes, conversation store, memory bank, and WebSocket terminal.
- `web/` — React + Vite frontend (TypeScript, Tailwind v4, Zustand). Built to `web/dist/` and served by FastAPI.
- `tests/` — Pytest test suite.

## Development Commands

```bash
# Install in development mode (editable)
uv tool install -e . --force

# Run tests
uv run pytest tests/ -v

# Lint
ruff check cli server shared tests

# Frontend dev (React + Vite, proxies API to localhost:8080)
cd web && npm install && npm run dev

# Frontend build
cd web && npm run build

# Deploy (full Terraform apply — creates or updates EC2 instance)
deathstar deploy

# Redeploy (code-only push — no instance replacement)
deathstar redeploy

# Upgrade (pull + reinstall CLI + backup + redeploy)
deathstar upgrade
```

## Code Conventions

- Python 3.11+. Use `from __future__ import annotations` in all files.
- Type hints everywhere. Pydantic models for all API contracts.
- Frozen dataclasses for configuration objects (`@dataclass(frozen=True)`).
- Subprocess calls always use list format (never `shell=True`).
- Catch specific exceptions, not bare `except Exception`.
- Provider adapters inherit from `BaseProvider` in `providers/base.py`.
- All provider HTTP errors go through `normalize_http_error` / `normalize_client_error`.
- Errors use `AppError` with `ErrorCode` enum; workflows catch and return error envelopes.
- `workspace_subpath` is always validated against path traversal on both CLI and server side.
- Secrets are never logged or echoed. Use `getpass` for interactive input, SSM SecureString for storage.
- Non-Python static files (HTML, CSS, JS) must be listed in `[tool.setuptools.package-data]` in `pyproject.toml` or they won't be included in the Docker image.

## Bootstrap & Terraform Template Conventions

- **Terraform template escaping**: Bash `${VAR}` must be written as `$${VAR}` in `.tftpl` files to avoid Terraform interpolation. This applies to all bash variable references, array expansions (`$${arr[@]}`), etc.
- **`indent()` first-line behavior**: Terraform's `indent(n, text)` only indents lines *after* the first. In cloud-init YAML `write_files` blocks, the first line gets its indentation from its position in the template, so place `${indent(6, content)}` at the correct column.
- **AL2023 Docker**: Amazon Linux 2023 does not ship `docker-compose-plugin` or a buildx version compatible with modern Compose. The bootstrap installs both from GitHub releases.

## Key Design Decisions

- **Tailscale-first**: All remote operations default to Tailscale. SSM is break-glass only.
- **Claude Agent SDK**: Web UI chat is powered by the Claude Agent SDK (`claude-agent-sdk`). Each workflow mode maps to different tool permissions and `ClaudeAgentOptions`. The SDK manages tool-calling, file access, and session continuity. Config lives in `server/deathstar_server/services/agent.py`.
- **Provider-agnostic (CLI)**: CLI workflows still use the multi-provider layer (OpenAI, Anthropic, Google, Vertex AI). One request/response contract across providers.
- **API auth**: Optional bearer token via `DEATHSTAR_API_TOKEN`. Health endpoint is always public.
- **No public SSH**: Security group has zero inbound rules by default.
- **Single instance**: v1 is intentionally single EC2, single AZ. No HA.
- **Web UI**: Always-on React + Vite frontend. Multi-stage Docker build (Node.js builds frontend, Python builds backend). Static files and `/` bypass auth; `/web/api/*` requires bearer token. WebSocket terminal at `/web/api/terminal`.
- **Personas**: Frontend-defined system prompts (Frontend, Full-stack, Security, DevOps, Data, Architect) sent with each chat request to shape LLM behavior.
- **SQLite persistence**: All conversations, memories, feedback, and usage logs stored in a single SQLite database (`/workspace/deathstar/deathstar.db`) with WAL mode. Backed up with the rest of `/workspace`.
- **Memory Bank**: Thumbs-up responses are saved as persistent context per repo. Injected into future prompts within a token budget (~4K chars).
- **Feedback**: Thumbs-up and thumbs-down tracked per message for analytics. Thumbs-up also saves to memory bank.
- **Repo Context**: CLAUDE.md, branch, recent commits, and file tree are automatically fetched and injected into LLM system prompts when a repo is selected.
- **Version tracking**: `/v1/health` returns `VERSION+git-sha`. `deathstar upgrade` compares local vs remote versions.

## Testing

Tests live in `tests/`. The suite covers:
- Provider adapters (mocked HTTP)
- Workflow service (mocked providers and git)
- Backup/restore (including path traversal and symlink rejection)
- Git operations (real git repos via `tmp_path`)
- Input validation (Pydantic model constraints)
- API routes and auth middleware (FastAPI TestClient)
- Web UI routes, chat, conversations, auth bypass (FastAPI TestClient)
- CLI configuration parsing

Pytest config is in `pyproject.toml` with `pythonpath = ["cli", "server", "shared"]`.

## CLI Command Groups

- `deathstar deploy / destroy` — Terraform infrastructure management.
- `deathstar trench-run` — Total teardown: infra, secrets, state. Requires typing the project name to confirm.
- `deathstar connect` — SSH to the remote instance (Tailscale or SSM).
- `deathstar run` — Execute AI workflows (prompt, patch, PR, review).
- `deathstar status / logs / backup / restore` — Remote operations.
- `deathstar secrets bootstrap / put` — Manage provider API keys in SSM.
- `deathstar github setup` — GitHub auth (gh CLI, PAT, or OAuth Device Flow) for automated PR access.
- `deathstar tailscale setup` — Create a Tailscale auth key via the API and store in SSM.
- `deathstar repos list / clone` — List or clone GitHub repos on the remote instance (proxies to `gh` CLI via SSH/SSM).
- `deathstar redeploy` — Push code changes to S3 and rebuild Docker without replacing the EC2 instance.
- `deathstar upgrade` — Pull latest code, reinstall CLI package, backup, and redeploy in one command.

## Files You Should Know

- `shared/deathstar_shared/models.py` — All Pydantic models. Change here affects both CLI and server.
- `server/deathstar_server/app.py` — FastAPI app with auth middleware and global exception handlers.
- `server/deathstar_server/services/agent.py` — Claude Agent SDK integration. Mode configs, streaming wrapper, SSE translation.
- `server/deathstar_server/services/workflow.py` — Legacy workflow orchestration for CLI (prompt, patch, PR, review).
- `server/deathstar_server/providers/base.py` — Provider base class and error normalization.
- `server/deathstar_server/providers/vertex.py` — Vertex AI provider (supports SA key and WIF auth).
- `cli/deathstar_cli/main.py` — All CLI commands.
- `cli/deathstar_cli/config.py` — CLI config loading from `.env` and environment.
- `cli/deathstar_cli/github_auth.py` — GitHub auth methods (gh CLI, guided PAT, OAuth Device Flow).
- `cli/deathstar_cli/tailscale_auth.py` — Tailscale OAuth client credentials and auth key creation.
- `server/deathstar_server/web/routes.py` — Web UI API endpoints (`/web/api/*`).
- `server/deathstar_server/web/database.py` — SQLite schema, connection management, JSON migration.
- `server/deathstar_server/web/conversations.py` — SQLite-backed conversation store.
- `server/deathstar_server/web/memory_bank.py` — SQLite-backed memory bank (thumbs-up responses per repo).
- `server/deathstar_server/web/feedback.py` — SQLite-backed feedback store (thumbs up/down per message).
- `server/deathstar_server/web/terminal.py` — WebSocket PTY terminal endpoint.
- `shared/deathstar_shared/version.py` — VERSION constant and `full_version()` (VERSION+git-sha).
- `web/src/store.ts` — Zustand store (all frontend state).
- `web/src/personas.ts` — Persona definitions and system prompts.
- `web/src/models.ts` — Curated model catalog with speed/price metadata per provider.
- `web/src/fileTree.ts` — Tree builder (flat paths → nested structure) and language detection.
- `web/src/api.ts` — Frontend API client.
- `web/src/components/Terminal.tsx` — xterm.js WebSocket terminal component.
- `web/src/components/FileViewer.tsx` — Syntax-highlighted file viewer (highlight.js).
- `web/src/components/BranchSelector.tsx` — Branch switching and creation dropdown.
- `web/src/components/ModelSelector.tsx` — Model picker with speed/price badges.
- `docker/control-api.Dockerfile` — Multi-stage build (Node.js frontend + Python backend).
