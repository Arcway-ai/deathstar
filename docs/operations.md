# Operations

## Prerequisites

- Terraform 1.6+
- AWS CLI v2
- Tailscale on the local operator device
- AWS Session Manager plugin for break-glass fallback
- Python 3.11+
- AWS permissions for EC2, VPC, IAM, S3, and SSM

## Initial Setup

### 1. Configure Repo Defaults

Copy `.env.example` to `.env` and set:

- AWS profile and region
- instance sizing
- Parameter Store paths
- optional backup bucket settings

### 2. Install The CLI

```bash
./scripts/install-cli.sh
```

### 3. Seed Secrets

Preferred path: use the local CLI so pasted values are hidden while you enter them.

```bash
deathstar secrets bootstrap --region us-west-1
```

The bootstrap flow hides pasted input, confirms each value, and lets you press Enter to skip items you do not want to store yet.

Targeted updates:

```bash
deathstar secrets put --provider openai --region us-west-1
deathstar secrets put --provider anthropic --region us-west-1
deathstar secrets put --provider google --region us-west-1
deathstar secrets put --integration tailscale --region us-west-1
deathstar secrets put --integration github --region us-west-1
```

Non-interactive automation:

```bash
printf %s "$OPENAI_API_KEY" | deathstar secrets put --provider openai --region us-west-1 --stdin
```

The GitHub token is optional unless you want remote PR automation. The Tailscale auth key is required when Tailscale is enabled, which is the recommended default.

The legacy `scripts/put-provider-secret.sh` helper still exists as a compatibility fallback. If you omit the secret value argument, it also prompts with hidden input.

If your tailnet uses restrictive access controls, make sure its network and SSH policy allows your operator device to reach the DeathStar host and log in as `ec2-user`.

## Deploy

```bash
deathstar deploy --region us-west-1
```

What happens:

- Terraform provisions the network, S3, IAM, and EC2 resources
- runtime files are uploaded into the artifact bucket
- the instance boots, mounts the workspace volume, renders secrets, and starts the API

## Connect

```bash
deathstar connect
deathstar connect --transport ssm
```

Use the remote shell to:

- clone repos into `/workspace/projects`
- inspect logs or container state directly if needed
- perform manual repair work

By default `deathstar connect` uses Tailscale SSH. Use `--transport ssm` only as a fallback.

## Phone Access

The current phone-access path is Tailscale plus SSH, not the full local CLI.

Recommended flow:

1. Install the Tailscale mobile app and join the same tailnet as the DeathStar instance.
2. Open a mobile SSH client that can use the tailnet connection.
3. Connect to `ec2-user@<tailscale-hostname>`.
4. Work inside `/workspace/projects` or inspect the runtime directly.

Useful commands from a phone session:

```bash
cd /workspace/projects
git status
docker ps
docker logs --tail 200 deathstar-control-api
ls /workspace/deathstar/backups
```

Current limitation:

- the project does not yet ship a phone-native client or mobile web workflow UI
- the best mobile experience today is secure shell-based administration over Tailscale

## Run Workflows

### Prompt

```bash
deathstar run --provider openai --prompt "Explain the service layout"
```

### Patch

```bash
deathstar run \
  --workflow patch \
  --provider anthropic \
  --workspace-subpath repos/api \
  --write \
  --prompt "Fix the panic in the request handler"
```

### PR

```bash
deathstar run \
  --workflow pr \
  --provider google \
  --workspace-subpath repos/api \
  --base-branch main \
  --open-pr \
  --prompt "Write a clean PR summary for these changes"
```

### Review

```bash
deathstar run \
  --workflow review \
  --provider openai \
  --workspace-subpath repos/api \
  --base-branch main \
  --prompt "Review these changes for bugs and missing tests"
```

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

By default backups are stored locally on the workspace volume. If a backup bucket is configured, the same archive is uploaded to S3 as well.

## Logs

```bash
deathstar logs --tail 200
```

## Destroy

```bash
deathstar destroy --region us-west-1
```

Notes:

- if you created a backup bucket and did not enable force destroy, Terraform will preserve its contents
- destroying the stack without off-instance backups removes the instance and its workspace volume

## Rebuild Flow

Recommended rebuild sequence:

1. `deathstar backup --label pre-rebuild`
2. `deathstar destroy`
3. `deathstar deploy --region us-west-1`
4. `deathstar restore`

## Common Failure Modes

### Tailscale transport fails

Check:

- your laptop is logged into the same tailnet
- the instance joined the tailnet successfully during bootstrap
- the configured Tailscale hostname matches what you expect

Use `--transport ssm` as a fallback if needed.

### Session Manager plugin missing

The CLI will fail only when you explicitly choose `--transport ssm`. Install the AWS Session Manager plugin locally for break-glass access.

### Provider not configured

The control API returns a normalized `provider_not_configured` error when the expected Parameter Store secret is missing or empty.

### GitHub PR creation fails

Check:

- the repo remote points to GitHub
- the GitHub token exists remotely
- the remote repo can push to origin

### Patch apply fails

The provider returned a diff that `git apply` could not apply cleanly. Retry with a tighter prompt or narrower workspace path.
