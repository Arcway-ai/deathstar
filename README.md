# DeathStar

DeathStar is an open-source, Terraform-built remote AI coding workstation for AWS — powered by Claude Code.

The v1 design is intentionally narrow:

- AWS only
- single EC2 instance
- no public SSH by default
- Tailscale-first operator access
- persistent EBS-backed workspace
- Python local CLI as the canonical operator interface
- Claude Code Agent SDK for interactive AI coding sessions

The web UI provides an experience similar to having Claude Code in a terminal — you type prompts, see streaming output with tool use and thinking, and can respond to questions or approve permissions interactively. Different workflow modes (Chat, Code, Review, Docs, Audit, Plan) configure the agent with appropriate tools and permissions.

## What You Get

- A remote Claude Code workstation accessible from any device over Tailscale
- Interactive AI coding sessions via the web UI with real-time streaming
- Tool use visualization (file reads, edits, bash commands, search)
- Permission management — approve or deny tool use from the UI
- Multi-turn conversations with full session continuity
- Branch management, PR creation, and code review workflows
- Structured code reviews with severity-rated findings and one-click apply
- Implementation planning with phased task breakdowns
- Remote terminal access via the browser (zsh + vim)
- Persistent workspace that survives instance restarts
- Zero-downtime blue/green deployments

```bash
deathstar deploy --region us-west-1
deathstar connect
deathstar status
deathstar logs
deathstar backup
deathstar restore
```

Open the web UI at `http://deathstar:8080/` over Tailscale.

## Architecture

```
Browser / Phone  ──▶  Web UI (React + Vite + Tailwind v4)
                         │
                         ▼
                    FastAPI Control API (:8080)
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
         Claude Code   Git Ops   WebSocket
         Agent SDK     Service   Terminal (PTY)
              │
              ▼
         Claude CLI
      (subscription auth)
```

1. The local `deathstar` CLI runs Terraform for deploy and destroy.
2. The CLI discovers the instance through Terraform outputs.
3. For `run`, `status`, `logs`, `backup`, and `restore`, the CLI talks to the remote control API over Tailscale by default.
4. `connect` uses Tailscale SSH by default.
5. AWS SSM remains available as a break-glass fallback.
6. The web UI communicates with the control API over WebSocket for interactive Claude Code sessions and over REST for repo management.
7. Redeploys use a blue/green strategy — the new image builds while the old container stays live, a canary health check runs, then traffic swaps over.

## Security Posture

- No public SSH ingress by default
- Security group starts with zero inbound rules
- IMDSv2 is required
- Root and data volumes are encrypted
- Provider secrets are pulled from SSM Parameter Store at runtime
- Tailscale is the primary private operator network
- The control API is intended to be reached over the tailnet, not the public internet
- The control API supports optional bearer token authentication via `DEATHSTAR_API_TOKEN`
- GitHub PR automation is optional and uses a separate token stored remotely
- Input validation enforces path traversal protection, prompt size limits, and safe workspace subpaths
- Backup restore rejects symlinks, hard links, and paths outside the workspace root
- Agent is blocked from force-pushing or pushing to main/master

The main tradeoff in v1 is outbound internet access: the instance needs egress for package installs, container pulls, provider APIs, GitHub, and AWS APIs. The default security group keeps outbound open to stay reproducible; tighter egress control is documented as a hardening step.

## Quick Start

### 1. Prerequisites

