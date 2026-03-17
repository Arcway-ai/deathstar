# CLI

## Philosophy

The local CLI is the canonical interface to DeathStar.

- same command style across providers
- same request envelope across workflows
- remote runtime handles provider-specific differences
- local machine orchestrates infrastructure and uses Tailscale as the default operator transport

## Commands

### `deathstar secrets`

Upload remote-only secrets into AWS SSM Parameter Store.

Examples:

```bash
deathstar secrets bootstrap --region us-west-1
deathstar secrets put --provider openai --region us-west-1
deathstar secrets put --integration tailscale --region us-west-1
printf %s "$OPENAI_API_KEY" | deathstar secrets put --provider openai --region us-west-1 --stdin
```

Default behavior:

- `bootstrap` prompts for OpenAI, Anthropic, Google, and optionally Tailscale or GitHub
- the prompt is hidden, so pasted keys are not echoed to the terminal
- press Enter during `bootstrap` to skip a key you do not want to store yet
- `put` targets one provider, integration, or explicit parameter name at a time
- `--stdin` supports non-interactive automation without putting the value in shell history

### `deathstar deploy`

Deploy or update the AWS stack.

Example:

```bash
deathstar deploy --region us-west-1
```

### `deathstar destroy`

Destroy the AWS stack.

Example:

```bash
deathstar destroy --region us-west-1
```

### `deathstar connect`

Open an interactive shell on the instance.

Example:

```bash
deathstar connect
deathstar connect --transport ssm
```

Default behavior:

- `auto` resolves to Tailscale SSH when the deployment has Tailscale enabled
- `ssm` is the break-glass fallback

### `deathstar run`

The shared workflow command.

Core options:

- `--provider openai|anthropic|google`
- `--workflow prompt|patch|pr|review`
- `--workspace-subpath <path-under-/workspace/projects>`
- `--prompt "..."` 
- `--model <provider-model-override>`
- `--transport auto|tailscale|ssm`
- `--output text|json`

Patch-specific:

- `--write`

PR-specific:

- `--base-branch main`
- `--head-branch deathstar/...`
- `--open-pr`
- `--draft-pr`

Examples:

```bash
deathstar run --provider openai --prompt "Explain the current repo"

deathstar run \
  --workflow patch \
  --provider anthropic \
  --workspace-subpath repos/api \
  --write \
  --prompt "Add missing error handling to the auth path"

deathstar run \
  --workflow pr \
  --provider google \
  --workspace-subpath repos/api \
  --base-branch main \
  --open-pr \
  --prompt "Draft the PR title and body for these changes"

deathstar run \
  --workflow review \
  --provider openai \
  --workspace-subpath repos/api \
  --base-branch main \
  --prompt "Review these changes for regressions and test gaps"
```

### `deathstar status`

Shows remote runtime health and configuration.

### `deathstar logs`

Tails the remote control API log file.

### `deathstar backup`

Archives `/workspace/projects`.

### `deathstar restore`

Restores the latest or specified backup archive.

## Output Contract

`run` uses one response envelope regardless of provider:

- `request_id`
- `workflow`
- `status`
- `provider`
- `model`
- `content`
- `duration_ms`
- `usage`
- `error`
- `artifacts`

`artifacts` changes by workflow:

- `patch`
  includes the diff and, when applied, changed files and git status
- `pr`
  includes title, body, branch, commit SHA, changed files, and optional PR URL
- `review`
  includes branch metadata and changed files

## JSON Mode

Every read-style command supports `--output json`.

That is useful for:

- scripting
- shell pipelines
- CI automation
- post-processing workflow artifacts

## Transport Model

- `deploy` and `destroy`
  use Terraform and AWS APIs directly from the local machine
- `run`, `status`, `logs`, `backup`, `restore`
  use Tailscale by default when enabled on the deployment
- `connect`
  uses Tailscale SSH by default
- `ssm`
  is retained for recovery and debugging when the tailnet path is unavailable
