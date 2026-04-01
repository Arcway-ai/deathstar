from __future__ import annotations

import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import re

import boto3

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_shared.models import BackupResponse, ErrorCode, RestoreResponse


class BackupService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.backup_directory.mkdir(parents=True, exist_ok=True)
        self.settings.projects_root.mkdir(parents=True, exist_ok=True)
        self.s3 = boto3.client("s3", region_name=settings.aws_region)

    def create_backup(self, label: str | None) -> BackupResponse:
        timestamp = datetime.now(timezone.utc)
        normalized_label = _normalize_label(label)
        backup_id = f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{normalized_label}.tar.gz"
        local_path = self.settings.backup_directory / backup_id

        deathstar_dir = self.settings.workspace_root / "deathstar"

        with tarfile.open(local_path, "w:gz") as archive:
            # Back up the SQLite database (conversations, memories, feedback)
            db_path = deathstar_dir / "deathstar.db"
            if db_path.exists():
                archive.add(db_path, arcname="deathstar/deathstar.db")
            # Back up WAL/SHM files if present (for consistency)
            for suffix in ("-wal", "-shm"):
                wal_path = deathstar_dir / f"deathstar.db{suffix}"
                if wal_path.exists():
                    archive.add(wal_path, arcname=f"deathstar/deathstar.db{suffix}")
            # Back up .claude config if present
            claude_dir = deathstar_dir / ".claude"
            if claude_dir.is_dir():
                archive.add(claude_dir, arcname="deathstar/.claude")

        s3_uri = None
        if self.settings.backup_bucket:
            key = f"{self.settings.backup_s3_prefix}/{backup_id}"
            self.s3.upload_file(str(local_path), self.settings.backup_bucket, key)
            s3_uri = f"s3://{self.settings.backup_bucket}/{key}"

        return BackupResponse(
            backup_id=backup_id,
            created_at=timestamp,
            local_path=str(local_path),
            s3_uri=s3_uri,
        )

    def restore(self, backup_id: str | None) -> RestoreResponse:
        local_path, restored_from, resolved_backup_id = self._resolve_backup_archive(backup_id)

        with tarfile.open(local_path, "r:gz") as archive:
            _safe_extract(archive, self.settings.workspace_root)

        return RestoreResponse(
            backup_id=resolved_backup_id,
            restored_from=restored_from,
            projects_root=str(self.settings.projects_root),
        )

    def latest_log_lines(self, tail: int) -> list[str]:
        if not self.settings.log_path.exists():
            return []
        try:
            with self.settings.log_path.open("rb") as handle:
                handle.seek(0, 2)  # seek to end
                size = handle.tell()
                # Read last 1MB or entire file, whichever is smaller
                chunk_size = min(size, 1_048_576)
                if chunk_size == 0:
                    return []
                handle.seek(-chunk_size, 2)
                data = handle.read().decode("utf-8", errors="replace")
            lines = data.splitlines()
            return [line.rstrip() for line in lines[-tail:]]
        except OSError:
            return []

    def _resolve_backup_archive(self, backup_id: str | None) -> tuple[Path, str, str]:
        if backup_id:
            local_candidate = self.settings.backup_directory / backup_id
            if local_candidate.exists():
                return local_candidate, str(local_candidate), backup_id
            if self.settings.backup_bucket:
                return self._download_from_s3(backup_id)
            raise AppError(
                ErrorCode.BACKUP_NOT_FOUND,
                f"backup {backup_id} was not found locally and no S3 bucket is configured",
                status_code=404,
            )

        local_backups = sorted(self.settings.backup_directory.glob("*.tar.gz"))
        if local_backups:
            latest = local_backups[-1]
            return latest, str(latest), latest.name

        if self.settings.backup_bucket:
            all_objects: list[dict] = []
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(
                Bucket=self.settings.backup_bucket,
                Prefix=f"{self.settings.backup_s3_prefix}/",
            ):
                all_objects.extend(page.get("Contents", []))
            if all_objects:
                latest = max(all_objects, key=lambda item: item["LastModified"])
                return self._download_from_s3(Path(latest["Key"]).name)

        raise AppError(
            ErrorCode.BACKUP_NOT_FOUND,
            "no backups are available",
            status_code=404,
        )

    def _download_from_s3(self, backup_id: str) -> tuple[Path, str, str]:
        if not self.settings.backup_bucket:
            raise AppError(
                ErrorCode.BACKUP_NOT_FOUND,
                "no backup bucket is configured",
                status_code=404,
            )

        local_path = self.settings.backup_directory / backup_id
        key = f"{self.settings.backup_s3_prefix}/{backup_id}"
        self.s3.download_file(self.settings.backup_bucket, key, str(local_path))
        return local_path, f"s3://{self.settings.backup_bucket}/{key}", backup_id


def _normalize_label(label: str | None) -> str:
    if not label:
        return "backup"
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", label).strip("-").lower()
    return normalized or "backup"


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()

    safe_members: list[tarfile.TarInfo] = []
    for member in archive.getmembers():
        if member.issym() or member.islnk():
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"refusing to extract symlink or hard link: {member.name}",
                status_code=400,
            )
        member_path = (destination / member.name).resolve()
        if not member_path.is_relative_to(destination):
            raise AppError(
                ErrorCode.INVALID_REQUEST,
                f"refusing to extract path outside destination: {member.name}",
                status_code=400,
            )
        safe_members.append(member)

    staging = Path(tempfile.mkdtemp(prefix="deathstar-restore-"))
    try:
        archive.extractall(staging, members=safe_members)
        for item in staging.iterdir():
            target = destination / item.name
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            shutil.move(str(item), str(target))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
