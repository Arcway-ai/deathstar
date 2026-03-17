# Architecture

## Goals

DeathStar is built around one idea: the local CLI is the stable operator surface, while the remote EC2 instance is the place where provider execution, secrets, git state, and workspace automation live.

## High-Level Components

### Local CLI

The local `deathstar` CLI is the primary interface for:

- Terraform-driven deploy and destroy
- Tailscale-backed connect
- remote workflow execution
- status, logs, backup, and restore

### Terraform

Terraform provisions:

- a dedicated VPC
- a public subnet with no inbound exposure by default
- an EC2 instance profile with SSM and least-privilege secret access
- an encrypted workspace EBS volume
- an artifact bucket for syncing the runtime bundle
- an optional backup bucket

### Remote Host Bootstrap

cloud-init on the instance:

- installs Docker
- formats and mounts the workspace volume at `/workspace`
- renders runtime environment from Parameter Store
- syncs the runtime bundle from S3
- starts the Docker Compose service

### Remote Control API

The control API:

- is reached through Tailscale by default
- uses SSM only as a fallback path
- normalizes provider calls across OpenAI, Anthropic, and Google
- manages backup and restore
- executes patch, PR, and review workflows against remote git repos

## Data Flow

### Deploy

1. Local CLI loads repo-local config.
2. CLI runs Terraform in `terraform/environments/aws-ec2`.
3. Terraform uploads runtime files from the repo into the artifact bucket.
4. Terraform launches the EC2 instance with cloud-init.
5. The instance syncs the runtime files and starts the control API.

### Run Workflow

1. CLI reads Terraform outputs to find the instance.
2. CLI resolves the DeathStar node on the tailnet and calls the control API directly over Tailscale.
3. CLI sends a normalized workflow request.
4. The server builds provider-specific requests behind a common adapter interface.
5. The server returns a normalized response envelope.

### Patch Workflow

1. The user points `--workspace-subpath` at a repo or subdirectory under `/workspace/projects`.
2. The server builds scoped file context.
3. The chosen provider returns a unified diff.
4. DeathStar optionally applies the diff with `git apply`.

### PR Workflow

1. The server builds a clean diff snapshot.
2. A separate provider call drafts title, body, and summary.
3. If requested, DeathStar creates a branch, commits changes, pushes it, and opens a GitHub PR.

### Review Workflow

1. The server builds a diff snapshot.
2. A separate provider call gets only the review prompt and the diff context.
3. The review result comes back as its own independent response.

That separate-call design is how DeathStar gives the PR writer and reviewer their own fresh context instead of reusing the implementation exchange.

## Runtime Layout

### Host Paths

- `/opt/deathstar`
  Runtime scripts, env files, and synced repo bundle
- `/workspace/projects`
  Persistent git repos and project files
- `/workspace/deathstar/logs`
  Persistent runtime logs
- `/workspace/deathstar/backups`
  Local workspace archives

### Container Service

There is one container in v1:

- `control-api`

It exposes:

- `8080` on the host

The security boundary for that API is:

- zero inbound security-group rules from the internet or VPC
- private tailnet transport for operators
- SSM as an explicit fallback path

## Terraform Module Responsibilities

- `network`
  Dedicated VPC, subnet, IGW, route table
- `security`
  No-ingress SG by default, optional future web UI ingress
- `storage`
  Runtime artifact bucket and optional backup bucket
- `iam`
  EC2 role, instance profile, Parameter Store and S3 permissions
- `instance`
  EC2 instance, encrypted root volume, encrypted workspace EBS volume

## Why This Shape

The architecture favors:

- simple rebuilds
- minimal exposed surface
- clear boundaries between operator UX and provider execution
- future extension into richer agent tooling without breaking the CLI contract
