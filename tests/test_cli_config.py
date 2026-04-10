from __future__ import annotations


import pytest

from deathstar_cli.config import CLIConfig, _parse_bool, _parse_csv, find_project_root


# ---------------------------------------------------------------------------
# _parse_bool
# ---------------------------------------------------------------------------

class TestParseBool:
    def test_true_values(self):
        assert _parse_bool("1") is True
        assert _parse_bool("true") is True
        assert _parse_bool("True") is True
        assert _parse_bool("TRUE") is True
        assert _parse_bool("yes") is True
        assert _parse_bool("Yes") is True
        assert _parse_bool("on") is True
        assert _parse_bool("ON") is True

    def test_false_values(self):
        assert _parse_bool("0") is False
        assert _parse_bool("false") is False
        assert _parse_bool("False") is False
        assert _parse_bool("no") is False
        assert _parse_bool("off") is False
        assert _parse_bool("anything") is False
        assert _parse_bool("") is False

    def test_none_returns_default(self):
        assert _parse_bool(None) is False
        assert _parse_bool(None, default=True) is True
        assert _parse_bool(None, default=False) is False

    def test_whitespace_stripped(self):
        assert _parse_bool("  true  ") is True
        assert _parse_bool("  1  ") is True


# ---------------------------------------------------------------------------
# _parse_csv
# ---------------------------------------------------------------------------

class TestParseCsv:
    def test_basic_csv(self):
        assert _parse_csv("a,b,c") == ["a", "b", "c"]

    def test_strips_whitespace(self):
        assert _parse_csv("  a , b , c  ") == ["a", "b", "c"]

    def test_empty_string(self):
        assert _parse_csv("") == []

    def test_none_value(self):
        assert _parse_csv(None) == []

    def test_single_value(self):
        assert _parse_csv("single") == ["single"]

    def test_empty_items_filtered(self):
        assert _parse_csv("a,,b,,,c") == ["a", "b", "c"]

    def test_only_commas(self):
        assert _parse_csv(",,,") == []


# ---------------------------------------------------------------------------
# find_project_root
# ---------------------------------------------------------------------------

