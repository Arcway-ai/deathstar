from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3

from deathstar_server.config import Settings
from deathstar_server.errors import AppError
from deathstar_shared.models import BackupResponse, ErrorCode, RestoreResponse

logger = logging.getLogger(__name__)


class BackupService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.backup_directory.mkdir(parents=True, exist_ok=True)
        self.settings.projects_root.mkdir(parents=True, exist_ok=True)
        self.s3 = boto3.client("s3", region_name=settings.aws_region)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_backup(self, label: str | None) -> BackupResponse:
        timestamp = datetime.now(timezone.utc)
        normalized_label = _normalize_label(label)
        backup_id = f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{normalized_label}.tar.gz"
        local_path = self.settings.backup_directory / backup_id

        deathstar_dir = self.settings.workspace_root / "deathstar"

        with tarfile.open(local_path, "w:gz") as archive:
            if self._is_postgres():
                self._backup_postgres(archive, deathstar_dir)
            else:
                self._backup_sqlite(archive, deathstar_dir)

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

        # If the archive contains a pg_dump file and we're on Postgres, load it
        if self._is_postgres():
            pg_dump_path = self.settings.workspace_root / "deathstar" / "pgdump.sql"
            if pg_dump_path.exists():
                self._restore_postgres(pg_dump_path)
                pg_dump_path.unlink()  # Clean up the dump file after restore

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

    # ------------------------------------------------------------------
    # Database-specific backup/restore
    # ------------------------------------------------------------------

    def _is_postgres(self) -> bool:
        url = self.settings.database_url
        return url.startswith("postgresql://") or url.startswith("postgres://")

    def _backup_sqlite(self, archive: tarfile.TarFile, deathstar_dir: Path) -> None:
        """Back up the SQLite database file and WAL/SHM files."""
        db_path = deathstar_dir / "deathstar.db"
        if db_path.exists():
            archive.add(db_path, arcname="deathstar/deathstar.db")
        # Back up WAL/SHM files if present (for consistency)
        for suffix in ("-wal", "-shm"):
            wal_path = deathstar_dir / f"deathstar.db{suffix}"
            if wal_path.exists():
                archive.add(wal_path, arcname=f"deathstar/deathstar.db{suffix}")

    def _backup_postgres(self, archive: tarfile.TarFile, deathstar_dir: Path) -> None:
        """Run pg_dump and add the SQL dump to the archive.

        Uses a temp file to avoid collisions from concurrent backups.
        Raises AppError if pg_dump fails (CalledProcessError) so the
        caller knows the archive has no database dump.  FileNotFoundError
        (pg_dump binary missing) is a known environment limitation and
        logged as a warning.
        """
        deathstar_dir.mkdir(parents=True, exist_ok=True)
        fd, dump_path_str = tempfile.mkstemp(
            suffix=".sql", prefix="pgdump-", dir=str(deathstar_dir),
        )
        os.close(fd)
        dump_path = Path(dump_path_str)
        pg_env = self._pg_env()

        try:
            subprocess.run(
                [
                    "pg_dump",
                    "--host", pg_env["host"],
                    "--port", pg_env["port"],
                    "--username", pg_env["user"],
                    "--dbname", pg_env["dbname"],
                    "--no-owner",
                    "--no-acl",
                    "--file", str(dump_path),
                ],
                capture_output=True,
                text=True,
                check=True,
                env={**os.environ, "PGPASSWORD": pg_env["password"]},
            )
            archive.add(dump_path, arcname="deathstar/pgdump.sql")
            logger.info("pg_dump completed successfully")
        except FileNotFoundError:
            logger.warning("pg_dump not available — skipping database backup")
        except subprocess.CalledProcessError as exc:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"pg_dump failed: {(exc.stderr or '')[:500]}",
                status_code=500,
            ) from exc
        finally:
            if dump_path.exists():
                dump_path.unlink()

    def _restore_postgres(self, dump_path: Path) -> None:
        """Restore a pg_dump SQL file into the current Postgres database.

        Raises AppError on failure so the caller never returns a
        successful RestoreResponse when the database wasn't restored.
        """
        pg_env = self._pg_env()

        try:
            subprocess.run(
                [
                    "psql",
                    "--host", pg_env["host"],
                    "--port", pg_env["port"],
                    "--username", pg_env["user"],
                    "--dbname", pg_env["dbname"],
                    "--file", str(dump_path),
                    "--single-transaction",
                    "--quiet",
                ],
                capture_output=True,
                text=True,
                check=True,
                env={**os.environ, "PGPASSWORD": pg_env["password"]},
            )
            logger.info("psql restore completed successfully")
        except FileNotFoundError:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                "psql is not available — cannot restore PostgreSQL database dump",
                status_code=500,
            )
        except subprocess.CalledProcessError as exc:
            raise AppError(
                ErrorCode.INTERNAL_ERROR,
                f"database restore failed: {(exc.stderr or '')[:500]}",
                status_code=500,
            ) from exc

    def _pg_env(self) -> dict[str, str]:
        """Parse the database URL into components for pg_dump/psql."""
        parsed = urlparse(self.settings.database_url)
        return {
            "host": parsed.hostname or "localhost",
            "port": str(parsed.port or 5432),
            "user": parsed.username or "deathstar",
            "password": parsed.password or "",
            "dbname": (parsed.path or "/deathstar").lstrip("/"),
        }

    # ------------------------------------------------------------------
    # Archive resolution
    # ------------------------------------------------------------------

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
