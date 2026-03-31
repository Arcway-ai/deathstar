from __future__ import annotations

import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_server.services.backup import BackupService, _normalize_label, _safe_extract
from deathstar_shared.models import ErrorCode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        workspace_root=tmp_path / "workspace",
        projects_root=tmp_path / "workspace" / "projects",
        log_path=tmp_path / "workspace" / "logs" / "control-api.log",
        backup_directory=tmp_path / "workspace" / "backups",
        backup_bucket=None,
        backup_s3_prefix="workspace-backups",
        aws_region="us-west-1",
        log_level="INFO",
        github_token=None,
        tailscale_enabled=False,
        tailscale_hostname=None,
        ssh_user="ubuntu",
        api_token=None,
    )


def _create_project_file(projects_root: Path, name: str = "hello.py", content: str = "print('hi')") -> Path:
    projects_root.mkdir(parents=True, exist_ok=True)
    f = projects_root / name
    f.write_text(content)
    return f


# ---------------------------------------------------------------------------
# create_backup
# ---------------------------------------------------------------------------

class TestCreateBackup:
    @patch("deathstar_server.services.backup.boto3")
    def test_creates_tar_gz_locally(self, mock_boto3, tmp_path):
        settings = _make_settings(tmp_path)
        _create_project_file(settings.projects_root)
        mock_boto3.client.return_value = MagicMock()

        service = BackupService(settings)
        result = service.create_backup(label="test")

        assert result.backup_id.endswith(".tar.gz")
        assert "test" in result.backup_id
        assert Path(result.local_path).exists()
        assert result.s3_uri is None

    @patch("deathstar_server.services.backup.boto3")
    def test_uploads_to_s3_when_bucket_configured(self, mock_boto3, tmp_path):
        settings_dict = _make_settings(tmp_path).__dict__
        settings_dict = {**settings_dict, "backup_bucket": "my-bucket"}
        settings = Settings(**settings_dict)
        _create_project_file(settings.projects_root)

        mock_s3 = MagicMock()
        mock_boto3.client.return_value = mock_s3

        service = BackupService(settings)
        result = service.create_backup(label="snapshot")

        assert result.s3_uri is not None
        assert "my-bucket" in result.s3_uri
        mock_s3.upload_file.assert_called_once()

    @patch("deathstar_server.services.backup.boto3")
    def test_backup_without_label(self, mock_boto3, tmp_path):
        settings = _make_settings(tmp_path)
        _create_project_file(settings.projects_root)
        mock_boto3.client.return_value = MagicMock()

        service = BackupService(settings)
        result = service.create_backup(label=None)

        assert "backup" in result.backup_id


# ---------------------------------------------------------------------------
# restore
# ---------------------------------------------------------------------------

class TestRestore:
    @patch("deathstar_server.services.backup.boto3")
    def test_restores_from_local_backup(self, mock_boto3, tmp_path):
        settings = _make_settings(tmp_path)
        _create_project_file(settings.projects_root, "original.py", "original content")
        mock_boto3.client.return_value = MagicMock()

        service = BackupService(settings)

        # Create a backup first
        backup_result = service.create_backup(label="restore-test")

        # Modify the project file
        (settings.projects_root / "original.py").write_text("modified content")

        # Restore
        restore_result = service.restore(backup_result.backup_id)

        assert restore_result.backup_id == backup_result.backup_id
        assert restore_result.projects_root == str(settings.projects_root)

    @patch("deathstar_server.services.backup.boto3")
    def test_restore_latest_when_no_id(self, mock_boto3, tmp_path):
        settings = _make_settings(tmp_path)
        _create_project_file(settings.projects_root)
        mock_boto3.client.return_value = MagicMock()

        service = BackupService(settings)
        backup_result = service.create_backup(label="latest-test")

        restore_result = service.restore(backup_id=None)
        assert restore_result.backup_id == backup_result.backup_id

    @patch("deathstar_server.services.backup.boto3")
    def test_restore_not_found_raises(self, mock_boto3, tmp_path):
        settings = _make_settings(tmp_path)
        settings.projects_root.mkdir(parents=True, exist_ok=True)
        mock_boto3.client.return_value = MagicMock()

        service = BackupService(settings)

        with pytest.raises(AppError) as exc_info:
            service.restore(backup_id="nonexistent.tar.gz")
        assert exc_info.value.code == ErrorCode.BACKUP_NOT_FOUND

    @patch("deathstar_server.services.backup.boto3")
    def test_restore_no_backups_available(self, mock_boto3, tmp_path):
        settings = _make_settings(tmp_path)
        settings.projects_root.mkdir(parents=True, exist_ok=True)
        mock_boto3.client.return_value = MagicMock()

        service = BackupService(settings)

        with pytest.raises(AppError) as exc_info:
            service.restore(backup_id=None)
        assert exc_info.value.code == ErrorCode.BACKUP_NOT_FOUND


# ---------------------------------------------------------------------------
# _safe_extract
# ---------------------------------------------------------------------------

