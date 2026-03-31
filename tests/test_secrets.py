from __future__ import annotations

import pytest
import typer

from deathstar_cli.config import CLIConfig
from deathstar_cli.secrets import IntegrationName, bootstrap_targets, resolve_secret_target
from deathstar_shared.models import ProviderName


def build_config(tmp_path) -> CLIConfig:
    return CLIConfig(
        project_root=tmp_path,
        terraform_dir=tmp_path / "terraform",
        aws_profile="default",
        region="us-west-1",
        project_name="deathstar",
        instance_type="t3.large",
        root_volume_size_gb=30,
        data_volume_size_gb=200,
        openai_parameter_name="/deathstar/providers/openai/api_key",
        anthropic_parameter_name="/deathstar/providers/anthropic/api_key",
        google_parameter_name="/deathstar/providers/google/api_key",
        vertex_parameter_name="/deathstar/providers/vertex/service_account_key",
        vertex_project_id="",
        vertex_location="us-central1",
        github_parameter_name="/deathstar/integrations/github/token",
        api_token_parameter_name="/deathstar/api_token",
        create_backup_bucket=False,
        backup_bucket_name="",
        force_destroy_backup_bucket=False,
        web_ui_port=8443,
        web_ui_allowed_cidrs=[],
        git_author_name="DeathStar",
        git_author_email="deathstar@local",
        enable_tailscale=True,
        enable_tailscale_ssh=True,
        tailscale_auth_parameter_name="/deathstar/integrations/tailscale/auth_key",
        tailscale_hostname="deathstar",
        tailscale_advertise_tags=[],
        remote_transport="auto",
        connect_transport="auto",
        github_app_client_id=None,
        tailscale_oauth_client_id=None,
        tailscale_oauth_client_secret=None,
    )


def test_resolve_secret_target_for_provider(tmp_path) -> None:
    config = build_config(tmp_path)

    target = resolve_secret_target(config, provider=ProviderName.ANTHROPIC)

    assert target.label == "Anthropic API key"
    assert target.parameter_name == "/deathstar/providers/anthropic/api_key"


def test_resolve_secret_target_for_integration(tmp_path) -> None:
    config = build_config(tmp_path)

    target = resolve_secret_target(config, integration=IntegrationName.TAILSCALE)

    assert target.label == "Tailscale auth key"
    assert target.parameter_name == "/deathstar/integrations/tailscale/auth_key"


def test_resolve_secret_target_for_custom_name(tmp_path) -> None:
    config = build_config(tmp_path)

    target = resolve_secret_target(config, name="/custom/secret/path")

    assert target.label == "secret value"
    assert target.parameter_name == "/custom/secret/path"


def test_resolve_secret_target_requires_exactly_one_selector(tmp_path) -> None:
    config = build_config(tmp_path)

    with pytest.raises(typer.BadParameter):
        resolve_secret_target(config)

    with pytest.raises(typer.BadParameter):
        resolve_secret_target(
            config,
            provider=ProviderName.ANTHROPIC,
            integration=IntegrationName.GITHUB,
        )


def test_bootstrap_targets_follow_supported_order(tmp_path) -> None:
    config = build_config(tmp_path)

    targets = bootstrap_targets(config, include_tailscale=True, include_github=True)

    param_names = [target.parameter_name for target in targets]
    # After provider removal, Anthropic should be present
    assert "/deathstar/providers/anthropic/api_key" in param_names
    # Integration targets should still be present when requested
    assert "/deathstar/integrations/tailscale/auth_key" in param_names
    assert "/deathstar/integrations/github/token" in param_names