class TestFindProjectRoot:
    def test_finds_root(self, tmp_path):
        # Create the marker files/dirs
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'deathstar'\n")
        (tmp_path / "terraform" / "environments" / "aws-ec2").mkdir(parents=True)

        root = find_project_root(start=tmp_path)
        assert root == tmp_path

    def test_finds_root_from_subdirectory(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'deathstar'\n")
        (tmp_path / "terraform" / "environments" / "aws-ec2").mkdir(parents=True)
        subdir = tmp_path / "cli" / "deathstar_cli"
        subdir.mkdir(parents=True)

        root = find_project_root(start=subdir)
        assert root == tmp_path

    def test_errors_when_not_found(self, tmp_path):
        # Empty directory, no markers
        with pytest.raises(RuntimeError, match="unable to locate"):
            find_project_root(start=tmp_path)


# ---------------------------------------------------------------------------
# CLIConfig.load()
# ---------------------------------------------------------------------------

class TestCLIConfigLoad:
    def test_load_with_dotenv(self, tmp_path, monkeypatch):
        # Set up project structure
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'deathstar'\n")
        (tmp_path / "terraform" / "environments" / "aws-ec2").mkdir(parents=True)

        # Create .env file
        env_content = (
            "DEATHSTAR_REGION=us-east-1\n"
            "DEATHSTAR_PROJECT_NAME=mystar\n"
            "DEATHSTAR_INSTANCE_TYPE=t3.xlarge\n"
        )
        (tmp_path / ".env").write_text(env_content)

        # Clear relevant env vars to ensure .env takes effect
        for key in [
            "DEATHSTAR_REGION",
            "DEATHSTAR_PROJECT_NAME",
            "DEATHSTAR_INSTANCE_TYPE",
            "DEATHSTAR_TERRAFORM_DIR",
        ]:
            monkeypatch.delenv(key, raising=False)

        config = CLIConfig.load(start=tmp_path)

        assert config.project_root == tmp_path
        assert config.region == "us-east-1"
        assert config.project_name == "mystar"
        assert config.instance_type == "t3.xlarge"

    def test_load_defaults(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text("[project]\nname = 'deathstar'\n")
        (tmp_path / "terraform" / "environments" / "aws-ec2").mkdir(parents=True)

        # Clear env vars that might be set
        for key in [
            "DEATHSTAR_REGION",
            "DEATHSTAR_PROJECT_NAME",
            "DEATHSTAR_INSTANCE_TYPE",
            "DEATHSTAR_TERRAFORM_DIR",
            "DEATHSTAR_AWS_PROFILE",
        ]:
            monkeypatch.delenv(key, raising=False)

        config = CLIConfig.load(start=tmp_path)

        assert config.region == "us-west-1"
        assert config.project_name == "deathstar"
        assert config.instance_type == "t3.large"
        assert config.aws_profile is None


# ---------------------------------------------------------------------------
# __post_init__ validation
# ---------------------------------------------------------------------------

class TestPostInitValidation:
    def test_rejects_invalid_project_name(self, tmp_path):
        with pytest.raises(ValueError, match="DEATHSTAR_PROJECT_NAME"):
            CLIConfig(
                project_root=tmp_path,
                terraform_dir=tmp_path / "terraform",
                aws_profile=None,
                region="us-west-1",
                project_name="invalid name!",
                instance_type="t3.large",
                root_volume_size_gb=30,
                data_volume_size_gb=200,
                openai_parameter_name="/p/openai",
                anthropic_parameter_name="/p/anthropic",
                google_parameter_name="/p/google",
                vertex_parameter_name="/p/vertex",
                vertex_project_id="",
                vertex_location="us-central1",
                github_parameter_name="/p/github",
                api_token_parameter_name="/p/api_token",
                create_backup_bucket=False,
                backup_bucket_name="",
                force_destroy_backup_bucket=False,
                web_ui_port=8443,
                web_ui_allowed_cidrs=[],
                git_author_name="DS",
                git_author_email="ds@local",
                enable_tailscale=False,
                enable_tailscale_ssh=False,
                db_password_parameter_name="/p/db_password",
                tailscale_auth_parameter_name="/p/ts",
                tailscale_hostname="ds",
                tailscale_advertise_tags=[],
                remote_transport="auto",
                connect_transport="auto",
                github_app_client_id=None,
                tailscale_oauth_client_id=None,
                linear_parameter_name="/p/linear",
                tailscale_oauth_client_secret=None,
            )

    def test_rejects_invalid_region(self, tmp_path):
        with pytest.raises(ValueError, match="DEATHSTAR_REGION"):
            CLIConfig(
                project_root=tmp_path,
                terraform_dir=tmp_path / "terraform",
                aws_profile=None,
                region="not-a-region",
                project_name="deathstar",
                instance_type="t3.large",
                root_volume_size_gb=30,
                data_volume_size_gb=200,
                openai_parameter_name="/p/openai",
                anthropic_parameter_name="/p/anthropic",
                google_parameter_name="/p/google",
                vertex_parameter_name="/p/vertex",
                vertex_project_id="",
                vertex_location="us-central1",
                github_parameter_name="/p/github",
                api_token_parameter_name="/p/api_token",
                create_backup_bucket=False,
                backup_bucket_name="",
                force_destroy_backup_bucket=False,
                web_ui_port=8443,
                web_ui_allowed_cidrs=[],
                git_author_name="DS",
                git_author_email="ds@local",
                enable_tailscale=False,
                enable_tailscale_ssh=False,
                db_password_parameter_name="/p/db_password",
                tailscale_auth_parameter_name="/p/ts",
                tailscale_hostname="ds",
                tailscale_advertise_tags=[],
                remote_transport="auto",
                connect_transport="auto",
                github_app_client_id=None,
                tailscale_oauth_client_id=None,
                linear_parameter_name="/p/linear",
                tailscale_oauth_client_secret=None,
            )

    def test_valid_project_name_with_hyphens_underscores(self, tmp_path):
        config = CLIConfig(
            project_root=tmp_path,
            terraform_dir=tmp_path / "terraform",
            aws_profile=None,
            region="us-west-2",
            project_name="my-project_v2",
            instance_type="t3.large",
            root_volume_size_gb=30,
            data_volume_size_gb=200,
            openai_parameter_name="/p/openai",
            anthropic_parameter_name="/p/anthropic",
            google_parameter_name="/p/google",
            vertex_parameter_name="/p/vertex",
            vertex_project_id="",
            vertex_location="us-central1",
            github_parameter_name="/p/github",
            api_token_parameter_name="/p/api_token",
            create_backup_bucket=False,
            backup_bucket_name="",
            force_destroy_backup_bucket=False,
            web_ui_port=8443,
            web_ui_allowed_cidrs=[],
            git_author_name="DS",
            git_author_email="ds@local",
            enable_tailscale=False,
            enable_tailscale_ssh=False,
            db_password_parameter_name="/p/db_password",
            tailscale_auth_parameter_name="/p/ts",
            tailscale_hostname="ds",
            tailscale_advertise_tags=[],
            remote_transport="auto",
            connect_transport="auto",
            github_app_client_id=None,
            tailscale_oauth_client_id=None,
            linear_parameter_name="/p/linear",
            tailscale_oauth_client_secret=None,
        )
        assert config.project_name == "my-project_v2"

    def test_valid_region_format(self, tmp_path):
        config = CLIConfig(
            project_root=tmp_path,
            terraform_dir=tmp_path / "terraform",
            aws_profile=None,
            region="eu-central-1",
            project_name="deathstar",
            instance_type="t3.large",
            root_volume_size_gb=30,
            data_volume_size_gb=200,
            openai_parameter_name="/p/openai",
            anthropic_parameter_name="/p/anthropic",
            google_parameter_name="/p/google",
            vertex_parameter_name="/p/vertex",
            vertex_project_id="",
            vertex_location="us-central1",
            github_parameter_name="/p/github",
            api_token_parameter_name="/p/api_token",
            create_backup_bucket=False,
            backup_bucket_name="",
            force_destroy_backup_bucket=False,
            web_ui_port=8443,
            web_ui_allowed_cidrs=[],
            git_author_name="DS",
            git_author_email="ds@local",
            enable_tailscale=False,
            enable_tailscale_ssh=False,
            db_password_parameter_name="/p/db_password",
            tailscale_auth_parameter_name="/p/ts",
            tailscale_hostname="ds",
            tailscale_advertise_tags=[],
            remote_transport="auto",
            connect_transport="auto",
            github_app_client_id=None,
            tailscale_oauth_client_id=None,
            linear_parameter_name="/p/linear",
            tailscale_oauth_client_secret=None,
        )
        assert config.region == "eu-central-1"
