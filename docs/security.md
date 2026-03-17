# Security

## Secure Defaults

DeathStar v1 is designed to keep the remote box reachable without opening the usual admin surface area.

- No public SSH ingress by default
- The EC2 security group starts with zero inbound rules
- Tailscale is the primary operator network
- The control API is meant to be reached over Tailscale
- AWS SSM is retained as a break-glass path
- IMDSv2 is required on the instance
- Root and workspace EBS volumes are encrypted
- Provider API keys, the Tailscale auth key, and the optional GitHub token are expected in SSM Parameter Store as `SecureString`
- The local CLI can upload secrets with hidden prompts so pasted values do not echo to the terminal
- Provider calls happen on the remote instance, not on the operator laptop

## What Is Exposed

By default:

- No inbound ports are exposed
- No SSH port is opened
- No web UI port is opened
- The control API listens on the host, but the security group still has zero inbound rules
- The instance may still have outbound internet access and, by default, a public IP so it can bootstrap, reach AWS APIs, talk to providers, and reach git remotes

That public-IP-with-no-ingress design is a deliberate v1 tradeoff. It keeps the deployment self-contained and reproducible without forcing NAT gateways or a full set of VPC endpoints.

## Trust Boundaries

### Local Machine

The local machine holds:

- AWS credentials used for Terraform and SSM access
- the local Tailscale identity used for private operator access
- no provider API keys by default
- no GitHub token by default unless the user chooses otherwise

### AWS Control Plane

AWS is trusted for:

- EC2 and EBS hosting
- SSM break-glass administration
- SSM Parameter Store secret storage
- optional S3 backup storage

### Tailscale Control Plane

Tailscale is trusted for:

- device identity
- encrypted operator transport
- private reachability from laptop and phone
- SSH access policy if Tailscale SSH is enabled

In v1, Tailscale identity and tailnet policy are also the primary access-control boundary for the private control API.

### Remote Runtime

The remote runtime holds:

- provider API keys fetched from Parameter Store at startup
- optional GitHub token for remote push and PR creation
- git working copies under `/workspace/projects`
- generated logs under `/workspace/deathstar/logs`

## Secrets Handling

Provider and integration secrets are not committed to the repo and are not stored in Terraform variables as plaintext values.

Recommended paths:

- `/deathstar/providers/openai/api_key`
- `/deathstar/providers/anthropic/api_key`
- `/deathstar/providers/google/api_key`
- `/deathstar/integrations/tailscale/auth_key`
- `/deathstar/integrations/github/token`

The instance role gets read-only access to the configured parameter names. The local CLI only passes parameter names into Terraform.

For secret upload, prefer `deathstar secrets bootstrap` or `deathstar secrets put`. Those commands use hidden terminal input by default and avoid placing the secret in the shell command line.

## Workflow Data Exposure

Prompt, patch, PR, and review workflows are executed on the remote instance.

- `prompt` can be prompt-only, or include scoped workspace context when `--workspace-subpath` is provided
- `patch` reads workspace files under the target path and sends that context to the chosen provider
- `pr` sends the git diff and metadata needed to draft a clean PR summary
- `review` sends the diff to a separate provider call with fresh context

This means code from the targeted remote workspace can be sent to the selected provider. Users should keep workspace scope tight and avoid sending sensitive repositories unless that is explicitly intended.

## GitHub PR Automation

PR creation is optional and separate from AI provider access.

- GitHub is assumed for PR automation in v1
- a GitHub token lives remotely in Parameter Store
- the remote runtime uses that token to push branches and call the GitHub API
- the local CLI never needs the GitHub token for normal operation

## Threat Model

DeathStar v1 primarily defends against:

- opportunistic internet scanning
- accidental secret leakage into local shell history
- unnecessary exposure of SSH
- exposing the control API to the public internet
- mixing local operator credentials with provider credentials
- provider-specific CLI sprawl that encourages users to bypass the remote control plane

It does not fully defend against:

- a compromised AWS account
- malicious code already running inside the instance
- supply-chain compromise in upstream OS packages or container base images
- exfiltration through allowed outbound access
- prompt-induced leakage of workspace contents after a user explicitly targets those files

## Production Hardening Gaps

These are intentional v1 simplifications and should be revisited for production deployments:

- outbound egress is broad rather than tightly allowlisted
- Tailscale tailnet policy is managed outside this repo
- Terraform state defaults to local unless the user configures a remote backend
- the runtime container image is not pinned to an immutable digest
- SSM Parameter Store uses the default AWS-managed key unless the user supplies a stronger KMS strategy
- backups are file-level workspace archives, not full-system disaster recovery
- PR automation assumes GitHub remotes rather than supporting multiple VCS hosts

## Safe Later Extensions

The Terraform security group module already has a narrow optional ingress path for a future web UI:

- disabled by default
- explicit port
- explicit allowed CIDRs

Any future web UI should keep the same stance:

- authenticated
- tightly scoped
- not exposed by accident
