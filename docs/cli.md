# CLI

## Philosophy

The local CLI manages infrastructure and deployment. The web UI is the primary interface for interactive AI workflows.

- CLI handles deploy, destroy, redeploy, upgrade, secrets, and remote administration
- Web UI handles chat, code generation, PR drafting, reviews, and all interactive agent sessions
- CLI retains legacy `run` command for scripted/headless workflows

## Installation

```bash
uv tool install -e . --force
```

## Commands

### `deathstar deploy`

Deploy or update the full AWS stack (Terraform apply).

```bash
deathstar deploy --region us-west-1
```

### `deathstar destroy`

Tear down the AWS stack.

```bash
deathstar destroy --region us-west-1
```

### `deathstar trench-run`

Total teardown: infrastructure, secrets, and Terraform state. Requires typing the project name to confirm.

```bash
deathstar trench-run --region us-west-1
```

### `deathstar redeploy`

Code-only push. Packages the repo to S3 and rebuilds Docker without replacing the EC2 instance. Uses blue/green container swap for zero-downtime updates.

```bash
deathstar redeploy
```

### `deathstar upgrade`

Pull latest code, reinstall CLI, backup, and redeploy in one command.

```bash
deathstar upgrade
```

### `deathstar connect`

Open an interactive shell on the instance.

```bash
deathstar connect
deathstar connect --transport ssm
```

Default transport is Tailscale SSH. Use `--transport ssm` as a break-glass fallback.

### `deathstar secrets`

Manage remote-only secrets in AWS SSM Parameter Store.

```bash
# Bootstrap all secrets (interactive, hidden input)
deathstar secrets bootstrap --region us-west-1

# Update a single secret
deathstar secrets put --provider anthropic --region us-west-1
deathstar secrets put --integration tailscale --region us-west-1
deathstar secrets put --integration github --region us-west-1

# Non-interactive automation
printf %s "$ANTHROPIC_API_KEY" | deathstar secrets put --provider anthropic --region us-west-1 --stdin
```

### `deathstar github setup`

Configure GitHub authentication on the remote instance. Supports gh CLI, PAT, or OAuth Device Flow.

```bash
deathstar github setup
```

### `deathstar tailscale setup`

Create a Tailscale auth key via the API and store it in SSM.

```bash
deathstar tailscale setup
```

### `deathstar repos`

Manage GitHub repos on the remote instance.

```bash
deathstar repos list
deathstar repos clone owner/repo
```

### `deathstar status`

Shows remote runtime health, version (VERSION+git-sha), and configuration.

### `deathstar logs`

Tails the remote control API log file.

```bash
deathstar logs --tail 200
```

### `deathstar backup`

Archives `/workspace/projects` and optionally uploads to S3.

```bash
deathstar backup --label before-rebuild
```

### `deathstar restore`

Restores the latest or specified backup archive.

```bash
deathstar restore
deathstar restore --backup-id 20260311T120000Z-before-rebuild.tar.gz
```

### `deathstar run` (Legacy)

Execute AI workflows from the CLI. Retains multi-provider support for scripted/headless use cases.

```bash
deathstar run --provider anthropic --prompt "Explain the service layout"

deathstar run \
  --workflow patch \
  --provider anthropic \
  --workspace-subpath repos/api \
  --write \
  --prompt "Fix the panic in the request handler"
```

Options: `--provider`, `--workflow`, `--workspace-subpath`, `--prompt`, `--model`, `--transport`, `--output`

## Transport Model

- `deploy` and `destroy` use Terraform and AWS APIs directly
- `run`, `status`, `logs`, `backup`, `restore` use Tailscale by default
- `connect` uses Tailscale SSH by default
- `ssm` is retained for recovery when the tailnet path is unavailable

## JSON Mode

Read-style commands support `--output json` for scripting and CI automation.
