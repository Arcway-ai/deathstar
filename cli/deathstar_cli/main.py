from __future__ import annotations

import re
import subprocess
import time
from typing import Literal

import boto3
import httpx
import typer

from deathstar_cli.config import CLIConfig
from deathstar_cli.output import (
    emit_backup,
    emit_logs,
    emit_restore,
    emit_status,
    validate_output_format,
)
from deathstar_cli.remote import RemoteAPIClient
from deathstar_cli.secrets import (
    IntegrationName,
    bootstrap_targets,
    prompt_for_secret,
    prompt_and_store_secret,
    put_secret_value,
    resolve_secret_target,
)
from deathstar_cli.ssm import run_via_ssm, start_shell_session
from deathstar_cli.tailscale import clear_known_host, connect_via_tailscale, push_image_via_tailscale, run_via_tailscale
from deathstar_cli.terraform import (
    terraform_apply,
    terraform_destroy,
    terraform_init,
    terraform_outputs,
)
from deathstar_shared.models import (
    BackupRequest,
    ProviderName,
    RestoreRequest,
)
from deathstar_shared.version import VERSION, full_version

app = typer.Typer(no_args_is_help=True, help="DeathStar local operator CLI.")
secrets_app = typer.Typer(help="Manage remote-only secrets in AWS SSM Parameter Store.")
github_app = typer.Typer(help="GitHub integration setup and management.")
tailscale_app = typer.Typer(help="Tailscale integration setup and management.")
repos_app = typer.Typer(help="Manage repositories on the remote instance.")
app.add_typer(secrets_app, name="secrets")
app.add_typer(github_app, name="github")
app.add_typer(tailscale_app, name="tailscale")
app.add_typer(repos_app, name="repos")