| Tool | Version | How to install | How to verify |
|------|---------|----------------|---------------|
| **Python** | 3.11+ | [python.org](https://www.python.org/downloads/) or `brew install python@3.12` | `python3 --version` |
| **uv** | any | [docs.astral.sh](https://docs.astral.sh/uv/getting-started/installation/) or `brew install uv` | `uv --version` |
| **Docker** | 20+ | [docker.com](https://docs.docker.com/get-docker/) or `brew install --cask docker` | `docker --version` |
| **Terraform** | 1.6+ | [terraform.io](https://developer.hashicorp.com/terraform/install) or `brew install terraform` | `terraform --version` |
| **AWS CLI** | v2 | [AWS docs](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) or `brew install awscli` | `aws --version` |
| **Tailscale** | any | [tailscale.com](https://tailscale.com/download) | `tailscale status` |
| **Session Manager plugin** | any | [AWS docs](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) | `session-manager-plugin` (prints usage) |

**AWS permissions required:** Your AWS credentials must be able to create and manage VPC, EC2, IAM roles/instance profiles, S3 buckets, SSM parameters, and security groups.

**Claude Code subscription:** The web UI uses your Claude Code subscription (Max or Pro plan) for AI features. No API key is required — you'll authenticate through the web UI after deploying.

### 2. Configure AWS Credentials

DeathStar uses whichever AWS credentials the AWS CLI resolves:

```bash
# Show your current identity
aws sts get-caller-identity

# List your configured profiles
aws configure list-profiles
```

If you need to use a specific profile:

```bash
# Export for the current shell session
export AWS_PROFILE=my-work-profile

# Or set it in .env (persists across sessions)
# DEATHSTAR_AWS_PROFILE=my-work-profile
```

### 3. Configure Local Defaults

```bash
cp .env.example .env
```

Open `.env` in your editor:

```bash
# --- Required: adjust these to your environment ---

DEATHSTAR_PROJECT_NAME=deathstar       # Names all AWS resources. Change if running
                                        # multiple instances in one account.
DEATHSTAR_REGION=us-west-1             # AWS region for all resources.
DEATHSTAR_AWS_PROFILE=default          # AWS CLI profile name.

# --- Instance sizing ---

DEATHSTAR_INSTANCE_TYPE=t3.large       # EC2 instance type. t3.large = 2 vCPU, 8GB RAM.
DEATHSTAR_ROOT_VOLUME_SIZE_GB=30       # OS disk. 30GB is usually enough.
DEATHSTAR_DATA_VOLUME_SIZE_GB=200      # Workspace disk mounted at /workspace.

# --- API authentication (strongly recommended) ---

DEATHSTAR_API_TOKEN=                   # Set to a random secret string.
                                        # Generate one with: openssl rand -hex 32

```

The web UI is always enabled and served at port 8080 (only accessible over Tailscale by default).

### 4. Install The CLI

**From PyPI (recommended):**

```bash
uv tool install deathstar-ai
```

**From source (for contributors):**

```bash
git clone https://github.com/Arcway-ai/deathstar.git
cd deathstar
uv tool install -e . --force
```

Verify:

```bash
deathstar version
```

### 5. Set Up Tailscale (Recommended)

DeathStar uses Tailscale as the primary private network between your devices and the EC2 instance.

**On your laptop/phone:**

1. Install Tailscale from [tailscale.com/download](https://tailscale.com/download)
2. Sign in: `tailscale up`
3. Verify: `tailscale status`

**Create a Tailscale auth key** so the EC2 instance can join automatically:

```bash
deathstar tailscale setup --region us-west-1
```

This requires a Tailscale OAuth client. To create one:

1. Go to [Tailscale admin console](https://login.tailscale.com/admin/settings/oauth) (Settings > OAuth clients)
2. Click **"Generate OAuth client..."**
3. Grant scopes: **"Auth Keys: Write"**, **"Devices: Read"**, **"Devices: Write"**
4. Copy the **client ID** and **client secret**
5. Run `deathstar tailscale setup` and paste them when prompted

**Important:** OAuth-created auth keys require at least one ACL tag. Define a tag in your [tailnet ACL policy](https://login.tailscale.com/admin/acls):

```jsonc
"tagOwners": {
  "tag:deathstar": ["autogroup:admin"]
}
```

```bash
# In .env:
DEATHSTAR_TAILSCALE_ADVERTISE_TAGS=tag:deathstar
```

### 6. Deploy

```bash
deathstar deploy --region us-west-1
```

This runs `terraform init` and `terraform apply`. Expect 3-5 minutes for the initial deploy.

**Wait a minute or two** after deploy for cloud-init to finish:

```bash
# Check if the instance appears on your tailnet
tailscale status | grep deathstar

# Verify the API is up
deathstar status
```

### 7. Connect Your Claude Account

Open the web UI at `http://deathstar:8080/` in your browser.

Click the **Claude** indicator in the top bar — it will show a red dot if not yet authenticated. Click **"Connect Claude Account"** to start the OAuth login flow:

1. The server starts `claude auth login` and returns a URL
2. Open the URL in your browser and complete authentication
3. The web UI automatically detects when auth succeeds (polls every 3 seconds)
4. The green dot appears — you're connected

Claude auth persists across container restarts (stored on the workspace volume).

### 8. Set Up GitHub Integration (Optional)

If you want DeathStar to push branches and open PRs:

```bash
deathstar github setup --region us-west-1
```

| Method | Best for | What happens |
|--------|----------|-------------|
| `auto` (default) | Laptop with `gh` CLI | Extracts token from your `gh` session |
| `pat` | Any device with a browser | Creates a PAT via github.com |
| `oauth` | Headless or phone setups | Device Flow with one-time code |

### 9. Clone Repos

SSH into the instance:

```bash
deathstar connect
```

Clone your repos:

```bash
cd /workspace/projects
git clone git@github.com:your-org/your-repo.git
```

Or clone from the web UI — use the repo picker to browse and clone GitHub repos directly.

### 10. Start Using It

Open the web UI at `http://deathstar:8080/`:

1. Select a repo from the picker
2. Choose a persona and workflow mode
3. Type a prompt and press Enter
4. Watch Claude Code work — you'll see tool use, file reads/writes, and thinking in real time
5. Approve or deny permission requests as they come up

## Web UI

The web UI provides an interactive Claude Code experience in your browser — like having a terminal session with Claude Code, but with a rich visual interface.

### Workflow Modes

| Mode | What it does | Agent tools |
|------|-------------|-------------|
| **Chat** | Read-only exploration and Q&A | Read, Glob, Grep, WebSearch, WebFetch |
| **Code** | Direct file modification | Read, Write, Edit, Bash, Glob, Grep |
| **Code + PR** | Same as Code, then creates a PR | Read, Write, Edit, Bash, Glob, Grep |
| **Review** | Structured code review with findings | Read, Glob, Grep, Bash, Agent |
| **Docs** | Documentation generation | Read, Write, Edit, Glob, Grep |
| **Audit** | Security audit (read-only) | Read, Glob, Grep, Bash |
| **Plan** | Implementation planning with phased tasks | Read, Glob, Grep |

### Features

- **Interactive streaming** — see text, thinking, tool use, and tool results stream in real time
- **Permission flow** — Claude requests permission for sensitive operations; approve or deny from the UI
- **Multi-turn conversations** — full session continuity via the Claude Agent SDK
- **Stop button** — interrupt the agent mid-stream
- **Personas** — 8 expert personas (Frontend, Full-stack, Security, DevOps, Data, Architect, Writer, Researcher) with specialized system prompts
- **Model selector** — pick Claude models with speed/price metadata
- **Structured code review** — review mode produces severity-rated findings with inline code suggestions; accept, reject, or apply them as a commit directly to the PR
- **Structured plans** — plan mode produces phased task breakdowns with complexity ratings, effort estimates, risks, and open questions
- **PR selector** — browse open pull requests and select one as context for review mode
- **Branch management** — view, switch, create, delete, and sync branches from the repo panel
- **Quick save** — commit dirty changes with one click or Cmd+S
- **Repo context** — CLAUDE.md, current branch, recent commits, and file tree are automatically injected into prompts
- **Memory bank** — thumbs-up a response to save it as persistent context for future prompts
- **Feedback** — thumbs-up and thumbs-down per message for quality tracking
- **File explorer** — collapsible directory tree with syntax-highlighted file viewer
- **Remote terminal** — WebSocket PTY terminal (xterm.js) with zsh, resize, maximize, and up to 4 sessions
- **Markdown rendering** — full markdown with syntax-highlighted code blocks
- **Conversation persistence** — SQLite-backed conversations, memories, and feedback survive page reloads and device switches
- **Claude auth management** — connect and disconnect your Claude account from the UI
- **Multiple themes** — dark ("Imperial"), light, and system preference
- **Star Wars commit authors** — agent commits are authored by random Star Wars characters with lego-style avatars
- **Protected branch enforcement** — agent cannot push to main/master or force-push

### API Endpoints

All web API endpoints live under `/web/api/` and require the same bearer token as `/v1/*`. Static files bypass auth.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/web/api/repos` | List repos with branch and dirty state |
| GET | `/web/api/repos/{name}/tree` | File list for a repo |
| GET | `/web/api/repos/{name}/file?path=...` | Read a file |
| GET | `/web/api/repos/{name}/context` | Repo context (CLAUDE.md, branch, commits, tree) |
| GET | `/web/api/repos/{name}/branches` | List local branches |
| GET | `/web/api/repos/{name}/commits` | Recent commit history |
| POST | `/web/api/repos/{name}/branch` | Create a branch |
| POST | `/web/api/repos/{name}/checkout` | Switch branch |
| POST | `/web/api/repos/{name}/sync` | Sync branch with base (rebase) |
| POST | `/web/api/repos/{name}/save` | Quick-save uncommitted changes |
| DELETE | `/web/api/repos/{name}/branch` | Delete a branch |
| GET | `/web/api/repos/{name}/pulls` | List pull requests |
| GET | `/web/api/claude/auth/status` | Check Claude CLI auth status |
| POST | `/web/api/claude/auth/login` | Start Claude OAuth login flow |
| POST | `/web/api/claude/auth/logout` | Disconnect Claude account |
| GET | `/web/api/github/repos` | List GitHub repos |
| POST | `/web/api/github/clone` | Clone a GitHub repo |
| POST | `/web/api/chat` | Send a chat message |
| GET | `/web/api/chat/stream` | SSE streaming chat |
| GET | `/web/api/conversations?repo=...` | List conversations |
| GET | `/web/api/conversations/{id}` | Full conversation detail |
| DELETE | `/web/api/conversations/{id}` | Delete a conversation |
| GET | `/web/api/memory?repo=...` | List memory bank entries |
| POST | `/web/api/memory` | Save a memory |
| DELETE | `/web/api/memory/{id}` | Delete a memory |
| POST | `/web/api/feedback` | Save thumbs-up/down feedback |
| POST | `/web/api/reviews/post-to-github` | Post review findings to a GitHub PR |
| POST | `/web/api/reviews/apply-suggestions` | Apply code suggestions as a commit |
| WS | `/web/api/agent` | WebSocket interactive agent session |
| WS | `/web/api/terminal` | WebSocket PTY terminal |

### Phone Usage

- **Laptop or desktop** — CLI for deploy/destroy/backup, web UI for coding
- **Phone or tablet** — web UI over Tailscale for chat, code, and review
- **Emergency access** — Tailscale SSH or SSM for direct shell access

## CLI Usage

The local CLI manages infrastructure and provides a command-line interface to the remote instance.

### Deploy And Destroy

```bash
deathstar deploy --region us-west-1
deathstar destroy --region us-west-1
```

### Redeploy (Code-Only Push)

Build the Docker image locally and push it to the remote instance over Tailscale SSH:

```bash
deathstar redeploy
deathstar redeploy --yes    # auto-approve
```

Steps:
1. Builds the Docker image locally (`docker build --platform linux/amd64`)
2. Pushes the image to the instance via `docker save | gzip | ssh docker load`
3. Restarts the container with a blue/green canary health check

The old container stays live until the new one passes health checks. If unhealthy, the old container stays up and the deploy is rolled back.

Use `redeploy` for frontend changes, API route updates, or any code-only change. Use `deploy` for infrastructure changes.

**Requires:** Docker Desktop running locally and Tailscale SSH ACL configured (see Tailscale setup).

### Upgrade

```bash
deathstar upgrade
```

Automatically detects your install mode:
- **PyPI install:** upgrades from PyPI (`uv tool upgrade deathstar-ai`)
- **Source install:** pulls latest code and reinstalls the editable package

Then backs up, builds the Docker image locally, pushes it to the instance via Tailscale SSH, and restarts with a health check.

```bash
deathstar upgrade --yes           # auto-approve everything
deathstar upgrade --skip-backup   # skip pre-upgrade backup
```

### Run CLI Workflows

```bash
deathstar run --provider anthropic --prompt "summarize this repo"

deathstar run \
  --workflow patch \
  --provider anthropic \
  --workspace-subpath repos/api \
  --write \
  --prompt "fix the failing tests"

deathstar run \
  --workflow review \
  --provider anthropic \
  --workspace-subpath repos/api \
  --base-branch main \
  --prompt "review these changes"
```

### Status, Logs, Backups

```bash
deathstar status
deathstar logs --tail 200
deathstar backup --label before-rebuild
deathstar restore
```

### Connect

```bash
deathstar connect                    # Tailscale SSH (default)
deathstar connect --transport ssm    # SSM break-glass fallback
```

### Seed Or Rotate Secrets

```bash
deathstar secrets bootstrap --region us-west-1
deathstar secrets put --provider anthropic --region us-west-1
deathstar secrets put --integration github --region us-west-1
```

### Tailscale Cleanup

```bash
deathstar tailscale cleanup
```

Deletes offline devices and renames suffixed hostnames (e.g. `deathstar-1` -> `deathstar`).

### Total Teardown (trench-run)

Wipes everything — infrastructure, SSM secrets, Terraform state:

```bash
deathstar trench-run --region us-west-1
```

No `--yes` flag; you must type the project name to confirm.

## Frontend Development

```bash
cd web
npm install
npm run dev     # Starts Vite dev server on :5173, proxies API to :8080
```

The Vite dev server proxies `/web/api/*` (including WebSocket) and `/v1/*` to `localhost:8080`.

## Testing

```bash
uv run pytest tests/ -v
```

The test suite covers the Anthropic provider, workflows, backup/restore, git operations, input validation, API routes, web UI routes, auth middleware, CLI configuration, and the Claude Agent SDK integration.

## Contributing

Contributions are welcome! Here's how to get involved:

1. **Fork** the repo and create a feature branch from `main`
2. **Make your changes** — follow the conventions in [CLAUDE.md](CLAUDE.md)
3. **Run the checks** before submitting:
   ```bash
   uv run ruff check cli server shared tests
   uv run pytest tests/ -v
   cd web && npx tsc --noEmit && npm run build
   ```
4. **Open a pull request** against `main` with a clear description of what and why

### Guidelines

- Keep PRs focused — one feature or fix per PR
- Add tests for new backend functionality
- Don't break existing tests
- Follow the existing code style (ruff for Python, TypeScript strict mode for frontend)
- Update docs if your change affects user-facing behavior

All PRs require review and approval before merging. CI must pass (lint, test, typecheck, frontend build).

## License

[AGPL-3.0](LICENSE)
