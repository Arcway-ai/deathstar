# Security

## Secure Defaults

DeathStar keeps the remote instance reachable without opening the usual admin surface area.

- No public SSH ingress by default
- The EC2 security group starts with zero inbound rules
- Tailscale is the primary operator network — all traffic stays on the tailnet
- AWS SSM is retained as a break-glass path
- IMDSv2 is required on the instance
- Root and workspace EBS volumes are encrypted
- Secrets live in SSM Parameter Store as `SecureString`
- The CLI uploads secrets with hidden prompts so pasted values never echo to the terminal
- All AI provider calls happen on the remote instance, not on the operator laptop

## What Is Exposed

By default:

- No inbound ports are open from the internet
- No SSH port is exposed
- The control API (port 8080) listens on the host but the security group has zero inbound rules — only Tailscale traffic reaches it
- The instance has outbound internet access and a public IP for bootstrapping, AWS APIs, provider calls, and git remotes

The public-IP-with-no-ingress design is a deliberate tradeoff. It keeps the deployment self-contained without forcing NAT gateways or VPC endpoints.

## Web UI Auth

The web UI is served by the control API on port 8080:

- **Static files** (`/`, `/index.html`, CSS, JS) bypass auth — the shell is publicly loadable over Tailscale but non-functional without a valid token
- **API routes** (`/web/api/*`) require a bearer token (`DEATHSTAR_API_TOKEN`)
- **WebSocket endpoints** (`/web/api/agent`, `/web/api/terminal`) require the same bearer token on connection
- **Health endpoint** (`/v1/health`) is always public (returns VERSION+git-sha)
- Auth is enforced by FastAPI middleware — no route can accidentally skip it

The bearer token is set via environment variable and stored in SSM Parameter Store. Without it, all API calls return 401.

## WebSocket Security

Two WebSocket endpoints exist:

- **Agent WebSocket** (`/web/api/agent`) — runs Claude Agent SDK sessions. The agent can read/write files, run bash commands, and access git within the workspace. Tool permissions are scoped per workflow mode.
- **Terminal WebSocket** (`/web/api/terminal`) — provides a full PTY shell on the remote instance. This is equivalent to SSH access.

Both require bearer token auth on the initial connection handshake.

## Trust Boundaries

### Local Machine

- AWS credentials for Terraform and SSM access
- Tailscale identity for private operator access
- No provider API keys by default
- No GitHub token unless the user chooses otherwise

### AWS Control Plane

- EC2 and EBS hosting
- SSM break-glass administration
- SSM Parameter Store secret storage
- Optional S3 backup storage

### Tailscale Control Plane

- Device identity and encrypted transport
- Private reachability from laptop and phone
- SSH access policy (if Tailscale SSH is enabled)
- Primary access-control boundary for the control API

### Remote Runtime

- Anthropic API key fetched from Parameter Store at startup
- Optional GitHub token for push and PR creation
- Git working copies under `/workspace/projects`
- SQLite database at `/workspace/deathstar/deathstar.db` (conversations, memory, feedback)
- Runtime logs under `/workspace/deathstar/logs`

## Secrets Handling

Secrets are never committed to the repo or stored in Terraform variables as plaintext.

SSM Parameter Store paths:

- `/deathstar/providers/anthropic/api_key` — required for Claude Agent SDK
- `/deathstar/integrations/tailscale/auth_key` — required when Tailscale is enabled
- `/deathstar/integrations/github/token` — optional, for PR automation
- `/deathstar/api_token` — bearer token for web UI auth

The instance role gets read-only access to configured parameter names. The CLI only passes parameter names into Terraform.

For secret upload, use `deathstar secrets bootstrap` or `deathstar secrets put`. Both use hidden terminal input and avoid placing secrets in shell command lines.

## Agent Data Exposure

The Claude Agent SDK runs on the remote instance with access to workspace files:

- **Chat mode**: Read-only access to files via Glob, Grep, Read tools
- **Code/PR modes**: Full read/write access including Bash execution
- **Review/Audit modes**: Read access plus Bash for analysis
- **All modes**: Repo context (CLAUDE.md, file tree, recent commits, branch) is injected into the system prompt

Code from the workspace is sent to the Anthropic API as part of agent sessions. Users should be aware that any file the agent reads is transmitted to the provider.

The memory bank persists useful responses per repo. These are re-injected into future prompts within a token budget.

## GitHub PR Automation

- GitHub is assumed for PR automation
- The GitHub token lives remotely in Parameter Store
- The runtime uses it to push branches and call the GitHub API
- The CLI never needs the GitHub token for normal operation
- GitHub auth can be configured via `deathstar github setup` (gh CLI, PAT, or OAuth Device Flow)

## Threat Model

DeathStar primarily defends against:

- Opportunistic internet scanning (no inbound rules)
- Accidental secret leakage into shell history (hidden prompts)
- Unnecessary exposure of SSH (Tailscale-only by default)
- Exposing the control API to the public internet (security group + Tailscale)
- Unauthorized web UI access (bearer token auth)

It does not fully defend against:

- A compromised AWS account
- Malicious code already running inside the instance
- Supply-chain compromise in upstream packages or container base images
- Exfiltration through allowed outbound access
- Prompt-induced leakage of workspace contents (the agent can read any workspace file)
- A compromised Tailscale tailnet (would expose the control API)

## Production Hardening Gaps

Intentional simplifications to revisit for multi-user or production deployments:

- Outbound egress is broad rather than tightly allowlisted
- Tailscale tailnet policy is managed outside this repo
- Terraform state defaults to local unless the user configures a remote backend
- The runtime container image is not pinned to an immutable digest
- SSM Parameter Store uses the default AWS-managed key (bring your own KMS for stricter setups)
- Backups are file-level workspace archives, not full disaster recovery
- Single bearer token for all users (no per-user auth or RBAC)
- WebSocket terminal provides full shell access — equivalent to SSH
- SQLite database is not encrypted at the application layer (relies on EBS encryption)