_SAFE_REPO_RE = re.compile(r"^[a-zA-Z0-9._:/@-]+$")


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse a version string like '0.8.3' into a comparable tuple."""
    return tuple(int(x) for x in re.split(r"[^0-9]+", v.strip()) if x)


def _check_for_update() -> None:
    """Check PyPI for a newer version, warn if outdated. Caches for 24h."""
    import json
    from pathlib import Path

    cache_dir = Path.home() / ".cache" / "deathstar"
    cache_file = cache_dir / "version-check.json"
    ttl = 86400  # 24 hours

    # Check cache first
    try:
        if cache_file.exists():
            data = json.loads(cache_file.read_text())
            if time.time() - data.get("checked_at", 0) < ttl:
                latest = data.get("latest", "")
                if latest and _parse_version(latest) > _parse_version(VERSION):
                    typer.echo(
                        f"\n  Update available: {VERSION} → {latest}"
                        f"\n  Run: uv tool upgrade deathstar-ai\n",
                        err=True,
                    )
                return
    except Exception:
        pass  # Corrupted cache, re-check

    # Query PyPI (short timeout, best-effort)
    try:
        resp = httpx.get(
            "https://pypi.org/pypi/deathstar-ai/json",
            timeout=3.0,
        )
        resp.raise_for_status()
        latest = resp.json()["info"]["version"]
    except Exception:
        return  # Network error, skip silently

    # Cache the result
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"latest": latest, "checked_at": time.time()}))
    except Exception:
        pass

    if _parse_version(latest) > _parse_version(VERSION):
        typer.echo(
            f"\n  Update available: {VERSION} → {latest}"
            f"\n  Run: uv tool upgrade deathstar-ai\n",
            err=True,
        )


@app.callback(invoke_without_command=True)
def _main(ctx: typer.Context) -> None:
    """DeathStar local operator CLI."""
    if ctx.invoked_subcommand is None:
        raise typer.Exit()
    _check_for_update()


def _config() -> CLIConfig:
    return CLIConfig.load()


def _display_terraform_summary(region: str) -> None:
    config = _config()
    outputs = terraform_outputs(config, region)
    typer.echo(f"instance_id: {outputs.get('instance_id')}")
    typer.echo(f"region: {outputs.get('region')}")
    typer.echo(f"remote_api_port: {outputs.get('remote_api_port')}")
    typer.echo(f"tailscale_enabled: {outputs.get('tailscale_enabled')}")
    if outputs.get("tailscale_hostname"):
        typer.echo(f"tailscale_hostname: {outputs.get('tailscale_hostname')}")


def _validate_transport(transport: str) -> str:
    normalized = transport.strip().lower()
    if normalized not in {"auto", "tailscale", "ssm"}:
        raise typer.BadParameter("transport must be auto, tailscale, or ssm")
    return normalized


_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_HYPERSPACE_PHASES = [
    "Entering hyperspace",
    "Navigating asteroid field",
    "Powering up the reactor core",
    "Aligning deflector shields",
    "Calibrating targeting systems",
    "Loading proton torpedoes",
    "Establishing uplink to command",
    "Syncing star charts",
    "Initializing droid protocols",
    "Charging the superlaser",
    "Routing through the Kessel Run",
    "Decrypting Imperial codes",
    "Warming up the hyperdrive",
    "Scanning for rebel frequencies",
    "Priming shield generators",
    "Locking S-foils in attack position",
]

_HYPERSPACE_READY = [
    "The Death Star is fully operational.",
    "All systems nominal. The galaxy awaits.",
    "That's no moon... it's a space station. And it's ready.",
    "The Force is strong with this deployment.",
    "Now witness the power of this fully armed and operational battle station.",
]


def _wait_for_healthy(
    config: CLIConfig,
    region: str,
    transport: str,
    timeout_seconds: int = 600,
    poll_interval: int = 10,
) -> dict | None:
    """Poll the remote health endpoint with a Star Wars loading animation.

    The spinner updates every 200ms for a live feel, but actual health
    checks only fire every ``poll_interval`` seconds to avoid hammering
    the endpoint. Phase messages rotate every ~8 seconds.
    """
    import logging
    import random
    import sys

    deadline = time.monotonic() + timeout_seconds
    last_err = ""
    spin_idx = 0
    phase_idx = 0
    next_poll = time.monotonic()
    next_phase_change = time.monotonic() + 8

    # Suppress noisy Tailscale-fallback warnings during the wait so they
    # don't clobber the spinner line.
    remote_logger = logging.getLogger("deathstar_cli.remote")
    prev_level = remote_logger.level
    remote_logger.setLevel(logging.CRITICAL)

    try:
        client = RemoteAPIClient(config, region, transport=transport)
    except (RuntimeError, httpx.HTTPError) as exc:
        remote_logger.setLevel(prev_level)
        typer.echo(f"  Could not create API client: {exc}", err=True)
        return None

    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            elapsed = int(now - (deadline - timeout_seconds))

            # Rotate phase message periodically
            if now >= next_phase_change:
                phase_idx += 1
                next_phase_change = now + random.uniform(6, 10)

            # Render spinner
            phase = _HYPERSPACE_PHASES[phase_idx % len(_HYPERSPACE_PHASES)]
            spinner = _SPINNER[spin_idx % len(_SPINNER)]
            bar = _progress_bar(elapsed, timeout_seconds, width=20)
            sys.stderr.write(f"\r\033[K  {spinner} {phase}... {bar} [{elapsed}s / {timeout_seconds}s]")
            sys.stderr.flush()
            spin_idx += 1

            # Only poll when the interval has elapsed
            if now >= next_poll:
                next_poll = now + poll_interval
                try:
                    result = client._request("GET", "/v1/health")
                    sys.stderr.write("\r\033[K")
                    sys.stderr.flush()
                    quote = random.choice(_HYPERSPACE_READY)
                    typer.echo(f"\n  ✦ {quote}")
                    version = result.get("version", "unknown") if isinstance(result, dict) else "unknown"
                    typer.echo(f"  Version: {version}")
                    return result
                except (RuntimeError, httpx.HTTPError) as exc:
                    last_err = str(exc)

            time.sleep(0.2)
    finally:
        remote_logger.setLevel(prev_level)

    sys.stderr.write("\r\033[K")
    sys.stderr.flush()
    typer.echo(f"  ✗ Timed out after {timeout_seconds}s. Last error: {last_err[:200]}", err=True)
    return None


def _progress_bar(elapsed: int, total: int, width: int = 20) -> str:
    """Render a small progress bar like [████████░░░░░░░░░░░░]."""
    fraction = min(elapsed / total, 1.0) if total > 0 else 0.0
    filled = int(width * fraction)
    return "▐" + "█" * filled + "░" * (width - filled) + "▌"


@app.command()
def version() -> None:
    typer.echo(full_version())


# ---------------------------------------------------------------------------
# AWS regions offered during init (covers most common choices)
# ---------------------------------------------------------------------------
_AWS_REGIONS = [
    ("us-east-1", "US East (N. Virginia)"),
    ("us-east-2", "US East (Ohio)"),
    ("us-west-1", "US West (N. California)"),
    ("us-west-2", "US West (Oregon)"),
    ("eu-west-1", "EU (Ireland)"),
    ("eu-west-2", "EU (London)"),
    ("eu-central-1", "EU (Frankfurt)"),
    ("ap-southeast-1", "Asia Pacific (Singapore)"),
    ("ap-northeast-1", "Asia Pacific (Tokyo)"),
]

_INSTANCE_TYPES = [
    ("t3.medium", "2 vCPU / 4 GB  — light work"),
    ("t3.large", "2 vCPU / 8 GB  — recommended default"),
    ("t3.xlarge", "4 vCPU / 16 GB — heavy builds"),
    ("m5.xlarge", "4 vCPU / 16 GB — sustained workloads"),
    ("m5.2xlarge", "8 vCPU / 32 GB — parallel agents"),
]


def _numbered_pick(label: str, options: list[tuple[str, str]], default_value: str) -> str:
    """Present a numbered list and return the selected value."""
    typer.echo(f"\n  {label}")
    default_idx = 0
    for i, (value, desc) in enumerate(options, 1):
        marker = " *" if value == default_value else ""
        typer.echo(f"    [{i}] {value:<20} {desc}{marker}")
        if value == default_value:
            default_idx = i
    while True:
        raw = input(f"  Select [default: {default_idx}]: ").strip()
        if not raw:
            return default_value
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
        except ValueError:
            pass
        typer.echo("  Invalid choice — try again.")


def _prompt(label: str, default: str = "", secret: bool = False) -> str:
    """Simple prompt with an optional default."""
    suffix = f" [{default}]" if default else ""
    if secret:
        import getpass
        value = getpass.getpass(f"  {label}{suffix}: ").strip()
    else:
        value = input(f"  {label}{suffix}: ").strip()
    return value or default


@app.command()
def init() -> None:
    """Initialize your DeathStar. Guided setup that writes a .env file.

    A new crew member runs this once to configure their station. It collects
    your call sign, preferred sector (region), ship class (instance type),
    and crew manifest (git identity), then writes everything to .env.
    """
    from deathstar_cli.config import find_project_root

    try:
        project_root = find_project_root()
    except RuntimeError:
        typer.echo("Error: could not locate the DeathStar project root.", err=True)
        raise typer.Exit(code=1)

    env_path = project_root / ".env"
    if env_path.exists():
        typer.echo("")
        typer.echo("  ⚠ A .env file already exists.")
        if not typer.confirm("  Overwrite with a fresh configuration?"):
            raise typer.Exit(0)

    typer.echo("")
    typer.echo("  ╔══════════════════════════════════════════════════════════════╗")
    typer.echo("  ║                                                              ║")
    typer.echo("  ║   D E A T H S T A R   —   S T A T I O N   S E T U P        ║")
    typer.echo("  ║                                                              ║")
    typer.echo("  ║   \"The ability to destroy a planet is insignificant          ║")
    typer.echo("  ║    next to the power of the Force.\"                          ║")
    typer.echo("  ║                                                              ║")
    typer.echo("  ║   Welcome, operator. Let's get your battle station online.   ║")
    typer.echo("  ║                                                              ║")
    typer.echo("  ╚══════════════════════════════════════════════════════════════╝")

    # ── Call sign (project name) ──────────────────────────────────────────
    typer.echo("")
    typer.echo("  ── CALL SIGN ─────────────────────────────────────────────────")
    typer.echo("  Your call sign identifies this station in AWS and on Tailscale.")
    typer.echo("  Each crew member should use a unique name (e.g., deathstar-luke).")
    typer.echo("")

    while True:
        callsign = _prompt("Call sign", "deathstar")
        if re.match(r"^[a-zA-Z0-9_-]+$", callsign):
            break
        typer.echo("  Call signs may only contain letters, numbers, hyphens, and underscores.")

    # ── Sector assignment (AWS region) ────────────────────────────────────
    typer.echo("")
    typer.echo("  ── SECTOR ASSIGNMENT ─────────────────────────────────────────")
    typer.echo("  Choose which galactic sector to deploy in.")
    region = _numbered_pick("Available sectors:", _AWS_REGIONS, "us-west-1")

    # ── AWS Profile ───────────────────────────────────────────────────────
    typer.echo("")
    typer.echo("  ── IMPERIAL CREDENTIALS ──────────────────────────────────────")
    typer.echo("  The AWS CLI profile used for Terraform and SSM operations.")
    aws_profile = _prompt("AWS profile name", "default")

    # ── Ship class (instance type) ────────────────────────────────────────
    typer.echo("")
    typer.echo("  ── SHIP CLASS ────────────────────────────────────────────────")
    typer.echo("  Select the firepower for your station.")
    instance_type = _numbered_pick("Available ships:", _INSTANCE_TYPES, "t3.large")

    # ── Storage ───────────────────────────────────────────────────────────
    typer.echo("")
    typer.echo("  ── CARGO BAY ─────────────────────────────────────────────────")
    data_volume = _prompt("Workspace volume size in GB", "200")
    try:
        int(data_volume)
    except ValueError:
        typer.echo("  Invalid number — using 200 GB.")
        data_volume = "200"

    # ── Crew manifest (git identity) ──────────────────────────────────────
    typer.echo("")
    typer.echo("  ── CREW MANIFEST ─────────────────────────────────────────────")
    typer.echo("  Git identity for automated commits made by the station.")

    # Try to detect from git config
    default_name = "DeathStar"
    default_email = "deathstar@local"
    try:
        result = subprocess.run(
            ["git", "config", "user.name"], capture_output=True, text=True, check=True
        )
        if result.stdout.strip():
            default_name = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    try:
        result = subprocess.run(
            ["git", "config", "user.email"], capture_output=True, text=True, check=True
        )
        if result.stdout.strip():
            default_email = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    git_name = _prompt("Git author name", default_name)
    git_email = _prompt("Git author email", default_email)

    # ── Tailscale ─────────────────────────────────────────────────────────
    typer.echo("")
    typer.echo("  ── SECURE COMMS (TAILSCALE) ──────────────────────────────────")
    typer.echo("  Tailscale creates a private encrypted tunnel to your station.")
    typer.echo("  Highly recommended — without it, you'll need SSM for access.")
    enable_tailscale = typer.confirm("  Enable Tailscale?", default=True)

    # ── API Token ─────────────────────────────────────────────────────────
    typer.echo("")
    typer.echo("  ── SHIELD GENERATOR (API TOKEN) ──────────────────────────────")
    typer.echo("  Optional bearer token to protect the control API.")
    typer.echo("  If only accessible via Tailscale, you can leave this blank.")
    api_token = _prompt("API token (blank to skip)", "", secret=True)

    # ── GitHub OAuth ──────────────────────────────────────────────────────
    typer.echo("")
    typer.echo("  ── REBEL ALLIANCE LINK (GITHUB) ──────────────────────────────")
    typer.echo("  OAuth App client ID for `deathstar github setup`.")
    typer.echo("  Create at: https://github.com/settings/applications/new")
    typer.echo("  (Enable Device Flow, then paste the Client ID here)")
    github_client_id = _prompt("GitHub OAuth Client ID (blank to skip)", "")

    # ── Write .env ────────────────────────────────────────────────────────
    lines = [
        "# DeathStar configuration — generated by `deathstar init`",
        f"DEATHSTAR_PROJECT_NAME={callsign}",
        f"DEATHSTAR_REGION={region}",
        f"DEATHSTAR_AWS_PROFILE={aws_profile}",
        "DEATHSTAR_TERRAFORM_DIR=terraform/environments/aws-ec2",
        f"DEATHSTAR_INSTANCE_TYPE={instance_type}",
        "DEATHSTAR_ROOT_VOLUME_SIZE_GB=30",
        f"DEATHSTAR_DATA_VOLUME_SIZE_GB={data_volume}",
        "",
        "# Parameter Store locations for remote-only secrets",
        f"DEATHSTAR_OPENAI_PARAMETER_NAME=/{callsign}/providers/openai/api_key",
        f"DEATHSTAR_ANTHROPIC_PARAMETER_NAME=/{callsign}/providers/anthropic/api_key",
        f"DEATHSTAR_GOOGLE_PARAMETER_NAME=/{callsign}/providers/google/api_key",
        f"DEATHSTAR_VERTEX_PARAMETER_NAME=/{callsign}/providers/vertex/service_account_key",
        f"DEATHSTAR_GITHUB_PARAMETER_NAME=/{callsign}/integrations/github/token",
        "",
        "# Vertex AI (optional)",
        "DEATHSTAR_VERTEX_PROJECT_ID=",
        "DEATHSTAR_VERTEX_LOCATION=us-central1",
        "",
        "# Off-instance backups (optional)",
        "DEATHSTAR_CREATE_BACKUP_BUCKET=false",
        "DEATHSTAR_BACKUP_BUCKET_NAME=",
        "DEATHSTAR_FORCE_DESTROY_BACKUP_BUCKET=false",
        "",
        "# Web UI",
        "DEATHSTAR_ENABLE_WEB_UI=false",
        "DEATHSTAR_WEB_UI_PORT=8443",
        "DEATHSTAR_WEB_UI_ALLOWED_CIDRS=",
        "",
        "# Git identity for automated commits",
        f"DEATHSTAR_GIT_AUTHOR_NAME={git_name}",
        f"DEATHSTAR_GIT_AUTHOR_EMAIL={git_email}",
        "",
        "# Tailscale",
        f"DEATHSTAR_ENABLE_TAILSCALE={'true' if enable_tailscale else 'false'}",
        f"DEATHSTAR_ENABLE_TAILSCALE_SSH={'true' if enable_tailscale else 'false'}",
        f"DEATHSTAR_TAILSCALE_AUTH_PARAMETER_NAME=/{callsign}/integrations/tailscale/auth_key",
        "DEATHSTAR_TAILSCALE_HOSTNAME=",
        "DEATHSTAR_TAILSCALE_ADVERTISE_TAGS=",
        "",
        "# Database",
        f"DEATHSTAR_DB_PASSWORD_PARAMETER_NAME=/{callsign}/database/password",
        "",
        "# API authentication",
        f"DEATHSTAR_API_TOKEN={api_token}",
        "",
        "# GitHub OAuth App",
        f"DEATHSTAR_GITHUB_APP_CLIENT_ID={github_client_id}",
        "",
        "# Tailscale OAuth (optional — enables automatic node cleanup on upgrade)",
        "DEATHSTAR_TAILSCALE_OAUTH_CLIENT_ID=",
        "DEATHSTAR_TAILSCALE_OAUTH_CLIENT_SECRET=",
        "",
        "# Event system",
        "GITHUB_WEBHOOK_SECRET=",
        "GITHUB_POLL_INTERVAL=10",
        "",
        "# Transport defaults",
        "DEATHSTAR_REMOTE_TRANSPORT=auto",
        "DEATHSTAR_CONNECT_TRANSPORT=auto",
    ]

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    typer.echo("")
    typer.echo("  ╔══════════════════════════════════════════════════════════════╗")
    typer.echo("  ║                                                              ║")
    typer.echo("  ║   STATION ONLINE                                             ║")
    typer.echo("  ║                                                              ║")
    typer.echo(f"  ║   Call sign : {callsign:<44} ║")
    typer.echo(f"  ║   Sector   : {region:<44} ║")
    typer.echo(f"  ║   Ship     : {instance_type:<44} ║")
    typer.echo(f"  ║   Tailscale: {'enabled' if enable_tailscale else 'disabled':<44} ║")
    typer.echo("  ║                                                              ║")
    typer.echo("  ║   Configuration written to .env                              ║")
    typer.echo("  ║                                                              ║")
    typer.echo("  ║   Next steps:                                                ║")
    typer.echo("  ║     1. deathstar secrets bootstrap    (store API keys)       ║")
    if enable_tailscale:
        typer.echo("  ║     2. deathstar tailscale setup      (Tailscale auth key)  ║")
        typer.echo("  ║     3. deathstar github setup         (GitHub token)        ║")
        typer.echo("  ║     4. deathstar deploy               (launch the station)  ║")
    else:
        typer.echo("  ║     2. deathstar github setup         (GitHub token)        ║")
        typer.echo("  ║     3. deathstar deploy               (launch the station)  ║")
    typer.echo("  ║                                                              ║")
    typer.echo("  ║   \"The Force will be with you. Always.\"                      ║")
    typer.echo("  ║                                                              ║")
    typer.echo("  ╚══════════════════════════════════════════════════════════════╝")
    typer.echo("")


@secrets_app.command("put")
def secrets_put(
    provider: ProviderName | None = typer.Option(None, "--provider"),
    integration: IntegrationName | None = typer.Option(None, "--integration"),
    name: str | None = typer.Option(None, "--name", help="Explicit SSM parameter name."),
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    stdin: bool = typer.Option(
        False,
        "--stdin",
        help="Read the secret from stdin instead of a hidden prompt.",
    ),
    file: str | None = typer.Option(
        None,
        "--file",
        help="Read the secret from a file (useful for JSON credential configs).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Overwrite an existing parameter without prompting.",
    ),
) -> None:
    if stdin and file:
        raise typer.BadParameter("--stdin and --file are mutually exclusive")
    config = _config()
    effective_region = region or config.region
    target = resolve_secret_target(
        config,
        provider=provider,
        integration=integration,
        name=name,
    )
    action, version = prompt_and_store_secret(
        config,
        effective_region,
        target,
        force=yes,
        stdin=stdin,
        file=file,
    )
    suffix = f" (version {version})" if version is not None else ""
    typer.echo(f"{action}: {target.parameter_name} in {effective_region}{suffix}")


@secrets_app.command("bootstrap")
def secrets_bootstrap(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    include_tailscale: bool = typer.Option(
        True,
        "--include-tailscale/--no-include-tailscale",
        help="Prompt for the Tailscale auth key as part of the bootstrap flow.",
    ),
    include_github: bool = typer.Option(
        False,
        "--include-github/--no-include-github",
        help="Prompt for the optional GitHub token as part of the bootstrap flow.",
    ),
    include_database: bool = typer.Option(
        True,
        "--include-database/--no-include-database",
        help="Prompt for the PostgreSQL database password.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Overwrite existing parameters without prompting.",
    ),
) -> None:
    config = _config()
    effective_region = region or config.region
    targets = bootstrap_targets(
        config,
        include_tailscale=include_tailscale,
        include_github=include_github,
        include_database=include_database,
    )

    typer.echo(
        "Paste each secret when prompted. Input is hidden, and pressing Enter skips that item."
    )

    created = 0
    updated = 0
    skipped = 0

    for target in targets:
        secret_value = prompt_for_secret(target.label, allow_empty=True)
        if secret_value is None:
            skipped += 1
            typer.echo(f"skipped: {target.parameter_name}")
            continue

        try:
            action, version = put_secret_value(
                config,
                effective_region,
                target,
                secret_value,
                force=yes,
            )
        except typer.Exit:
            skipped += 1
            typer.echo(f"skipped: {target.parameter_name}")
            continue
        if action == "created":
            created += 1
        else:
            updated += 1
        suffix = f" (version {version})" if version is not None else ""
        typer.echo(f"{action}: {target.parameter_name} in {effective_region}{suffix}")

    typer.echo(f"summary: created={created} updated={updated} skipped={skipped}")


@github_app.command("setup")
def github_setup(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    method: str = typer.Option(
        "auto",
        "--method",
        help="Auth method: auto, gh, pat, or oauth.",
    ),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="GitHub OAuth App client ID (only needed for --method oauth).",
    ),
    yes: bool = typer.Option(False, "--yes", help="Overwrite an existing token without prompting."),
) -> None:
    """Authorize DeathStar with GitHub and store the token in SSM.

    Methods (--method):
      auto  - Use gh CLI if available, otherwise open browser for PAT creation
      gh    - Use the gh CLI (runs gh auth login if not already logged in)
      pat   - Open browser to create a personal access token, then paste it
      oauth - GitHub OAuth Device Flow (requires --client-id or DEATHSTAR_GITHUB_APP_CLIENT_ID)
    """
    from deathstar_cli.github_auth import (
        guided_pat_creation,
        login_via_gh_cli,
        run_device_flow,
        token_from_gh_cli,
    )

    config = _config()
    effective_region = region or config.region
    normalized_method = method.strip().lower()

    if normalized_method not in {"auto", "gh", "pat", "oauth"}:
        raise typer.BadParameter("method must be auto, gh, pat, or oauth")

    token: str | None = None

    if normalized_method == "oauth":
        resolved_client_id = client_id or config.github_app_client_id
        if not resolved_client_id:
            typer.echo(
                "OAuth method requires a GitHub OAuth App client ID.\n\n"
                "Create one at https://github.com/settings/applications/new\n"
                "  - Check 'Enable Device Flow'\n"
                "  - Then pass --client-id <ID> or set DEATHSTAR_GITHUB_APP_CLIENT_ID in .env",
                err=True,
            )
            raise typer.Exit(code=1)
        token = run_device_flow(resolved_client_id)

    elif normalized_method == "gh":
        token = token_from_gh_cli()
        if token:
            typer.echo("Using token from existing gh CLI session.")
        else:
            token = login_via_gh_cli()

    elif normalized_method == "pat":
        token = guided_pat_creation()

    else:
        # auto: try gh CLI first, then guided PAT
        token = token_from_gh_cli()
        if token:
            typer.echo("Found existing gh CLI session.")
        else:
            import shutil

            if shutil.which("gh"):
                typer.echo("gh CLI found but not authenticated.")
                if typer.confirm("Run gh auth login?", default=True):
                    token = login_via_gh_cli()

            if not token:
                token = guided_pat_creation()

    if not token:
        raise typer.BadParameter("no token was obtained")

    typer.echo("GitHub token obtained.")

    target = resolve_secret_target(config, integration=IntegrationName.GITHUB)
    action, secret_version = put_secret_value(
        config,
        effective_region,
        target,
        token,
        force=yes,
    )
    suffix = f" (version {secret_version})" if secret_version is not None else ""
    typer.echo(f"{action}: {target.parameter_name} in {effective_region}{suffix}")


@tailscale_app.command("setup")
def tailscale_setup(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="Tailscale OAuth client ID (from admin console > Settings > OAuth clients).",
    ),
    reusable: bool = typer.Option(True, "--reusable/--no-reusable", help="Create a reusable auth key."),
    ephemeral: bool = typer.Option(True, "--ephemeral/--no-ephemeral", help="Create an ephemeral auth key."),
    preauthorized: bool = typer.Option(
        True, "--preauthorized/--no-preauthorized", help="Create a preauthorized auth key."
    ),
    yes: bool = typer.Option(False, "--yes", help="Overwrite an existing auth key without prompting."),
) -> None:
    """Create a Tailscale auth key via the API and store it in SSM.

    Requires a Tailscale OAuth client (client ID + client secret).
    Create one in the Tailscale admin console under Settings > OAuth clients.

    Steps:
      1. Go to https://login.tailscale.com/admin/settings/oauth
      2. Click "Generate OAuth client..."
      3. Grant at least the "Keys: Write" scope (under Auth Keys)
      4. Copy the client ID and client secret
      5. Run this command and paste them when prompted

    The command uses the OAuth client credentials to create an auth key
    via the Tailscale API, then stores it in AWS SSM Parameter Store.
    """
    from deathstar_cli.tailscale_auth import (
        create_auth_key,
        get_oauth_token,
        prompt_for_credentials,
    )

    config = _config()
    effective_region = region or config.region

    resolved_client_id = client_id or config.tailscale_oauth_client_id
    if resolved_client_id:
        import getpass

        typer.echo(f"Using Tailscale OAuth client ID: {resolved_client_id}")
        client_secret = getpass.getpass("Tailscale OAuth client secret: ")
        if not client_secret:
            raise typer.BadParameter("client secret cannot be empty")
        client_id = resolved_client_id
    else:
        client_id, client_secret = prompt_for_credentials()

    typer.echo("Authenticating with Tailscale API...")
    access_token = get_oauth_token(client_id, client_secret)

    tags = config.tailscale_advertise_tags or None
    typer.echo("Creating auth key...")
    auth_key = create_auth_key(
        access_token,
        reusable=reusable,
        ephemeral=ephemeral,
        preauthorized=preauthorized,
        tags=tags,
        description=f"DeathStar - {config.project_name}",
    )

    typer.echo("Tailscale auth key created.")

    target = resolve_secret_target(config, integration=IntegrationName.TAILSCALE)
    action, secret_version = put_secret_value(
        config,
        effective_region,
        target,
        auth_key,
        force=yes,
    )
    suffix = f" (version {secret_version})" if secret_version is not None else ""
    typer.echo(f"{action}: {target.parameter_name} in {effective_region}{suffix}")


@tailscale_app.command("cleanup")
def tailscale_cleanup(
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="Tailscale OAuth client ID. Defaults to DEATHSTAR_TAILSCALE_OAUTH_CLIENT_ID.",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="Tailscale OAuth client secret. Defaults to DEATHSTAR_TAILSCALE_OAUTH_CLIENT_SECRET.",
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip prompts."),
) -> None:
    """Clean up Tailscale devices after a deploy or upgrade.

    When the EC2 instance is replaced, the new node registers with a
    suffixed name (e.g. deathstar-1) because the old node still exists.
    This command:

      1. Deletes offline devices matching your hostname
      2. Renames any suffixed device (deathstar-1) back to the base hostname

    Run this after a deploy/upgrade, or let it happen automatically by
    setting both DEATHSTAR_TAILSCALE_OAUTH_CLIENT_ID and
    DEATHSTAR_TAILSCALE_OAUTH_CLIENT_SECRET in .env.

    Requires OAuth client scopes: "Devices: Read" + "Devices: Write".
    """
    result = _tailscale_cleanup(client_id=client_id, client_secret=client_secret, yes=yes)
    if not result["deleted"] and not result["renamed"]:
        typer.echo("Nothing to clean up.")


@tailscale_app.command("fix")
def tailscale_fix(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    client_id: str | None = typer.Option(
        None,
        "--client-id",
        help="Tailscale OAuth client ID.",
    ),
    client_secret: str | None = typer.Option(
        None,
        "--client-secret",
        help="Tailscale OAuth client secret.",
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip prompts."),
) -> None:
    """Fix Tailscale connectivity after an instance replacement.

    When the EC2 instance is replaced, the old Tailscale node lingers and
    the new one registers with a suffixed name (e.g. deathstar-1).  This
    command:

      1. Cleans up stale/suffixed devices via the Tailscale API
      2. Re-runs tailscale up on the instance via SSM (break-glass)
      3. Verifies the connection is working

    Requires OAuth client scopes: "Devices: Read" + "Devices: Write".
    """
    config = _config()
    effective_region = region or config.region

    # Step 1 — API cleanup (delete stale, rename suffixed)
    typer.echo("  [1/3] Cleaning up stale Tailscale devices...")
    try:
        result = _tailscale_cleanup(client_id=client_id, client_secret=client_secret, yes=yes)
        if result["deleted"] or result["renamed"]:
            typer.echo(f"        Cleaned: {len(result['deleted'])} deleted, {len(result['renamed'])} renamed")
        else:
            typer.echo("        No stale devices found.")
    except (typer.BadParameter, httpx.HTTPError) as exc:
        typer.echo(f"        API cleanup failed: {exc}", err=True)
        typer.echo("        Continuing with SSM restart...")

    # Step 2 — re-register Tailscale on the instance via SSM
    typer.echo("  [2/3] Re-registering Tailscale on instance via SSM...")
    outputs = terraform_outputs(config, effective_region)
    instance_id = str(outputs["instance_id"])
    hostname = config.tailscale_hostname
    auth_param = config.tailscale_auth_parameter_name

    # Build the tailscale up flags to match configure-tailscale.sh
    ts_flags = f"--hostname={hostname} --reset"
    if config.enable_tailscale_ssh:
        ts_flags += " --ssh"
    if config.tailscale_advertise_tags:
        ts_flags += f" --advertise-tags={','.join(config.tailscale_advertise_tags)}"

    ssm_script = (
        f'TS_AUTH_KEY=$(aws ssm get-parameter --region {effective_region}'
        f' --name "{auth_param}" --with-decryption'
        f" --query 'Parameter.Value' --output text) && "
        f"systemctl restart tailscaled && sleep 2 && "
        f"tailscale up --auth-key=$TS_AUTH_KEY {ts_flags} && "
        f"tailscale status"
    )

    try:
        output = run_via_ssm(config, effective_region, instance_id, ssm_script)
        typer.echo("        Tailscale re-registered.")
        if output.strip():
            for line in output.strip().splitlines()[:5]:
                typer.echo(f"        {line}")
    except RuntimeError as exc:
        typer.echo(f"        SSM command failed: {exc}", err=True)
        raise typer.Exit(code=1)

    # Step 3 — verify connectivity
    typer.echo("  [3/3] Verifying Tailscale connectivity...")
    hostname = config.tailscale_hostname

    for attempt in range(6):
        try:
            result_ping = subprocess.run(
                ["tailscale", "ping", "--timeout=3s", "-c1", hostname],
                capture_output=True,
                text=True,
            )
            if result_ping.returncode == 0:
                typer.echo(f"        Connected to {hostname}")
                return
        except FileNotFoundError:
            typer.echo("        tailscale CLI not found locally", err=True)
            raise typer.Exit(code=1)
        if attempt < 5:
            time.sleep(3)

    typer.echo(f"        Could not reach {hostname} — the node may need time to re-register.", err=True)
    typer.echo(f"        Try: tailscale ping {hostname}")


def _get_tailscale_token(
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> str | None:
    """Resolve OAuth credentials and return an access token, or None if unavailable."""
    from deathstar_cli.tailscale_auth import get_oauth_token

    config = _config()
    resolved_id = client_id or config.tailscale_oauth_client_id
    resolved_secret = client_secret or config.tailscale_oauth_client_secret

    if not resolved_id:
        typer.echo("No Tailscale OAuth client configured — skipping cleanup.")
        typer.echo("Set DEATHSTAR_TAILSCALE_OAUTH_CLIENT_ID and DEATHSTAR_TAILSCALE_OAUTH_CLIENT_SECRET in .env")
        return None

    if not resolved_secret:
        import getpass

        resolved_secret = getpass.getpass("Tailscale OAuth client secret: ")
        if not resolved_secret:
            raise typer.BadParameter("client secret cannot be empty")

    return get_oauth_token(resolved_id, resolved_secret)


def _device_display_name(device: dict) -> str:
    """Extract the short machine name from a Tailscale device.

    The API returns a `name` like "deathstar-1.tailnet-abc.ts.net" and a
    `hostname` like "deathstar".  The `-1` suffix only appears in `name`,
    so we derive the display name from the FQDN by stripping the tailnet
    domain.
    """
    fqdn = device.get("name", "")
    if "." in fqdn:
        return fqdn.split(".")[0]
    # Fallback to hostname if name is missing or unqualified.
    return device.get("hostname", "")


def _tailscale_cleanup(
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    yes: bool = False,
) -> dict[str, list[str]]:
    """Delete stale devices and rename suffixed ones back to the base hostname.

    Returns {"deleted": [...], "renamed": [...]}.
    """
    from deathstar_cli.tailscale_auth import (
        delete_device,
        list_devices,
        rename_device,
    )

    access_token = _get_tailscale_token(client_id=client_id, client_secret=client_secret)
    if not access_token:
        return {"deleted": [], "renamed": []}

    config = _config()
    hostname = config.tailscale_hostname
    devices = list_devices(access_token)

    # Partition matching devices into: delete (offline, base name) vs rename (suffixed).
    # The Tailscale API `hostname` field is what the machine set (always "deathstar"),
    # but the `name` field is the MagicDNS FQDN where the suffix lives
    # (e.g. "deathstar-1.tailnet-abc.ts.net").
    to_delete: list[dict] = []
    to_rename: list[dict] = []

    for device in devices:
        display = _device_display_name(device)
        if display != hostname and not display.startswith(f"{hostname}-"):
            continue

        if display != hostname:
            # Suffixed device (e.g. deathstar-1) — rename it regardless of online status.
            to_rename.append(device)
        elif not device.get("online", False):
            # Base-named device that's offline — stale, delete it.
            to_delete.append(device)

    # Show summary and confirm.
    if not to_delete and not to_rename:
        return {"deleted": [], "renamed": []}

    if not yes:
        if to_delete:
            typer.echo(f"  Found {len(to_delete)} offline device(s) to remove:")
            for d in to_delete:
                addr = d.get("addresses", ["?"])[0]
                typer.echo(f"    - {_device_display_name(d)} ({addr})")
        if to_rename:
            typer.echo(f"  Found {len(to_rename)} device(s) to rename → {hostname}:")
            for d in to_rename:
                addr = d.get("addresses", ["?"])[0]
                typer.echo(f"    - {_device_display_name(d)} ({addr})")
        if not typer.confirm("  Proceed?"):
            return {"deleted": [], "renamed": []}

    # Delete stale devices first (so the rename target hostname is free).
    deleted: list[str] = []
    for device in to_delete:
        device_id = device.get("id") or device.get("nodeId")
        if device_id:
            delete_device(access_token, device_id)
            display = _device_display_name(device)
            deleted.append(display)
            typer.echo(f"  Deleted: {display}")

    # Rename suffixed devices back to the base hostname.
    renamed: list[str] = []
    for device in to_rename:
        device_id = device.get("id") or device.get("nodeId")
        if device_id:
            old_name = _device_display_name(device)
            rename_device(access_token, device_id, hostname)
            renamed.append(f"{old_name} → {hostname}")
            typer.echo(f"  Renamed: {old_name} → {hostname}")

    return {"deleted": deleted, "renamed": renamed}


@app.command()
def deploy(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    yes: bool = typer.Option(False, "--yes", help="Skip interactive confirmation."),
    skip_backup: bool = typer.Option(
        False, "--skip-backup", help="Skip pre-deploy backup of the remote instance.",
    ),
    transport: Literal["auto", "tailscale", "ssm"] = typer.Option("auto", "--transport"),
) -> None:
    config = _config()
    effective_region = region or config.region

    terraform_init(config, effective_region)

    if not yes and not typer.confirm(f"Deploy DeathStar into {effective_region}?"):
        raise typer.Exit(code=1)

    # Pre-deploy backup: if an instance is already running, back up before
    # Terraform potentially replaces it.  The EBS data volume survives
    # instance replacement, but an explicit backup is a safety net.
    if not skip_backup:
        typer.echo("  Creating pre-deploy backup...")
        try:
            client = RemoteAPIClient(
                config,
                effective_region,
                transport=_validate_transport(
                    transport if transport != "auto" else config.remote_transport
                ),
            )
            backup_response = client.backup(BackupRequest(label="pre-deploy"))
            typer.echo(f"  Backup: {backup_response.backup_id}")
        except (RuntimeError, httpx.HTTPError):
            typer.echo("  Skipping backup — remote instance not reachable (first deploy?).")
    else:
        typer.echo("  Skipping backup (--skip-backup).")

    # Clean up stale Tailscale nodes before deploy so the new instance gets a clean hostname.
    if config.enable_tailscale and config.tailscale_oauth_client_id and config.tailscale_oauth_client_secret:
        try:
            _tailscale_cleanup(yes=yes)
        except (typer.BadParameter, httpx.HTTPError):
            pass  # best-effort during deploy

    terraform_apply(config, effective_region, auto_approve=yes)
    _display_terraform_summary(effective_region)

    # Wait for the instance to become healthy (cloud-init + Docker build)
    typer.echo("\n  Waiting for Death Star to come online...")
    effective_transport = _validate_transport(
        transport if transport != "auto" else config.remote_transport,
    )
    _wait_for_healthy(config, effective_region, effective_transport)


def _build_and_push_image(config: CLIConfig, effective_region: str) -> None:
    """Build the Docker image locally and push it to the remote instance."""
    import shutil

    from deathstar_shared.version import VERSION

    if not shutil.which("docker"):
        typer.echo("Error: Docker is required for redeploy/upgrade.", err=True)
        typer.echo("Install Docker Desktop: https://docs.docker.com/get-docker/", err=True)
        raise typer.Exit(code=1)

    # Check that the installed CLI version matches the source version.
    # Mismatches happen when uv tool caches a stale install.
    source_version_file = config.project_root / "shared" / "deathstar_shared" / "version.py"
    if source_version_file.exists():
        for line in source_version_file.read_text().splitlines():
            if line.startswith("VERSION"):
                source_ver = line.split('"')[1]
                if source_ver != VERSION:
                    typer.echo(
                        f"Error: CLI version ({VERSION}) doesn't match source ({source_ver}).",
                        err=True,
                    )
                    typer.echo("Run: uv tool install -e . --force", err=True)
                    raise typer.Exit(code=1)
                break

    image_tag = f"deathstar-app:{VERSION}"

    # Step 1: Build locally
    typer.echo(f"  [1/3] Building Docker image ({image_tag})...")
    build_cmd = [
        "docker", "build",
        "--platform", "linux/amd64",
        "-t", image_tag,
        "-t", "deathstar-app:latest",
        "-f", "docker/control-api.Dockerfile",
        ".",
    ]
    try:
        subprocess.run(
            build_cmd,
            cwd=str(config.project_root),
            check=True,
            capture_output=True,
            text=True,
        )
        typer.echo("        Build complete.")
    except subprocess.CalledProcessError as exc:
        typer.echo(f"        Build failed: {(exc.stderr or '')[:500]}", err=True)
        raise typer.Exit(code=1) from exc

    # Step 2: Push to instance via Tailscale SSH
    typer.echo("  [2/3] Pushing image to instance...")
    outputs = terraform_outputs(config, effective_region)
    tailscale_hostname = str(
        outputs.get("tailscale_hostname") or config.tailscale_hostname
    ).strip()
    ssh_user = str(outputs.get("ssh_user", "ubuntu"))

    ssh_target = f"{ssh_user}@{tailscale_hostname}"
    try:
        push_image_via_tailscale(tailscale_hostname, ssh_user, image_tag)
        # Also push the updated docker-compose.yml and start-runtime.sh
        # Use ssh + sudo tee since the target dirs are root-owned
        clear_known_host(tailscale_hostname)
        ssh_opts = ["-o", "StrictHostKeyChecking=accept-new"]
        compose_file = config.project_root / "docker" / "docker-compose.yml"
        start_script = config.project_root / "bootstrap" / "files" / "start-runtime.sh"
        for local, remote in [
            (compose_file, "/opt/deathstar/repo/docker/docker-compose.yml"),
            (start_script, "/opt/deathstar/start-runtime.sh"),
        ]:
            subprocess.run(
                ["ssh", *ssh_opts, ssh_target, f"sudo tee {remote} > /dev/null"],
                input=local.read_bytes(),
                check=True,
                capture_output=True,
            )
        # Ensure start-runtime.sh is executable and retag image as latest
        subprocess.run(
            ["ssh", *ssh_opts, ssh_target,
             f"sudo chmod +x /opt/deathstar/start-runtime.sh && "
             f"docker tag {image_tag} deathstar-app:latest"],
            check=True,
            capture_output=True,
        )
        typer.echo("        Image and config pushed.")
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        typer.echo(f"        Push failed: {exc}", err=True)
        typer.echo("        Tip: ensure Tailscale SSH ACL allows your user to SSH as ubuntu.", err=True)
        raise typer.Exit(code=1) from exc

    # Step 3: Restart container on instance
    typer.echo("  [3/3] Restarting container...")
    instance_id = str(outputs["instance_id"])

    session_kwargs: dict[str, str] = {"region_name": effective_region}
    if config.aws_profile:
        session_kwargs["profile_name"] = config.aws_profile

    ssm = boto3.Session(**session_kwargs).client("ssm")

    # Run start-runtime.sh directly (not systemctl restart) to avoid
    # sync-runtime.sh ExecStartPre which would overwrite our pushed files.
    response = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": ["/opt/deathstar/start-runtime.sh"]},
        TimeoutSeconds=600,
    )
    command_id = response["Command"]["CommandId"]

    for _ in range(180):
        time.sleep(2)
        try:
            invocation = ssm.get_command_invocation(CommandId=command_id, InstanceId=instance_id)
        except ssm.exceptions.InvocationDoesNotExist:
            continue

        if invocation["Status"] in ("Success", "Failed", "Cancelled", "TimedOut"):
            if invocation["Status"] != "Success":
                stderr = invocation.get("StandardErrorContent", "")
                typer.echo(f"        Restart failed: {stderr[:300]}", err=True)
                raise typer.Exit(code=1)
            typer.echo("        Container restarted.")
            break
    else:
        typer.echo("        Timed out waiting for restart.", err=True)
        raise typer.Exit(code=1)

    # Verify health — use SSM directly since the container just restarted
    # and Tailscale health checks will fail with connection refused until
    # the API port is listening, producing noisy fallback warnings.
    typer.echo("        Waiting for instance to come up...")
    health = _wait_for_healthy(config, effective_region, "ssm")
    if health:
        typer.echo(f"  Deploy complete. Version: {health.get('version', 'unknown')}")
    else:
        typer.echo("  Instance did not become healthy within the timeout.", err=True)
        typer.echo("  Run `deathstar status` to check manually.", err=True)
        raise typer.Exit(code=1)


@app.command()
def redeploy(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    yes: bool = typer.Option(False, "--yes", help="Skip interactive confirmation."),
) -> None:
    """Build the Docker image locally and deploy to the remote instance.

    Steps:
      1. Build Docker image locally (linux/amd64)
      2. Push image to instance via Tailscale SSH (docker save | ssh docker load)
      3. Restart container with blue/green health check
    """
    config = _config()
    effective_region = region or config.region
    _build_and_push_image(config, effective_region)


@app.command()
def reboot(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    yes: bool = typer.Option(False, "--yes", help="Skip interactive confirmation."),
) -> None:
    """Reboot the remote EC2 instance.

    Non-destructive — the instance, EBS volumes, and IP stay the same.
    Useful when SSM and Tailscale are both unreachable.
    """
    config = _config()
    effective_region = region or config.region
    outputs = terraform_outputs(config, effective_region)
    instance_id = str(outputs["instance_id"])

    if not yes:
        typer.confirm(f"  Reboot instance {instance_id}?", abort=True)

    ec2 = boto3.client("ec2", region_name=effective_region)
    ec2.reboot_instances(InstanceIds=[instance_id])
    typer.echo(f"  Reboot initiated for {instance_id}.")
    typer.echo("  Wait 1–2 minutes, then try: deathstar status")


@app.command(name="console-log")
def console_log(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    tail: int = typer.Option(200, "--tail", help="Number of lines to show."),
) -> None:
    """Show the EC2 serial console output.

    Works even when SSM and Tailscale are unreachable — reads directly
    from the EC2 hypervisor. Useful for diagnosing boot failures,
    cloud-init errors, and kernel panics.
    """
    config = _config()
    effective_region = region or config.region
    outputs = terraform_outputs(config, effective_region)
    instance_id = str(outputs["instance_id"])

    ec2 = boto3.client("ec2", region_name=effective_region)
    response = ec2.get_console_output(InstanceId=instance_id, Latest=True)
    output = response.get("Output", "")

    if not output:
        typer.echo("  No console output available (instance may still be booting).", err=True)
        raise typer.Exit(code=1)

    lines = output.splitlines()
    for line in lines[-tail:]:
        typer.echo(line)


@app.command()
def upgrade(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    yes: bool = typer.Option(False, "--yes", help="Skip interactive confirmations."),
    skip_backup: bool = typer.Option(False, "--skip-backup", help="Skip pre-upgrade backup."),
    transport: Literal["auto", "tailscale", "ssm"] = typer.Option("auto", "--transport"),
    verbose: bool = typer.Option(False, "--verbose", help="Show full terraform output."),
) -> None:
    """Upgrade the CLI and redeploy the remote instance.

    Supports two install modes:
      - **Source (git clone):** pull latest, reinstall editable
      - **PyPI (`uv tool install deathstar-ai`):** upgrade from PyPI

    Steps:
      1. Update local CLI (git pull + reinstall, or PyPI upgrade)
      2. Compare local vs remote version
      3. Create a backup on the remote instance (unless --skip-backup)
      4. Build Docker image locally and push to instance via SSH
    """
    import shutil

    config = _config()
    effective_region = region or config.region

    # Detect install mode: source (editable) vs PyPI
    is_source_install = (config.project_root / ".git").is_dir()
    installer = "uv" if shutil.which("uv") else "pip"

    if is_source_install:
        # Step 1a: Check for uncommitted changes
        typer.echo("  [1/6] Checking local repo state...")
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(config.project_root),
                capture_output=True,
                text=True,
                check=True,
            )
            if result.stdout.strip():
                typer.echo("        Warning: you have uncommitted changes in the DeathStar repo.")
                if not yes and not typer.confirm("        Continue anyway?"):
                    raise typer.Exit(code=1)
        except subprocess.CalledProcessError:
            typer.echo("        Warning: could not check git status.", err=True)

        # Step 1b: Pull latest
        typer.echo("  [2/6] Pulling latest changes...")
        has_upstream = False
        try:
            subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
                cwd=str(config.project_root),
                capture_output=True,
                text=True,
                check=True,
            )
            has_upstream = True
        except subprocess.CalledProcessError:
            pass

        if not has_upstream:
            typer.echo("        No remote tracking branch — skipping pull.")
        else:
            try:
                result = subprocess.run(
                    ["git", "pull", "--ff-only"],
                    cwd=str(config.project_root),
                    capture_output=True,
                    text=True,
                    check=True,
                )
                pull_output = result.stdout.strip()
                if "Already up to date" in pull_output:
                    typer.echo("        Already up to date.")
                else:
                    typer.echo(f"        {pull_output.splitlines()[-1] if pull_output else 'Updated.'}")
            except subprocess.CalledProcessError as exc:
                stderr = (exc.stderr or "").strip()
                typer.echo(f"        git pull failed: {stderr[:200]}", err=True)
                typer.echo("        Tip: commit or stash local changes, or pull manually.", err=True)
                raise typer.Exit(code=1) from exc

        # Step 1c: Reinstall editable package
        typer.echo("  [3/6] Upgrading local CLI package...")
        if installer == "uv":
            install_cmd = ["uv", "pip", "install", "-e", ".[dev]"]
        else:
            install_cmd = ["pip", "install", "-e", ".[dev]"]

        try:
            subprocess.run(
                install_cmd,
                cwd=str(config.project_root),
                capture_output=True,
                text=True,
                check=True,
            )
            typer.echo(f"        Reinstalled via {installer}.")
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            typer.echo(f"        Warning: package install failed: {stderr[:200]}", err=True)
            if not yes and not typer.confirm("        Continue with deploy anyway?"):
                raise typer.Exit(code=1) from exc
    else:
        # PyPI install — upgrade from the registry
        typer.echo("  [1/6] PyPI install detected.")
        typer.echo("  [2/6] Upgrading from PyPI...")
        if installer == "uv":
            upgrade_cmd = ["uv", "tool", "upgrade", "deathstar-ai"]
        else:
            upgrade_cmd = ["pip", "install", "--upgrade", "deathstar-ai"]

        try:
            result = subprocess.run(
                upgrade_cmd,
                capture_output=True,
                text=True,
                check=True,
            )
            output = result.stdout.strip()
            if "Already" in output or "Nothing to upgrade" in output:
                typer.echo("        Already on latest version.")
            else:
                typer.echo(f"        {output.splitlines()[-1] if output else 'Upgraded.'}")
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            typer.echo(f"        Warning: upgrade failed: {stderr[:200]}", err=True)
            if not yes and not typer.confirm("        Continue with deploy anyway?"):
                raise typer.Exit(code=1) from exc
        typer.echo("  [3/6] Skipping (PyPI install).")

    # Version comparison
    typer.echo("        Checking versions...")
    local_ver = full_version()
    typer.echo(f"        Local:  {local_ver}")

    remote_ver = None
    try:
        client = RemoteAPIClient(
            config,
            effective_region,
            transport=_validate_transport(transport if transport != "auto" else config.remote_transport),
        )
        health = client._request("GET", "/v1/health")
        remote_ver = health.get("version", "unknown")
        typer.echo(f"        Remote: {remote_ver}")
    except (RuntimeError, httpx.HTTPError):
        typer.echo("        Remote: unreachable (new deploy or instance down)")

    if remote_ver and remote_ver == local_ver:
        typer.echo("        Versions match — no upgrade needed.")
        if not yes and not typer.confirm("        Redeploy anyway?"):
            raise typer.Exit(0)

    # Backup
    if not skip_backup and remote_ver:
        typer.echo("  [4/6] Creating pre-upgrade backup...")
        try:
            client = RemoteAPIClient(
                config,
                effective_region,
                transport=_validate_transport(transport if transport != "auto" else config.remote_transport),
            )
            backup_response = client.backup(BackupRequest(label="pre-upgrade"))
            typer.echo(f"        Backup: {backup_response.backup_id}")
        except (RuntimeError, httpx.HTTPError) as exc:
            typer.echo(f"        Warning: backup failed: {exc}", err=True)
            if not yes and not typer.confirm("        Continue without backup?"):
                raise typer.Exit(code=1) from exc
    else:
        typer.echo("  [4/6] Skipping backup.")

    # Build locally and push to instance
    _build_and_push_image(config, effective_region)


@app.command()
def destroy(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    yes: bool = typer.Option(False, "--yes", help="Skip interactive confirmation."),
) -> None:
    config = _config()
    effective_region = region or config.region

    terraform_init(config, effective_region)

    if not yes and not typer.confirm(
        f"Destroy DeathStar resources in {effective_region}? Backup buckets may be retained."
    ):
        raise typer.Exit(code=1)

    terraform_destroy(config, effective_region, auto_approve=yes)


@app.command(name="trench-run")
def trench_run(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
) -> None:
    """Fire the proton torpedoes. Destroy ALL DeathStar resources: infrastructure,
    SSM secrets, Terraform state, and local state files. Nothing survives.

    You must type the project name to confirm. There is no --yes flag.
    """
    config = _config()
    effective_region = region or config.region

    typer.echo("")
    typer.echo("  ╔══════════════════════════════════════════════════════════════╗")
    typer.echo("  ║                                                              ║")
    typer.echo("  ║   The target area is only two meters wide. It's a small      ║")
    typer.echo("  ║   thermal exhaust port, right below the main port.           ║")
    typer.echo("  ║                                                              ║")
    typer.echo("  ║   This will destroy EVERYTHING:                              ║")
    typer.echo("  ║                                                              ║")
    typer.echo("  ║     • EC2 instance, VPC, security groups, IAM roles          ║")
    typer.echo("  ║     • All SSM Parameter Store secrets                        ║")
    typer.echo("  ║     • S3 backup bucket (if created)                          ║")
    typer.echo("  ║     • Terraform state files                                  ║")
    typer.echo("  ║     • Local .terraform directory                             ║")
    typer.echo("  ║                                                              ║")
    typer.echo("  ║   The workspace volume and all data on it will be lost.      ║")
    typer.echo("  ║                                                              ║")
    typer.echo("  ╚══════════════════════════════════════════════════════════════╝")
    typer.echo("")

    confirmation = input(
        f'  Type "{config.project_name}" to fire the proton torpedoes: '
    ).strip()
    if confirmation != config.project_name:
        typer.echo("  Abort. The Death Star lives another day.")
        raise typer.Exit(code=1)

    typer.echo("")
    typer.echo("  🎯 Stay on target...")
    typer.echo("")

    # Phase 1: Terraform destroy (infra + buckets)
    typer.echo("  [1/4] Destroying infrastructure (terraform destroy)...")
    try:
        terraform_init(config, effective_region)
        terraform_destroy(config, effective_region, auto_approve=True)
        typer.echo("        Infrastructure destroyed.")
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        typer.echo(f"        Warning: terraform destroy failed: {exc}", err=True)
        typer.echo("        Continuing with remaining cleanup...", err=True)

    # Phase 2: Delete SSM secrets
    typer.echo("  [2/4] Deleting SSM secrets...")
    ssm_params = [
        config.openai_parameter_name,
        config.anthropic_parameter_name,
        config.google_parameter_name,
        config.vertex_parameter_name,
        config.github_parameter_name,
        config.tailscale_auth_parameter_name,
    ]
    _delete_ssm_parameters(config, effective_region, ssm_params)

    # Phase 3: Clean Terraform state
    typer.echo("  [3/4] Cleaning Terraform state files...")
    _clean_terraform_state(config)

    # Phase 4: Clean local state
    typer.echo("  [4/4] Cleaning local Terraform directory...")
    _clean_local_terraform(config)

    typer.echo("")
    typer.echo("  💥 That's impossible, even for a computer!")
    typer.echo("     It's not impossible. I used to bullseye womp rats")
    typer.echo("     in my T-16 back home.")
    typer.echo("")
    typer.echo(f"  All DeathStar resources in {effective_region} have been destroyed.")
    typer.echo("  The galaxy is free. May the Force be with you.")
    typer.echo("")


def _delete_ssm_parameters(
    config: CLIConfig, region: str, parameter_names: list[str]
) -> None:
    from botocore.exceptions import ClientError, ProfileNotFound

    session_kwargs: dict[str, str] = {"region_name": region}
    if config.aws_profile:
        session_kwargs["profile_name"] = config.aws_profile

    try:
        session = boto3.Session(**session_kwargs)
    except ProfileNotFound as exc:
        typer.echo(f"        Warning: AWS profile not found: {exc}", err=True)
        return

    ssm = session.client("ssm")
    for name in parameter_names:
        try:
            ssm.delete_parameter(Name=name)
            typer.echo(f"        Deleted: {name}")
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "ParameterNotFound":
                typer.echo(f"        Not found (skip): {name}")
            else:
                typer.echo(f"        Warning: failed to delete {name}: {exc}", err=True)


def _clean_terraform_state(config: CLIConfig) -> None:
    state_files = [
        config.terraform_dir / "terraform.tfstate",
        config.terraform_dir / "terraform.tfstate.backup",
    ]
    for path in state_files:
        if path.exists():
            path.unlink()
            typer.echo(f"        Removed: {path.name}")


def _clean_local_terraform(config: CLIConfig) -> None:
    import shutil as _shutil

    tf_dir = config.terraform_dir / ".terraform"
    if tf_dir.is_dir():
        _shutil.rmtree(tf_dir)
        typer.echo("        Removed: .terraform/")

    lock_file = config.terraform_dir / ".terraform.lock.hcl"
    if lock_file.exists():
        lock_file.unlink()
        typer.echo("        Removed: .terraform.lock.hcl")


@app.command()
def connect(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    transport: Literal["auto", "tailscale", "ssm"] = typer.Option("auto", "--transport"),
) -> None:
    config = _config()
    effective_region = region or config.region
    outputs = terraform_outputs(config, effective_region)
    resolved_transport = _validate_transport(transport if transport != "auto" else config.connect_transport)

    if resolved_transport == "auto":
        resolved_transport = "tailscale" if outputs.get("tailscale_enabled") else "ssm"

    if resolved_transport == "tailscale":
        if not outputs.get("tailscale_enabled"):
            raise typer.BadParameter(
                "this deployment does not have Tailscale enabled; use --transport ssm or redeploy with Tailscale"
            )
        try:
            connect_via_tailscale(
                str(outputs.get("tailscale_hostname") or config.tailscale_hostname),
                str(outputs.get("ssh_user", "ubuntu")),
            )
            return
        except (subprocess.CalledProcessError, RuntimeError):
            typer.echo("  Tailscale SSH failed — falling back to SSM...", err=True)

    start_shell_session(config, effective_region, str(outputs["instance_id"]))


@app.command()
def status(
    region: str | None = typer.Option(None, "--region"),
    transport: Literal["auto", "tailscale", "ssm"] = typer.Option("auto", "--transport"),
    output: str = typer.Option("text", "--output"),
) -> None:
    config = _config()
    response = RemoteAPIClient(
        config,
        region or config.region,
        transport=_validate_transport(transport if transport != "auto" else config.remote_transport),
    ).status()
    emit_status(response, validate_output_format(output))


@app.command()
def logs(
    tail: int = typer.Option(200, "--tail"),
    region: str | None = typer.Option(None, "--region"),
    transport: Literal["auto", "tailscale", "ssm"] = typer.Option("auto", "--transport"),
    output: str = typer.Option("text", "--output"),
) -> None:
    config = _config()
    response = RemoteAPIClient(
        config,
        region or config.region,
        transport=_validate_transport(transport if transport != "auto" else config.remote_transport),
    ).logs(tail=tail)
    emit_logs(response, validate_output_format(output))


@app.command()
def backup(
    label: str | None = typer.Option(None, "--label"),
    region: str | None = typer.Option(None, "--region"),
    transport: Literal["auto", "tailscale", "ssm"] = typer.Option("auto", "--transport"),
    output: str = typer.Option("text", "--output"),
) -> None:
    config = _config()
    response = RemoteAPIClient(
        config,
        region or config.region,
        transport=_validate_transport(transport if transport != "auto" else config.remote_transport),
    ).backup(BackupRequest(label=label))
    emit_backup(response, validate_output_format(output))


@app.command()
def restore(
    backup_id: str | None = typer.Option(None, "--backup-id"),
    region: str | None = typer.Option(None, "--region"),
    transport: Literal["auto", "tailscale", "ssm"] = typer.Option("auto", "--transport"),
    output: str = typer.Option("text", "--output"),
) -> None:
    config = _config()
    response = RemoteAPIClient(
        config,
        region or config.region,
        transport=_validate_transport(transport if transport != "auto" else config.remote_transport),
    ).restore(RestoreRequest(backup_id=backup_id))
    emit_restore(response, validate_output_format(output))


def _run_remote_command(
    config: CLIConfig,
    region: str | None,
    *,
    transport: str,
    command: str,
) -> str:
    effective_region = region or config.region
    outputs = terraform_outputs(config, effective_region)
    resolved_transport = _validate_transport(transport if transport != "auto" else config.connect_transport)

    if resolved_transport == "auto":
        resolved_transport = "tailscale" if outputs.get("tailscale_enabled") else "ssm"

    if resolved_transport == "tailscale":
        if not outputs.get("tailscale_enabled"):
            raise typer.BadParameter(
                "this deployment does not have Tailscale enabled; use --transport ssm"
            )
        hostname = str(outputs.get("tailscale_hostname") or config.tailscale_hostname)
        ssh_user = str(outputs.get("ssh_user", "ubuntu"))
        return run_via_tailscale(hostname, ssh_user, command)

    return run_via_ssm(config, effective_region, str(outputs["instance_id"]), command)


@repos_app.command("list")
def repos_list(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    transport: Literal["auto", "tailscale", "ssm"] = typer.Option("auto", "--transport"),
) -> None:
    """List repositories in /workspace/projects on the remote instance."""
    config = _config()
    output = _run_remote_command(
        config,
        region,
        transport=transport,
        command="ls -1 /workspace/projects 2>/dev/null || echo '(empty)'",
    )
    typer.echo(output.strip() if output.strip() else "(no repos found)")


@repos_app.command("clone")
def repos_clone(
    repo: str = typer.Argument(..., help="GitHub repo to clone (owner/repo or URL)."),
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    transport: Literal["auto", "tailscale", "ssm"] = typer.Option("auto", "--transport"),
) -> None:
    """Clone a GitHub repository into /workspace/projects on the remote instance."""
    if not _SAFE_REPO_RE.match(repo):
        raise typer.BadParameter(
            "repo must be owner/name or a GitHub URL (no shell metacharacters)"
        )

    config = _config()
    output = _run_remote_command(
        config,
        region,
        transport=transport,
        command=f"cd /workspace/projects && gh repo clone '{repo}'",
    )
    typer.echo(output.strip())


def run_cli() -> None:
    try:
        app()
    except (RuntimeError, subprocess.CalledProcessError, httpx.HTTPError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
