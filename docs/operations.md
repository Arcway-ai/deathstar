# Operations

## Prerequisites

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Terraform 1.6+
- AWS CLI v2
- Tailscale on the local operator device
- AWS Session Manager plugin (break-glass fallback)
- AWS permissions for EC2, VPC, IAM, S3, and SSM

## Initial Setup

### 1. Configure Repo Defaults

Copy `.env.example` to `.env` and set:

- AWS profile and region
- Instance sizing
- Parameter Store paths
- Optional backup bucket settings
- `DEATHSTAR_API_TOKEN` for web UI auth

### 2. Install The CLI

```bash
uv tool install -e . --force
```

### 3. Seed Secrets

```bash
deathstar secrets bootstrap --region us-west-1
```

The bootstrap flow hides pasted input, confirms each value, and lets you press Enter to skip items. At minimum you need:

- **Anthropic API key** — required for the Claude Agent SDK (web UI)
- **Tailscale auth key** — required when Tailscale is enabled (recommended default)
- **GitHub token** — optional, needed for PR automation and repo cloning

Targeted updates:

```bash
deathstar secrets put --provider anthropic --region us-west-1
deathstar secrets put --integration tailscale --region us-west-1
deathstar secrets put --integration github --region us-west-1
```

### 4. GitHub Auth (Optional)

For remote GitHub access (repo cloning, PR automation):

```bash
deathstar github setup
```

Supports gh CLI, guided PAT entry, or OAuth Device Flow.

### 5. Tailscale Auth (Optional)

To create a Tailscale auth key via the API:

```bash
deathstar tailscale setup
```

## Deploy

```bash
deathstar deploy --region us-west-1
```

What happens:

- Terraform provisions network, S3, IAM, and EC2 resources
- Runtime files are uploaded into the artifact bucket
- The instance boots, mounts the workspace volume, renders secrets, and starts the API
- Multi-stage Docker build: Node.js builds the React frontend, Python builds the backend

## Access the Web UI

After deployment, access the web UI over Tailscale:

```
http://<tailscale-hostname>:8080
```

The web UI provides:

- Multi-workflow agent chat (Chat, Code, PR, Review, Docs, Audit, Plan)
- Repo selection and branch management
- File viewer with syntax highlighting
- Integrated terminal (WebSocket PTY)
- Model selection with speed/price metadata
- Persona system for different development contexts
- Memory bank for persistent context across conversations

## Redeploy (Code-Only)

Push code changes without replacing the EC2 instance:

```bash
deathstar redeploy
```

This packages the repo to S3, rebuilds Docker, and performs a blue/green container swap for zero-downtime updates.

## Upgrade

Pull latest code, reinstall CLI, backup, and redeploy in one step:

```bash
deathstar upgrade
```

## Connect

```bash
deathstar connect
deathstar connect --transport ssm
```

By default uses Tailscale SSH. Use `--transport ssm` as a fallback.

## Clone Repos

```bash
deathstar repos list
deathstar repos clone owner/repo
```

Repos are cloned to `/workspace/projects` on the remote instance and become available in the web UI repo selector.

## Backups

Create a workspace backup:

```bash
deathstar backup --label before-rebuild
```

Restore the latest backup:

```bash
deathstar restore
```

Restore a specific backup:

```bash
deathstar restore --backup-id 20260311T120000Z-before-rebuild.tar.gz
```

Backups include `/workspace/projects` and the SQLite database. If a backup bucket is configured, the archive is also uploaded to S3.

## Logs

```bash
deathstar logs --tail 200
```

## Destroy

```bash
deathstar destroy --region us-west-1
```

Notes:

- If a backup bucket exists with force destroy disabled, Terraform preserves its contents
- Destroying the stack without off-instance backups removes the instance and workspace volume

## Rebuild Flow

1. `deathstar backup --label pre-rebuild`
2. `deathstar destroy`
3. `deathstar deploy --region us-west-1`
4. `deathstar restore`

## Common Failure Modes

### Tailscale transport fails

Check:

- Your laptop is on the same tailnet
- The instance joined the tailnet during bootstrap
- The configured Tailscale hostname matches

Use `--transport ssm` as a fallback.

### Session Manager plugin missing

Install the AWS Session Manager plugin locally. Only needed for `--transport ssm`.

### Agent SDK errors

The web UI shows errors inline. Check server logs for details:

```bash
deathstar logs --tail 200
```

Common causes: missing Anthropic API key, rate limiting, network issues.

### GitHub PR creation fails

Check:

- The repo remote points to GitHub
- The GitHub token exists remotely
- The remote has push access to origin