class TestSafeExtract:
    def test_rejects_symlinks(self, tmp_path):
        archive_path = tmp_path / "test.tar.gz"
        target_dir = tmp_path / "target"
        target_dir.mkdir()

        with tarfile.open(archive_path, "w:gz") as archive:
            info = tarfile.TarInfo(name="link.txt")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            archive.addfile(info)

        with tarfile.open(archive_path, "r:gz") as archive:
            with pytest.raises(AppError) as exc_info:
                _safe_extract(archive, target_dir)
            assert exc_info.value.code == ErrorCode.INVALID_REQUEST
            assert "symlink" in exc_info.value.message

    def test_rejects_path_traversal(self, tmp_path):
        archive_path = tmp_path / "test.tar.gz"
        target_dir = tmp_path / "target"
        target_dir.mkdir()

        with tarfile.open(archive_path, "w:gz") as archive:
            info = tarfile.TarInfo(name="../../../etc/passwd")
            info.size = 5
            import io
            archive.addfile(info, io.BytesIO(b"hello"))

        with tarfile.open(archive_path, "r:gz") as archive:
            with pytest.raises(AppError) as exc_info:
                _safe_extract(archive, target_dir)
            assert exc_info.value.code == ErrorCode.INVALID_REQUEST
            assert "outside destination" in exc_info.value.message

    def test_rejects_hard_links(self, tmp_path):
        archive_path = tmp_path / "test.tar.gz"
        target_dir = tmp_path / "target"
        target_dir.mkdir()

        with tarfile.open(archive_path, "w:gz") as archive:
            info = tarfile.TarInfo(name="hardlink.txt")
            info.type = tarfile.LNKTYPE
            info.linkname = "/etc/shadow"
            archive.addfile(info)

        with tarfile.open(archive_path, "r:gz") as archive:
            with pytest.raises(AppError) as exc_info:
                _safe_extract(archive, target_dir)
            assert "symlink or hard link" in exc_info.value.message

    def test_extracts_safe_archive(self, tmp_path):
        archive_path = tmp_path / "test.tar.gz"
        target_dir = tmp_path / "target"
        target_dir.mkdir()
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        (source_dir / "hello.txt").write_text("hello world")

        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(source_dir / "hello.txt", arcname="hello.txt")

        with tarfile.open(archive_path, "r:gz") as archive:
            _safe_extract(archive, target_dir)

        assert (target_dir / "hello.txt").read_text() == "hello world"


# ---------------------------------------------------------------------------
# latest_log_lines
# ---------------------------------------------------------------------------

class TestLatestLogLines:
    @patch("deathstar_server.services.backup.boto3")
    def test_reads_last_n_lines(self, mock_boto3, tmp_path):
        settings = _make_settings(tmp_path)
        settings.projects_root.mkdir(parents=True, exist_ok=True)
        settings.log_path.parent.mkdir(parents=True, exist_ok=True)
        settings.log_path.write_text("line1\nline2\nline3\nline4\nline5\n")
        mock_boto3.client.return_value = MagicMock()

        service = BackupService(settings)
        lines = service.latest_log_lines(tail=3)

        assert len(lines) == 3
        assert lines == ["line3", "line4", "line5"]

    @patch("deathstar_server.services.backup.boto3")
    def test_returns_empty_when_no_log_file(self, mock_boto3, tmp_path):
        settings = _make_settings(tmp_path)
        settings.projects_root.mkdir(parents=True, exist_ok=True)
        mock_boto3.client.return_value = MagicMock()

        service = BackupService(settings)
        lines = service.latest_log_lines(tail=10)

        assert lines == []

    @patch("deathstar_server.services.backup.boto3")
    def test_returns_all_lines_when_fewer_than_tail(self, mock_boto3, tmp_path):
        settings = _make_settings(tmp_path)
        settings.projects_root.mkdir(parents=True, exist_ok=True)
        settings.log_path.parent.mkdir(parents=True, exist_ok=True)
        settings.log_path.write_text("line1\nline2\n")
        mock_boto3.client.return_value = MagicMock()

        service = BackupService(settings)
        lines = service.latest_log_lines(tail=100)

        assert len(lines) == 2


# ---------------------------------------------------------------------------
# _normalize_label
# ---------------------------------------------------------------------------

class TestNormalizeLabel:
    def test_none_returns_backup(self):
        assert _normalize_label(None) == "backup"

    def test_empty_returns_backup(self):
        assert _normalize_label("") == "backup"

    def test_whitespace_only_returns_backup(self):
        assert _normalize_label("   ") == "backup"

    def test_special_characters_replaced(self):
        result = _normalize_label("My Backup! @v1.0")
        assert result == "my-backup-v1.0"

    def test_preserves_hyphens_dots_underscores(self):
        result = _normalize_label("my-backup_v1.0")
        assert result == "my-backup_v1.0"

    def test_leading_trailing_hyphens_stripped(self):
        result = _normalize_label("---test---")
        assert result == "test"

    def test_only_special_chars_returns_backup(self):
        result = _normalize_label("!@#$%")
        assert result == "backup"
