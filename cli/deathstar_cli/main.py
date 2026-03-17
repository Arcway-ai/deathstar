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

    terraform_apply(config, effective_region, auto_approve=yes)
    _display_terraform_summary(effective_region)


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
      6. Run terraform apply to redeploy

    For open source users: just `deathstar upgrade`.
    """
    import shutil

    config = _config()
    effective_region = region or config.region

    # Step 1: Check for uncommitted changes in the deathstar repo
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

    # Step 2: Pull latest
    typer.echo("  [2/6] Pulling latest changes...")
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
    typer.echo("  [3/6] Upgrading local CLI package...")
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
    typer.echo("  [4/6] Checking versions...")
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
        typer.echo("  [5/6] Creating pre-upgrade backup...")
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
        typer.echo("  [5/6] Skipping backup.")

    # Step 6: Redeploy
    typer.echo("  [6/6] Deploying...")
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
        connect_via_tailscale(
            str(outputs.get("tailscale_hostname") or config.tailscale_hostname),
            str(outputs.get("ssh_user", "ec2-user")),
        )
        return

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
        ssh_user = str(outputs.get("ssh_user", "ec2-user"))
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
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
