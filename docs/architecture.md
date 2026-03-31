# Architecture

## Goals

DeathStar is a Terraform-built remote AI coding workstation on AWS. The web UI is the primary interface for interactive development, while the local CLI manages infrastructure, secrets, and deployments. The remote EC2 instance runs the Claude Agent SDK, manages git state, and hosts all workspace automation.

## High-Level Components

### Web UI

The React + Vite frontend is the primary development interface:

- Multi-workflow agent sessions (Chat, Code, PR, Review, Docs, Audit, Plan)
- Real-time streaming via WebSocket with tool-use progress
- Repo selection, branch management, and PR integration
- Syntax-highlighted file viewer and inline terminal (xterm.js over WebSocket PTY)
- Persona system (Frontend, Full-stack, Security, DevOps, Data, Architect)
- Structured output panels for reviews and plans
- Memory bank for persistent context across conversations
- Feedback tracking (thumbs up/down) per message

### Local CLI

The `deathstar` CLI handles:

- Terraform-driven deploy and destroy
- Blue/green code-only redeploy (no instance replacement)
- One-command upgrade (pull + reinstall + backup + redeploy)
- Tailscale-backed connect
- Secrets management via SSM Parameter Store
- GitHub and Tailscale auth setup
- Remote repo management
- Backup and restore

### Claude Agent SDK

The web UI chat pipeline is powered by the Claude Agent SDK:

- Each workflow mode maps to different tool permissions and `ClaudeAgentOptions`
- Per-workflow `max_turns` (Chat: 30, Code: unlimited, PR: unlimited, Review: 50, Docs: 50, Audit: 50, Plan: 30)
- Plugin system for mode-specific behavior (security guidance, code review, PR review toolkit)
- Session continuity via `session_id` for multi-turn conversations
- Tool-use streaming translated to SSE events for the frontend

### Terraform

Terraform provisions:

- A dedicated VPC with public subnet
- An EC2 instance profile with SSM and least-privilege secret access
- Encrypted root and workspace EBS volumes
- An artifact bucket for syncing the runtime bundle
- An optional backup bucket

### Remote Host Bootstrap

cloud-init on the instance:

- Installs Docker (including buildx and compose plugin for AL2023)
- Formats and mounts the workspace volume at `/workspace`
- Renders runtime environment from Parameter Store
- Syncs the runtime bundle from S3
- Starts the Docker Compose service

### Remote Control API

The FastAPI control API:

- Serves the built React frontend as static files
- Runs Claude Agent SDK sessions via WebSocket
- Manages conversations, memory bank, and feedback in SQLite
- Provides REST endpoints for repo management, branch operations, and file viewing
- Provides a WebSocket PTY terminal
- Is reached through Tailscale by default (SSM as break-glass fallback)
- Uses optional bearer token auth (`DEATHSTAR_API_TOKEN`)

## Data Flow

### Deploy

1. Local CLI loads repo-local config from `.env`.
2. CLI runs Terraform in `terraform/environments/aws-ec2`.
3. Terraform uploads runtime files into the artifact bucket.
4. Terraform launches the EC2 instance with cloud-init.
5. The instance syncs runtime files and starts the control API.

### Redeploy (Code-Only)

1. CLI packages the current repo into S3.
2. CLI triggers the remote host to pull the new bundle.
3. Docker rebuilds with the new code (multi-stage: Node.js frontend + Python backend).
4. Blue/green container swap for zero-downtime updates.

### Web UI Chat

1. User selects a repo and workflow mode in the frontend.
2. Frontend opens a WebSocket connection to `/web/api/agent`.
3. Repo context (CLAUDE.md, branch, recent commits, file tree) is injected into the system prompt.
4. The server runs a Claude Agent SDK session with mode-appropriate tool permissions.
5. Tool-use events and text deltas stream back to the frontend as SSE-style WebSocket messages.
6. Conversation history is persisted in SQLite for continuity.

### Legacy CLI Workflows

The CLI `deathstar run` command still supports prompt, patch, PR, and review workflows via the multi-provider layer (OpenAI, Anthropic, Google). These are separate from the web UI's Agent SDK pipeline.

## Runtime Layout

### Host Paths

- `/opt/deathstar` — Runtime scripts, env files, and synced repo bundle
- `/workspace/projects` — Persistent git repos and project files
- `/workspace/deathstar/deathstar.db` — SQLite database (conversations, memory, feedback, usage)
- `/workspace/deathstar/logs` — Persistent runtime logs
- `/workspace/deathstar/backups` — Local workspace archives

### Container Service

One container in v1: `control-api`

It exposes port `8080` on the host and serves:

- Static frontend files at `/`
- Web API at `/web/api/*` (bearer token required)
- WebSocket agent at `/web/api/agent`
- WebSocket terminal at `/web/api/terminal`
- Health endpoint at `/v1/health` (public, returns VERSION+git-sha)

### SQLite Persistence

All state lives in a single SQLite database with WAL mode:

- Conversations and messages
- Memory bank entries (per-repo persistent context from thumbs-up responses)
- Feedback records (thumbs up/down per message)
- Usage logs

## Terraform Module Responsibilities

- `network` — Dedicated VPC, subnet, IGW, route table
- `security` — No-ingress SG by default, optional web UI ingress with explicit port and allowed CIDRs
- `storage` — Runtime artifact bucket and optional backup bucket
- `iam` — EC2 role, instance profile, Parameter Store and S3 permissions
- `instance` — EC2 instance, encrypted root volume, encrypted workspace EBS volume
