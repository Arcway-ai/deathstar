# DeathStar

DeathStar is an open-source, Terraform-built remote AI coding workstation for AWS.

The v1 design is intentionally narrow:

- AWS only
- single EC2 instance
- no public SSH by default
- Tailscale-first operator access
- persistent EBS-backed workspace
- Python local CLI as the canonical operator interface
- provider-agnostic workflows across OpenAI, Anthropic, Google, and Vertex AI

The local `deathstar` CLI is the canonical interface to DeathStar. Deploy and destroy use AWS APIs directly, while remote operations talk to the DeathStar instance over a private operator path. Provider API keys live on the remote side in AWS-managed secret storage, and the remote control service normalizes provider differences behind one request and response contract.

## Why Python

Python is used for both the local CLI and the remote control service so the project stays readable to contributors, shares one interface model, and can move quickly without maintaining two languages for one control plane.

## What You Get

- `deathstar deploy --region us-west-1`
- `deathstar secrets bootstrap --region us-west-1`
- `deathstar connect`
- `deathstar run --provider openai --prompt "summarize this repo"`
- `deathstar run --workflow patch --provider anthropic --workspace-subpath repos/api --write --prompt "fix the failing tests"`
- `deathstar run --workflow pr --provider google --workspace-subpath repos/api --base-branch main --open-pr --prompt "create a clean PR summary"`
- `deathstar run --workflow review --provider openai --workspace-subpath repos/api --base-branch main --prompt "review these changes"`
- `deathstar status`
- `deathstar logs`
- `deathstar backup`
- `deathstar restore`

## Architecture

The v1 control path is:

1. The local `deathstar` CLI runs Terraform for deploy and destroy.
2. The CLI discovers the instance through Terraform outputs.
3. For `run`, `status`, `logs`, `backup`, and `restore`, the CLI talks to the remote control API over Tailscale by default.
4. `connect` uses Tailscale SSH by default.
5. AWS SSM remains available as a break-glass fallback.
6. The control API executes provider requests, git workflows, patch application, PR drafting, code review, backups, and restore operations on the remote box.

That keeps the attack surface small while preserving a consistent interface across providers.

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

The main tradeoff in v1 is outbound internet access: the instance needs egress for package installs, container pulls, provider APIs, GitHub, and AWS APIs. The default security group keeps outbound open to stay reproducible; tighter egress control is documented as a hardening step.

## Quick Start

### 1. Prerequisites

Before you begin, make sure you have these tools installed locally:

| Tool | Version | How to install | How to verify |
|------|---------|----------------|---------------|
| **Python** | 3.11+ | [python.org](https://www.python.org/downloads/) or `brew install python@3.12` | `python3 --version` |
| **Terraform** | 1.6+ | [terraform.io](https://developer.hashicorp.com/terraform/install) or `brew install terraform` | `terraform --version` |
| **AWS CLI** | v2 | [AWS docs](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) or `brew install awscli` | `aws --version` |
| **Tailscale** | any | [tailscale.com](https://tailscale.com/download) | `tailscale status` |
| **Session Manager plugin** | any | [AWS docs](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) | `session-manager-plugin` (prints usage) |

**AWS permissions required:** Your AWS credentials must be able to create and manage VPC, EC2, IAM roles/instance profiles, S3 buckets, SSM parameters, and security groups. If you're using an organization account, make sure your role or user has these permissions or ask your admin for an appropriate policy.

### 2. Configure AWS Credentials

DeathStar uses whichever AWS credentials the AWS CLI resolves. If you're not sure which account or profile you're using, check first:

```bash
# Show your current identity (account ID, user/role ARN)
aws sts get-caller-identity

# List your configured profiles
aws configure list-profiles

# See which profile and region are currently active
aws configure list
```

If you need to use a specific profile, either export it or set it in `.env`:

```bash
# Option A: export for the current shell session
export AWS_PROFILE=my-work-profile

# Option B: set it in .env (persists across sessions)
# DEATHSTAR_AWS_PROFILE=my-work-profile
```

If you haven't configured AWS credentials at all yet:

```bash
# Interactive setup — prompts for access key, secret, region, and output format
aws configure

# Or configure a named profile
aws configure --profile my-work-profile
```

The CLI reads `DEATHSTAR_AWS_PROFILE` from `.env` and passes it to Terraform and AWS SDK calls. If left as `default`, it uses whatever `aws configure` set up. If you use SSO:

```bash
aws sso login --profile my-sso-profile
```

### 3. Configure Local Defaults

```bash
cp .env.example .env
```

Open `.env` in your editor. Here's what each setting does and when you need to change it:

```bash
# --- Required: adjust these to your environment ---

DEATHSTAR_PROJECT_NAME=deathstar       # Names all AWS resources. Change if running
                                        # multiple DeathStar instances in one account.
DEATHSTAR_REGION=us-west-1             # AWS region for all resources.
DEATHSTAR_AWS_PROFILE=default          # AWS CLI profile name. Use `aws configure
                                        # list-profiles` to see your options.

# --- Instance sizing ---

DEATHSTAR_INSTANCE_TYPE=t3.large       # EC2 instance type. t3.large = 2 vCPU, 8GB RAM.
                                        # Use t3.xlarge or larger for heavy workloads.
DEATHSTAR_ROOT_VOLUME_SIZE_GB=30       # OS disk. 30GB is usually enough.
DEATHSTAR_DATA_VOLUME_SIZE_GB=200      # Workspace disk mounted at /workspace.
                                        # Size this for your repos + backups.

# --- API authentication (strongly recommended) ---

DEATHSTAR_API_TOKEN=                   # Set this to a random secret string.
                                        # All API endpoints except /v1/health will
                                        # require `Authorization: Bearer <token>`.
                                        # Generate one with: openssl rand -hex 32

# --- Web UI (optional, for phone/browser access) ---

DEATHSTAR_ENABLE_WEB_UI=false          # Set to true to serve the chat UI at port 8080.
                                        # Only accessible over Tailscale by default.
```

The remaining settings in `.env.example` (SSM parameter names, backup bucket, Tailscale tags, transport defaults) can be left at their defaults for most setups. See the comments in `.env.example` for details.

### 4. Install The CLI

The install script uses `pipx` to install the `deathstar` command in an isolated environment. If you don't have `pipx` yet (common on macOS with Homebrew Python):

```bash
brew install pipx
pipx ensurepath
```

Then restart your terminal (or `source ~/.zshrc`) and run:

```bash
./scripts/install-cli.sh
```

Verify it worked:

```bash
deathstar version
```

**Alternative: virtual environment.** If you prefer not to use pipx, you can install into a venv instead:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

With this approach you'll need to activate the venv (`source .venv/bin/activate`) each time you open a new terminal.

**If `deathstar` is not found after install**, make sure `~/.local/bin` is on your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Add that line to your `~/.zshrc` (or `~/.bashrc`) to make it permanent.

### 5. Set Up Tailscale (Recommended)

DeathStar uses Tailscale as the primary private network between your devices and the EC2 instance. Set this up **before deploying** so the instance can join your tailnet on first boot.

**On your laptop/phone:**

1. Install Tailscale from [tailscale.com/download](https://tailscale.com/download)
2. Sign in to your tailnet: `tailscale up` (or use the app)
3. Verify you're connected: `tailscale status`

**Create a Tailscale auth key** so the EC2 instance can join automatically:

Option A — Use the `deathstar tailscale setup` command (creates a key via the API):

```bash
deathstar tailscale setup --region us-west-1
```

This requires a Tailscale OAuth client. To create one:

1. Go to [Tailscale admin console](https://login.tailscale.com/admin/settings/oauth) (Settings > OAuth clients)
2. Click **"Generate OAuth client..."**
3. Grant at least the **"Auth Keys: Write"** scope
4. Copy the **client ID** and **client secret**
5. Run `deathstar tailscale setup` and paste them when prompted

**Important:** OAuth-created auth keys require at least one ACL tag. Before running setup, define a tag in your [tailnet ACL policy](https://login.tailscale.com/admin/acls) and set it in `.env`:

```jsonc
// In your tailnet ACL policy, add to tagOwners:
"tagOwners": {
  "tag:deathstar": ["autogroup:admin"]
}
```

```bash
# In your .env:
DEATHSTAR_TAILSCALE_ADVERTISE_TAGS=tag:deathstar
```

You can also pass the client ID directly and save it in `.env` for reuse:

```bash
# Save in .env so you don't need to pass it each time
# DEATHSTAR_TAILSCALE_OAUTH_CLIENT_ID=tskey-client-abc123

deathstar tailscale setup --client-id tskey-client-abc123 --region us-west-1
```

The auth key defaults to reusable, ephemeral, and preauthorized. Override with flags:

```bash
deathstar tailscale setup --no-reusable --no-ephemeral
```

Option B — Create a key manually in the Tailscale admin console and paste it during `secrets bootstrap` (step 6).

If your tailnet uses restrictive ACLs, make sure the rules allow your operator device to reach the DeathStar host on port 8080 (API) and SSH as `ec2-user`.

### 6. Seed Provider API Keys

Before deploying, store your AI provider API keys in AWS SSM Parameter Store. The EC2 instance pulls these at runtime — they never touch `.env` or your local disk.

```bash
deathstar secrets bootstrap --region us-west-1
```

This prompts for each secret with hidden input (pasted values are not echoed). Press Enter to skip any provider you don't use yet:

```
OpenAI API key: ••••••••
Anthropic API key: ••••••••
Google API key: [Enter to skip]
Tailscale auth key: ••••••••
```

**Where to find your API keys:**

| Provider | Where to get it |
|----------|----------------|
| OpenAI | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) |
| Anthropic | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) |
| Google | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| Vertex AI | See [Vertex AI Setup](#vertex-ai-setup-optional) below — uses GCP credentials, not a simple API key |

You need at least one provider configured. You can add or rotate keys later without redeploying:

```bash
# Update a single provider
deathstar secrets put --provider openai --region us-west-1

# Pipe a key for automation (no interactive prompt)
printf %s "$ANTHROPIC_API_KEY" | deathstar secrets put --provider anthropic --region us-west-1 --stdin

# Overwrite without confirmation
deathstar secrets put --provider google --region us-west-1 --yes
```

To verify a secret was stored:

```bash
aws ssm get-parameter \
  --name /deathstar/providers/openai/api_key \
  --with-decryption \
  --query 'Parameter.Version' \
  --output text \
  --region us-west-1
```

### 7. Deploy

```bash
deathstar deploy --region us-west-1
```

This runs `terraform init` and `terraform apply` behind the scenes. It will show you a plan and ask for confirmation. Expect it to take 3-5 minutes for the initial deploy.

When it completes, you'll see a summary:

```
instance_id: i-0abc123def456
region: us-west-1
remote_api_port: 8080
tailscale_enabled: True
tailscale_hostname: deathstar
```

To skip the confirmation prompt (useful for CI):

```bash
deathstar deploy --region us-west-1 --yes
```

**Wait a minute or two** after deploy for cloud-init to finish setting up Docker, Tailscale, and the control API on the instance. You can check progress:

```bash
# Check if the instance appears on your tailnet
tailscale status | grep deathstar

# Once it appears, verify the API is up
deathstar status
```

### 8. Set Up GitHub Integration (Optional)

If you want DeathStar to push branches and open PRs on your behalf, set up GitHub access. **You only need to run this once** — the token is stored in AWS SSM and the remote instance uses it for all devices (laptop, phone, web UI).

```bash
deathstar github setup --region us-west-1
```

There are four auth methods. Pick the one that fits your situation:

| Method | Best for | What happens |
|--------|----------|-------------|
| `auto` (default) | **Laptop with `gh` CLI** | Extracts the token from your existing `gh` session. If `gh` isn't installed or isn't logged in, falls back to guided PAT creation. This is the easiest path if you have `gh`. |
| `gh` | Laptop with `gh` CLI | Same as auto but skips the fallback — uses `gh` only. Runs `gh auth login` if you're not already logged in. |
| `pat` | **Any device with a browser** | Opens `github.com/settings/tokens` in your browser. You create a fine-grained or classic PAT, copy it, and paste it back into the terminal. Works from a phone over SSH too. |
| `oauth` | **Headless or phone-only setups** | Uses GitHub's [Device Flow](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow). Shows a one-time code, you visit `github.com/login/device` on any device (including your phone) and enter the code. Requires a GitHub OAuth App with Device Flow enabled. |

```bash
# Most common: let it auto-detect (laptop with gh CLI)
deathstar github setup

# Explicit gh CLI
deathstar github setup --method gh

# Manual PAT creation in browser
deathstar github setup --method pat

# OAuth Device Flow (enter the code on any device, even your phone)
deathstar github setup --method oauth --client-id <YOUR_CLIENT_ID>
```

**For the OAuth method**, you need a GitHub OAuth App:

1. Go to [github.com/settings/applications/new](https://github.com/settings/applications/new)
2. **Application name:** anything (e.g. "DeathStar")
3. **Homepage URL:** `https://github.com` (or your repo URL — doesn't matter)
4. **Authorization callback URL:** `http://localhost` — the Device Flow uses polling, not redirects, so this URL is never actually called. GitHub just requires the field to be filled in.
5. Check **"Enable Device Flow"**
6. Click **Register application**, then copy the **Client ID**
7. Set it in `.env` as `DEATHSTAR_GITHUB_APP_CLIENT_ID` so you don't have to pass `--client-id` each time

**Recommended approach:** If you have `gh` CLI on your laptop, just run `deathstar github setup` — it will extract your token in seconds. The phone doesn't need its own setup because the token lives in SSM on the remote side, and both the CLI and web UI use it from there.

**Required token scopes for PRs:** `repo` (full control of private repositories). If your org uses SSO, remember to authorize the token for your org after creation.

### 9. Connect And Prepare Repos

SSH into the instance to clone your repos:

```bash
deathstar connect
```

This uses Tailscale SSH by default. You'll land in a shell on the EC2 instance as `ec2-user`. Clone your repos into the workspace:

```bash
cd /workspace/projects
git clone git@github.com:your-org/your-repo.git
git clone git@github.com:your-org/another-repo.git
```

For HTTPS cloning (if you haven't set up SSH keys on the instance):

```bash
git clone https://github.com/your-org/your-repo.git
```

**Break-glass access** if Tailscale is down:

```bash
deathstar connect --transport ssm
```

### 10. Verify Everything Works

```bash
# Check the remote control API status and configured providers
deathstar status

# Run a simple prompt to verify end-to-end
deathstar run --provider anthropic --prompt "Say hello"

# Run against a specific repo
deathstar run \
  --provider anthropic \
  --workspace-subpath your-repo \
  --prompt "Summarize this project"
```

If you enabled the web UI (`DEATHSTAR_ENABLE_WEB_UI=true`), open your browser to:

```
http://deathstar:8080/
```

(Replace `deathstar` with your Tailscale hostname if you changed `DEATHSTAR_PROJECT_NAME`.)

## CLI Usage

The local CLI is the main way to operate DeathStar. It keeps the same command shape across all supported providers and always routes work through the remote AWS instance.

By default:

- `deploy` and `destroy` use AWS APIs directly
- `run`, `status`, `logs`, `backup`, and `restore` use Tailscale
- `connect` uses Tailscale SSH
- `--transport ssm` is the explicit fallback

### Deploy And Destroy

```bash
deathstar deploy --region us-west-1
deathstar destroy --region us-west-1
```

### Upgrade

`deathstar upgrade` handles the full upgrade lifecycle in one command:

```bash
deathstar upgrade
```

What it does:

1. **Checks** for uncommitted local changes (warns if dirty)
2. **Pulls** latest code with `git pull --ff-only`
3. **Reinstalls** the local CLI package (auto-detects `uv` or falls back to `pip`)
4. **Compares** local version vs remote instance version
5. **Backs up** the remote workspace (unless `--skip-backup`)
6. **Redeploys** via `terraform init` + `terraform apply`

```bash
# Auto-approve everything (no prompts)
deathstar upgrade --yes

# Skip the pre-upgrade backup
deathstar upgrade --skip-backup

# Force SSM transport for version check and backup
deathstar upgrade --transport ssm
```

Version tracking uses `VERSION+git-sha` (e.g., `0.2.0+abc1234`). The `/v1/health` endpoint returns this, and the upgrade command compares it to detect when local and remote are out of sync. If they already match, it asks before redeploying.

### Total Teardown (trench-run)

When you want to wipe everything — infrastructure, SSM secrets, Terraform state, and local state files — use the trench run. There is no `--yes` flag; you must type the project name to confirm.

```bash
deathstar trench-run --region us-west-1
```

This runs four phases:
1. `terraform destroy` (EC2, VPC, security groups, IAM, S3 buckets)
2. Deletes all SSM Parameter Store secrets (provider keys, Tailscale, GitHub)
3. Removes `terraform.tfstate` and backup state files
4. Removes the `.terraform/` directory and lock file

### Seed Or Rotate Secrets

```bash
deathstar secrets bootstrap --region us-west-1
deathstar secrets put --provider openai --region us-west-1
deathstar secrets put --integration github --region us-west-1
printf %s "$OPENAI_API_KEY" | deathstar secrets put --provider openai --region us-west-1 --stdin

# For JSON credential files (e.g., Vertex AI WIF config or SA key):
deathstar secrets put --provider vertex --region us-west-1 --file ~/Downloads/credential-config.json
```

The default input path is a hidden prompt, so pasted keys are not echoed in the terminal. `--stdin` is the non-interactive option for automation. `--file` reads the secret from a file path — use this for multi-line values like JSON credential configs.

### Connect To The Remote Box

```bash
deathstar connect
deathstar connect --transport ssm
```

`deathstar connect` uses Tailscale SSH by default. `--transport ssm` is the break-glass fallback if the tailnet path is unavailable.

### Run A Simple Prompt

```bash
deathstar run --provider openai --prompt "summarize this repo"
deathstar run --provider anthropic --prompt "explain the service layout"
deathstar run --provider google --prompt "list the main security controls"
deathstar run --provider openai --prompt "check the service" --transport ssm
```

### Write Code Into A Specific Remote Directory

```bash
deathstar run \
  --workflow patch \
  --provider anthropic \
  --workspace-subpath repos/api \
  --write \
  --prompt "fix the failing tests in the auth module"
```

`--workspace-subpath` is resolved under `/workspace/projects` on the remote instance. That is the safety boundary for repo-local editing.

### Draft A PR Summary And Optionally Open A PR

```bash
deathstar run \
  --workflow pr \
  --provider google \
  --workspace-subpath repos/api \
  --base-branch main \
  --open-pr \
  --prompt "write a clean PR title and body for these changes"
```

This workflow builds its context from the git diff on the remote box, then returns a normalized response with:

- `title`
- `body`
- `summary`
- branch metadata
- optional PR URL

### Run A Separate Review Agent

```bash
deathstar run \
  --workflow review \
  --provider openai \
  --workspace-subpath repos/api \
  --base-branch main \
  --prompt "review these changes for bugs, regressions, and missing tests"
```

The review workflow is a separate provider call with fresh context derived from the diff. It does not reuse the implementation prompt or patch-generation exchange.

### Check Status, Logs, Backups, And Restore

```bash
deathstar status
deathstar logs --tail 200
deathstar backup --label before-rebuild
deathstar restore
```

### JSON Output For Automation

```bash
deathstar status --output json
deathstar run --provider openai --prompt "summarize this repo" --output json
```

## Web UI (Phone & Browser Access)

DeathStar includes an optional React-based web UI served from the same FastAPI control API on port 8080. It provides a conversational chat interface with personas, repo context awareness, and a memory bank — accessible from any device over Tailscale.

The frontend is built with React 19, TypeScript, Vite 6, Tailwind v4, and Zustand. It's compiled during the Docker multi-stage build (Node.js stage), so there's no separate build step for operators.

### Enabling the Web UI

Set `DEATHSTAR_ENABLE_WEB_UI=true` in your environment or `.env` file. When disabled (the default), the web routes and static files are not registered.

### Accessing the Web UI

1. Install the Tailscale app on your device and sign into the same tailnet.
2. Open `http://<deathstar-hostname>:8080/` in your browser.

The web UI uses the same bearer token authentication as the REST API. Enter your `DEATHSTAR_API_TOKEN` in the Settings panel on first use — it is saved in the browser's local storage.

### Features

- **Repo picker** — select from local repos or browse and clone from GitHub
- **Personas** — 6 expert personas (Frontend, Full-stack, Security, DevOps, Data, Architect) with specialized system prompts that shape LLM behavior for each workflow
- **Repo context** — CLAUDE.md, current branch, recent commits, and file tree are automatically injected into LLM prompts when a repo is selected
- **Memory bank** — thumbs-up a response to save it as persistent context. Approved memories are automatically injected into future prompts (capped at ~4K chars to manage token budget)
- **Branch guard** — warns when running Patch or PR workflows on `main`/`master` and prompts to confirm
- **Conversational chat** — multi-turn conversations with AI, scoped to a repo
- **Workflow modes** — Chat, Patch, Review, and PR via pill buttons
- **File browser** — browse the repo file tree and view files with line numbers
- **Markdown rendering** — full markdown with syntax-highlighted code blocks and copy buttons
- **Conversation persistence** — conversations are stored server-side and survive page reloads and device switches
- **Provider selection** — choose between configured providers or let the server pick the first available
- **Dark theme** — "Imperial Command Center" aesthetic, mobile-first with touch-friendly controls

### API Endpoints

All web API endpoints live under `/web/api/` and require the same bearer token as `/v1/*`. Static files (`/`, `/assets/*`) are served without auth.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/web/api/repos` | List repos with branch and dirty state |
| GET | `/web/api/repos/{name}/tree` | File list for a repo |
| GET | `/web/api/repos/{name}/file?path=...` | Read a file |
| GET | `/web/api/repos/{name}/context` | Repo context (CLAUDE.md, branch, commits, tree) |
| POST | `/web/api/repos/{name}/branch` | Create a branch (rejects `main`/`master`) |
| GET | `/web/api/github/repos` | List GitHub repos for the authenticated user |
| POST | `/web/api/github/clone` | Clone a GitHub repo to the instance |
| POST | `/web/api/chat` | Send a message (wraps workflow execution) |
| GET | `/web/api/conversations?repo=...` | List conversations |
| GET | `/web/api/conversations/{id}` | Full conversation detail |
| DELETE | `/web/api/conversations/{id}` | Delete a conversation |
| GET | `/web/api/providers` | Available providers and status |
| GET | `/web/api/memory?repo=...` | List memory bank entries |
| POST | `/web/api/memory` | Save a memory (thumbs-up) |
| DELETE | `/web/api/memory/{id}` | Delete a memory |

### Frontend Development

To work on the frontend locally:

```bash
cd web
npm install
npm run dev     # Starts Vite dev server on :5173, proxies API to :8080
```

The Vite dev server proxies `/web/api/*` and `/v1/*` to `localhost:8080`, so you need the FastAPI backend running locally or port-forwarded.

### Phone Usage

Use cases by device:

- **Laptop or desktop** — use the `deathstar` CLI for deploy, run, PR, review, backup, and restore
- **Phone or tablet** — use the web UI over Tailscale for chat, patch, and review workflows
- **Emergency access** — use Tailscale SSH or SSM for direct shell access

## Supported Providers

- **OpenAI** — API key auth via `OPENAI_API_KEY`
- **Anthropic** — API key auth via `ANTHROPIC_API_KEY`
- **Google** (AI Studio) — API key auth via `GOOGLE_API_KEY`
- **Vertex AI** (Google Cloud) — GCP credential auth (service account key or Workload Identity Federation)

Google and Vertex AI both use Gemini models. The difference is how they authenticate and bill:

| | Google (AI Studio) | Vertex AI |
|---|---|---|
| Auth | API key | GCP OAuth2 (SA key or WIF) |
| Billing | Google AI Studio account | GCP project billing |
| Use when | Quick setup, personal use | GCP credits, org accounts |
| Provider flag | `--provider google` | `--provider vertex` |

## Vertex AI Setup (Optional)

Vertex AI lets you use Gemini models billed through your GCP project. This is useful if you have GCP credits (e.g., a cloud program grant) or your organization manages billing through GCP.

### Prerequisites

1. A GCP project with the **Vertex AI API** enabled
2. Your GCP project ID (find it at [console.cloud.google.com](https://console.cloud.google.com) in the project picker)

Set the project ID in `.env`:

```bash
DEATHSTAR_VERTEX_PROJECT_ID=your-project-id
DEATHSTAR_VERTEX_LOCATION=us-central1
```

### Authentication

Choose one of two auth methods:

#### Option A: Workload Identity Federation (Recommended)

WIF lets the EC2 instance authenticate to GCP using its AWS IAM role — no static keys. This is the recommended approach, and is required if your GCP organization blocks service account key creation (`iam.disableServiceAccountKeyCreation`).

**GCP side:**

1. Go to [IAM & Admin > Workload Identity Federation](https://console.cloud.google.com/iam-admin/workload-identity-pools)
2. Click **"Create Pool"**
   - Name: `deathstar-aws` (or any name)
   - Click **Continue**
3. **Add a provider:**
   - Provider type: **AWS**
   - Provider name: `aws-provider`
   - AWS Account ID: your 12-digit AWS account ID (find it with `aws sts get-caller-identity --query Account --output text`)
   - Click **Continue**
4. **Configure provider attributes** — leave the defaults (maps `attribute.aws_role` from the AWS STS token)
5. **Grant access to a service account:**
   - Click **"Grant Access"** on the pool
   - Select or create a service account with the **"Vertex AI User"** role
   - For the principal, use the following format (replacing all four placeholders):

   ```
   principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_ID/attribute.aws_role/arn:aws:sts::AWS_ACCOUNT_ID:assumed-role/ROLE_NAME
   ```

   | Placeholder | Where to find it | Example |
   |---|---|---|
   | `PROJECT_NUMBER` | GCP Console project picker (the **number**, not the ID string), or `gcloud projects describe your-project-id --format='value(projectNumber)'` | `123456789012` |
   | `POOL_ID` | The name you chose in step 2 | `deathstar-aws` |
   | `AWS_ACCOUNT_ID` | `aws sts get-caller-identity --query Account --output text` | `111122223333` |
   | `ROLE_NAME` | Your DeathStar EC2 instance role: `${DEATHSTAR_PROJECT_NAME}-instance-role` | `deathstar-instance-role` |

   For example, with defaults:
   ```
   principalSet://iam.googleapis.com/projects/123456789012/locations/global/workloadIdentityPools/deathstar-aws/attribute.aws_role/arn:aws:sts::111122223333:assumed-role/deathstar-instance-role
   ```

   - Click **Save**
6. **Download the credential configuration:**
   - In the pool, go to **"Connected Service Accounts"**
   - Click **"Download Config"**, choose **AWS** format
   - This downloads a JSON file with `"type": "external_account"` — it contains no secrets, just the WIF pool configuration

**AWS side:**

The EC2 instance role already has the permissions it needs. WIF works by having the EC2 instance call AWS STS (which it can do inherently as an EC2 instance with an IAM role), then exchanging that STS token with Google's STS endpoint. No additional IAM policies are required on the AWS side.

**Store the credential config:**

```bash
deathstar secrets put --provider vertex --region us-west-1 --file ~/Downloads/client-config.json
```

The bootstrap script writes this to `/opt/deathstar/gcp-credentials.json` on the EC2 instance and sets `GOOGLE_APPLICATION_CREDENTIALS` so the google-auth library picks it up automatically.

#### Option B: Service Account Key

If your GCP organization allows service account key creation:

1. Go to [IAM & Admin > Service Accounts](https://console.cloud.google.com/iam-admin/serviceaccounts)
2. Create a service account with the **"Vertex AI User"** role
3. Click the service account > **Keys** > **Add Key** > **Create new key** > **JSON**
4. Store the downloaded JSON key:

```bash
deathstar secrets put --provider vertex --region us-west-1 --file ~/Downloads/service-account-key.json
```

### Verify

After deploying (or redeploying), verify Vertex AI is configured:

```bash
deathstar status
# Look for: vertex: configured=True

deathstar run --provider vertex --prompt "Say hello"
```

## Docs

- [`docs/architecture.md`](docs/architecture.md)
- [`docs/security.md`](docs/security.md)
- [`docs/operations.md`](docs/operations.md)
- [`docs/cli.md`](docs/cli.md)
- [`docs/provider-interface.md`](docs/provider-interface.md)

## Testing

```bash
uv run pytest tests/ -v
```

The test suite covers providers, workflows, backup and restore, git operations, input validation, API routes, web UI routes, authentication middleware, and CLI configuration.

## Open Decisions For Later

- richer repo-context selection and tool-execution agents
- safer outbound egress control with VPC endpoints or a proxy
- remote state and locking for Terraform
- multi-repo orchestration beyond one workspace path per workflow
