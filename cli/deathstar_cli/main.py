from __future__ import annotations

import re
import subprocess
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
    emit_workflow,
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
from deathstar_cli.tailscale import connect_via_tailscale, run_via_tailscale
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
    WorkflowKind,
    WorkflowRequest,
)
from deathstar_shared.version import full_version

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


@app.command()
def version() -> None:
    typer.echo(full_version())


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
    import time
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
) -> None:
    config = _config()
    effective_region = region or config.region

    terraform_init(config, effective_region)

    if not yes and not typer.confirm(f"Deploy DeathStar into {effective_region}?"):
        raise typer.Exit(code=1)

    # Clean up stale Tailscale nodes before deploy so the new instance gets a clean hostname.
    if config.enable_tailscale and config.tailscale_oauth_client_id and config.tailscale_oauth_client_secret:
        try:
            _tailscale_cleanup(yes=yes)
        except (typer.BadParameter, httpx.HTTPError):
            pass  # best-effort during deploy

    terraform_apply(config, effective_region, auto_approve=yes)
    _display_terraform_summary(effective_region)


@app.command()
def redeploy(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    yes: bool = typer.Option(False, "--yes", help="Skip interactive confirmation."),
) -> None:
    """Push code changes and rebuild the container without replacing the instance.

    Steps:
      1. terraform apply — uploads new code to S3 (instance stays)
      2. SSM restart — re-syncs code from S3 and rebuilds Docker image
    """
    config = _config()
    effective_region = region or config.region

    typer.echo("  [1/2] Uploading code to S3...")
    terraform_init(config, effective_region)
    # Only target S3 runtime files — never replace the instance on redeploy.
    terraform_apply(
        config,
        effective_region,
        auto_approve=yes,
        targets=["aws_s3_object.runtime_files"],
    )

    typer.echo("  [2/2] Blue/green deploy on instance...")
    outputs = terraform_outputs(config, effective_region)
    instance_id = str(outputs["instance_id"])

    session_kwargs: dict[str, str] = {"region_name": effective_region}
    if config.aws_profile:
        session_kwargs["profile_name"] = config.aws_profile

    ssm = boto3.Session(**session_kwargs).client("ssm")

    response = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": ["systemctl restart deathstar-runtime.service"]},
        TimeoutSeconds=300,
    )
    command_id = response["Command"]["CommandId"]

    import time  # noqa: E402 — late import is fine for a CLI command

    for _ in range(120):
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
            typer.echo("        Runtime restarted successfully.")
            break
    else:
        typer.echo("        Timed out waiting for restart.", err=True)
        raise typer.Exit(code=1)

    # Verify health
    time.sleep(5)
    try:
        client = RemoteAPIClient(
            config,
            effective_region,
            transport=_validate_transport(config.remote_transport),
        )
        health = client._request("GET", "/v1/health")
        typer.echo(f"  Redeploy complete. Version: {health.get('version', 'unknown')}")
    except (RuntimeError, httpx.HTTPError):
        typer.echo("  Redeploy complete. Instance may still be starting — run `deathstar status` in a moment.")


