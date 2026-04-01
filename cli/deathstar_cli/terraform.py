from __future__ import annotations

import json
import os
import shutil
import subprocess

from deathstar_cli.config import CLIConfig


def ensure_binary(name: str) -> None:
    if shutil.which(name):
        return
    raise RuntimeError(f"required binary not found: {name}")


def _terraform_env(config: CLIConfig, region: str) -> dict[str, str]:
    env = os.environ.copy()
    env["AWS_REGION"] = region
    env["AWS_DEFAULT_REGION"] = region
    if config.aws_profile:
        env["AWS_PROFILE"] = config.aws_profile
    return env


def _build_var_flags(config: CLIConfig, region: str) -> list[str]:
    flags = [
        f"-var=aws_region={region}",
        f"-var=project_name={config.project_name}",
        f"-var=instance_type={config.instance_type}",
        f"-var=root_volume_size_gb={config.root_volume_size_gb}",
        f"-var=data_volume_size_gb={config.data_volume_size_gb}",
        f"-var=openai_api_key_parameter_name={config.openai_parameter_name}",
        f"-var=anthropic_api_key_parameter_name={config.anthropic_parameter_name}",
        f"-var=google_api_key_parameter_name={config.google_parameter_name}",
        f"-var=vertex_service_account_key_parameter_name={config.vertex_parameter_name}",
        f"-var=vertex_project_id={config.vertex_project_id}",
        f"-var=vertex_location={config.vertex_location}",
        f"-var=github_token_parameter_name={config.github_parameter_name}",
        f"-var=api_token_parameter_name={config.api_token_parameter_name}",
        f"-var=create_backup_bucket={str(config.create_backup_bucket).lower()}",
        f"-var=backup_bucket_name={config.backup_bucket_name}",
        f"-var=force_destroy_backup_bucket={str(config.force_destroy_backup_bucket).lower()}",
        "-var=enable_web_ui=true",
        f"-var=web_ui_port={config.web_ui_port}",
        f"-var=git_author_name={config.git_author_name}",
        f"-var=git_author_email={config.git_author_email}",
        f"-var=enable_tailscale={str(config.enable_tailscale).lower()}",
        f"-var=enable_tailscale_ssh={str(config.enable_tailscale_ssh).lower()}",
        f"-var=tailscale_auth_key_parameter_name={config.tailscale_auth_parameter_name}",
        f"-var=tailscale_hostname={config.tailscale_hostname}",
    ]

    if config.web_ui_allowed_cidrs:
        quoted = ",".join(f'"{cidr}"' for cidr in config.web_ui_allowed_cidrs)
        flags.append(f"-var=web_ui_allowed_cidrs=[{quoted}]")

    if config.tailscale_advertise_tags:
        quoted = ",".join(f'"{tag}"' for tag in config.tailscale_advertise_tags)
        flags.append(f"-var=tailscale_advertise_tags=[{quoted}]")

    return flags


def _run(
    config: CLIConfig,
    region: str,
    command: list[str],
    capture_output: bool = False,
    quiet: bool = False,
) -> subprocess.CompletedProcess[str]:
    ensure_binary("terraform")

    if quiet and not capture_output:
        # Suppress stdout but let errors through
        result = subprocess.run(
            command,
            cwd=config.terraform_dir,
            env=_terraform_env(config, region),
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            # Show the full output on failure so the user can debug
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr)
            result.check_returncode()
        return result

    return subprocess.run(
        command,
        cwd=config.terraform_dir,
        env=_terraform_env(config, region),
        check=True,
        text=True,
        capture_output=capture_output,
    )


def terraform_init(config: CLIConfig, region: str, quiet: bool = False) -> None:
    _run(config, region, ["terraform", "init", "-input=false"], quiet=quiet)


def terraform_apply(
    config: CLIConfig,
    region: str,
    auto_approve: bool,
    targets: list[str] | None = None,
    quiet: bool = False,
) -> None:
    command = ["terraform", "apply", "-input=false", *_build_var_flags(config, region)]
    if auto_approve:
        command.insert(2, "-auto-approve")
    if targets:
        for t in targets:
            command.append(f"-target={t}")
    _run(config, region, command, quiet=quiet)


def terraform_destroy(config: CLIConfig, region: str, auto_approve: bool) -> None:
    command = ["terraform", "destroy", "-input=false", *_build_var_flags(config, region)]
    if auto_approve:
        command.insert(2, "-auto-approve")
    _run(config, region, command)


def terraform_outputs(config: CLIConfig, region: str) -> dict[str, object]:
    completed = _run(
        config,
        region,
        ["terraform", "output", "-json"],
        capture_output=True,
    )
    payload = json.loads(completed.stdout)
    return {key: value["value"] for key, value in payload.items()}