@app.command()
def upgrade(
    region: str | None = typer.Option(None, "--region", help="AWS region override."),
    yes: bool = typer.Option(False, "--yes", help="Skip interactive confirmations."),
    skip_backup: bool = typer.Option(False, "--skip-backup", help="Skip pre-upgrade backup."),
    transport: Literal["auto", "tailscale", "ssm"] = typer.Option("auto", "--transport"),
) -> None:
    """Pull the latest code, upgrade the CLI, back up the instance, and redeploy.

    Steps:
      1. Check for local uncommitted changes
      2. Pull latest from the current branch
      3. Reinstall the deathstar CLI package (picks up new code)
      4. Compare local vs remote version
      5. Create a backup on the remote instance (unless --skip-backup)
      6. Remove stale Tailscale devices (if OAuth credentials are configured)
      7. Run terraform apply to redeploy

    For open source users: just `deathstar upgrade`.
    """
    import shutil

    config = _config()
    effective_region = region or config.region

    # Step 1: Check for uncommitted changes in the deathstar repo
    typer.echo("  [1/7] Checking local repo state...")
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

    # Step 2: Pull latest (skip if no remote tracking branch)
    typer.echo("  [2/7] Pulling latest changes...")
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

    # Step 3: Reinstall CLI package
    typer.echo("  [3/7] Upgrading local CLI package...")
    installer = "uv" if shutil.which("uv") else "pip"
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
        typer.echo(f"        You may need to run `{installer} pip install -e '.[dev]'` manually.", err=True)
        if not yes and not typer.confirm("        Continue with deploy anyway?"):
            raise typer.Exit(code=1) from exc

    # Step 4: Version comparison
    typer.echo("  [4/7] Checking versions...")
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

    # Step 5: Backup
    if not skip_backup and remote_ver:
        typer.echo("  [5/7] Creating pre-upgrade backup...")
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
        typer.echo("  [5/7] Skipping backup.")

    # Step 6: Tailscale cleanup
    if config.enable_tailscale:
        typer.echo("  [6/7] Cleaning up Tailscale devices...")
        try:
            result = _tailscale_cleanup(yes=yes)
            if not result["deleted"] and not result["renamed"]:
                typer.echo("        Nothing to clean up.")
        except (typer.BadParameter, httpx.HTTPError) as exc:
            typer.echo(f"        Warning: Tailscale cleanup failed: {exc}", err=True)
            typer.echo("        The new instance may get a suffixed hostname (e.g. deathstar-1).", err=True)
    else:
        typer.echo("  [6/7] Tailscale not enabled — skipping cleanup.")

    # Step 7: Redeploy
    typer.echo("  [7/7] Deploying...")
    terraform_init(config, effective_region)
    terraform_apply(config, effective_region, auto_approve=yes)

    typer.echo("")
    _display_terraform_summary(effective_region)

    # Post-deploy version check
    typer.echo("")
    try:
        client = RemoteAPIClient(
            config,
            effective_region,
            transport=_validate_transport(transport if transport != "auto" else config.remote_transport),
        )
        health = client._request("GET", "/v1/health")
        typer.echo(f"  Upgrade complete. Remote version: {health.get('version', 'unknown')}")
    except (RuntimeError, httpx.HTTPError):
        typer.echo("  Deploy complete. Remote instance may still be starting up.")
        typer.echo("  Run `deathstar status` in a minute to verify.")


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
def run(
    provider: ProviderName = typer.Option(..., "--provider"),
    prompt: str = typer.Option(..., "--prompt"),
    workflow: WorkflowKind = typer.Option(WorkflowKind.PROMPT, "--workflow"),
    workspace_subpath: str = typer.Option(".", "--workspace-subpath"),
    model: str | None = typer.Option(None, "--model"),
    system: str | None = typer.Option(None, "--system"),
    timeout_seconds: int = typer.Option(180, "--timeout-seconds"),
    write: bool = typer.Option(False, "--write", help="Apply a returned patch to the remote repo."),
    base_branch: str = typer.Option("main", "--base-branch"),
    head_branch: str | None = typer.Option(None, "--head-branch"),
    open_pr: bool = typer.Option(False, "--open-pr"),
    draft_pr: bool = typer.Option(False, "--draft-pr"),
    region: str | None = typer.Option(None, "--region"),
    transport: Literal["auto", "tailscale", "ssm"] = typer.Option("auto", "--transport"),
    output: str = typer.Option("text", "--output"),
) -> None:
    config = _config()
    normalized_output = validate_output_format(output)

    if workflow != WorkflowKind.PATCH and write:
        raise typer.BadParameter("--write can only be used with --workflow patch")

    if ".." in workspace_subpath.split("/") or workspace_subpath.startswith("/"):
        raise typer.BadParameter(
            "workspace_subpath must be a relative path without '..' components"
        )

    request = WorkflowRequest(
        workflow=workflow,
        provider=provider,
        prompt=prompt,
        workspace_subpath=workspace_subpath,
        model=model,
        system=system,
        timeout_seconds=timeout_seconds,
        write_changes=write,
        base_branch=base_branch,
        head_branch=head_branch,
        open_pr=open_pr,
        draft_pr=draft_pr,
    )

    try:
        response = RemoteAPIClient(
            config,
            region or config.region,
            transport=_validate_transport(transport if transport != "auto" else config.remote_transport),
        ).run(request)
    except httpx.HTTPStatusError as exc:
        typer.echo(exc.response.text, err=True)
        raise typer.Exit(code=1) from exc

    emit_workflow(response, normalized_output)
    if response.status == "failed":
        raise typer.Exit(code=1)


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
