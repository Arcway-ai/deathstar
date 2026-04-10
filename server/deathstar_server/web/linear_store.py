from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from deathstar_server.db.models import LinearIssue, LinearProject

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncResult:
    """Summary of a sync_issues() call."""

    created: int
    updated: int
    deleted_ids: tuple[str, ...]


def _slugify(text: str) -> str:
    """Convert text to a URL/branch-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s_-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")[:60]


def _derive_branch_name(identifier: str, title: str) -> str:
    """Derive a git branch name from a Linear issue identifier and title.

    Example: ENG-123 "Add user auth" -> "eng-123/add-user-auth"
    """
    prefix = identifier.lower()
    slug = _slugify(title)
    return f"{prefix}/{slug}" if slug else prefix


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class LinearStore:
    """ORM layer for Linear sync state.

    Follows the ConversationStore pattern: takes an Engine, exposes
    typed synchronous methods using SQLModel sessions.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def link_project(
        self,
        *,
        repo: str,
        linear_project_id: str,
        conversation_id: str | None,
        team_id: str,
        project_data: dict,
    ) -> LinearProject:
        """Create or update a LinearProject row. Idempotent on linear_project_id."""
        now = _utcnow()
        with Session(self._engine) as session:
            stmt = select(LinearProject).where(
                LinearProject.linear_project_id == linear_project_id,
            )
            existing = session.exec(stmt).first()

            if existing:
                existing.repo = repo
                existing.conversation_id = conversation_id
                existing.linear_team_id = team_id
                existing.name = project_data.get("name", existing.name)
                existing.slug = project_data.get("slugId", existing.slug)
                existing.state = project_data.get("state", existing.state)
                existing.url = project_data.get("url", existing.url)
                existing.updated_at = now
                session.commit()
                session.refresh(existing)
                return existing

            project = LinearProject(
                id=str(uuid.uuid4()),
                repo=repo,
                conversation_id=conversation_id,
                linear_project_id=linear_project_id,
                linear_team_id=team_id,
                name=project_data.get("name", ""),
                slug=project_data.get("slugId", ""),
                state=project_data.get("state", "planned"),
                url=project_data.get("url", ""),
                last_synced_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(project)
            try:
                session.commit()
            except IntegrityError:
                # TOCTOU: a concurrent request inserted the same
                # linear_project_id between our SELECT and INSERT.
                # Fall back to reading the winner's row.
                session.rollback()
                existing = session.exec(
                    select(LinearProject).where(
                        LinearProject.linear_project_id == linear_project_id,
                    )
                ).first()
                if existing:
                    return existing
                raise
            session.refresh(project)
            return project

    def get_project_by_linear_id(self, linear_project_id: str) -> LinearProject | None:
        with Session(self._engine) as session:
            stmt = select(LinearProject).where(
                LinearProject.linear_project_id == linear_project_id,
            )
            return session.exec(stmt).first()

    def list_projects_for_repo(self, repo: str) -> list[LinearProject]:
        with Session(self._engine) as session:
            stmt = (
                select(LinearProject)
                .where(LinearProject.repo == repo)
                .order_by(LinearProject.updated_at.desc())
            )
            return list(session.exec(stmt).all())

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    def sync_issues(
        self,
        project_id: str,
        issues: list[dict],
    ) -> SyncResult:
        """Idempotent upsert of issues for a project.

        - Inserts new issues (by linear_issue_id).
        - Updates existing issues whose data changed.
        - Deletes issues no longer present in the remote list.

        Returns a SyncResult with counts.
        """
        now = _utcnow()
        created = 0
        updated = 0
        deleted_ids: list[str] = []

        with Session(self._engine) as session:
            # Get the project to read repo
            project = session.get(LinearProject, project_id)
            if not project:
                logger.warning("sync_issues: project %s not found", project_id)
                return SyncResult(created=0, updated=0, deleted_ids=())

            repo = project.repo

            # Load existing issues for this project
            stmt = select(LinearIssue).where(
                LinearIssue.linear_project_id == project_id,
            )
            existing_by_linear_id: dict[str, LinearIssue] = {
                issue.linear_issue_id: issue
                for issue in session.exec(stmt).all()
            }

            remote_linear_ids: set[str] = set()

            for issue_data in issues:
                linear_issue_id = issue_data.get("id", "")
                if not linear_issue_id:
                    continue
                remote_linear_ids.add(linear_issue_id)

                identifier = issue_data.get("identifier", "")
                title = issue_data.get("title", "")
                description = issue_data.get("description")
                state_obj = issue_data.get("state", {})
                status = state_obj.get("name", "backlog") if isinstance(state_obj, dict) else "backlog"
                priority = issue_data.get("priority", 0) or 0
                assignee_obj = issue_data.get("assignee")
                assignee = None
                if isinstance(assignee_obj, dict):
                    assignee = assignee_obj.get("displayName") or assignee_obj.get("name")
                url = issue_data.get("url", "")
                remote_branch = issue_data.get("branchName")

                if linear_issue_id in existing_by_linear_id:
                    # Update
                    row = existing_by_linear_id[linear_issue_id]
                    changed = False
                    for attr, val in [
                        ("identifier", identifier),
                        ("title", title),
                        ("description", description),
                        ("status", status),
                        ("priority", priority),
                        ("assignee", assignee),
                        ("url", url),
                    ]:
                        if getattr(row, attr) != val:
                            setattr(row, attr, val)
                            changed = True

                    # Branch: use remote branch if set, else keep existing or derive
                    if remote_branch and row.branch != remote_branch:
                        row.branch = remote_branch
                        changed = True
                    elif not row.branch and identifier and title:
                        row.branch = _derive_branch_name(identifier, title)
                        changed = True

                    if changed:
                        row.updated_at = now
                        row.last_synced_at = now
                        updated += 1
                    else:
                        row.last_synced_at = now
                else:
                    # Derive branch name
                    branch = remote_branch or (_derive_branch_name(identifier, title) if identifier else None)

                    issue = LinearIssue(
                        id=str(uuid.uuid4()),
                        linear_project_id=project_id,
                        repo=repo,
                        linear_issue_id=linear_issue_id,
                        identifier=identifier,
                        title=title,
                        description=description,
                        status=status,
                        priority=priority,
                        branch=branch,
                        assignee=assignee,
                        url=url,
                        last_synced_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(issue)
                    created += 1

            # Delete issues no longer present remotely
            for linear_id, row in existing_by_linear_id.items():
                if linear_id not in remote_linear_ids:
                    deleted_ids.append(row.id)
                    session.delete(row)

            # Update project sync timestamp
            project.last_synced_at = now
            project.updated_at = now

            session.commit()

        return SyncResult(created=created, updated=updated, deleted_ids=tuple(deleted_ids))

    def get_issue_by_linear_id(self, linear_issue_id: str) -> LinearIssue | None:
        with Session(self._engine) as session:
            stmt = select(LinearIssue).where(
                LinearIssue.linear_issue_id == linear_issue_id,
            )
            return session.exec(stmt).first()

    def get_issue_by_branch(self, repo: str, branch: str) -> LinearIssue | None:
        """Reverse lookup: find a Linear issue by repo + git branch."""
        with Session(self._engine) as session:
            stmt = select(LinearIssue).where(
                LinearIssue.repo == repo,
                LinearIssue.branch == branch,
            )
            return session.exec(stmt).first()

    def update_issue_status(self, linear_issue_id: str, status: str) -> bool:
        """Update the local status of a synced issue. Returns True if found."""
        with Session(self._engine) as session:
            stmt = select(LinearIssue).where(
                LinearIssue.linear_issue_id == linear_issue_id,
            )
            row = session.exec(stmt).first()
            if not row:
                return False
            row.status = status
            row.updated_at = _utcnow()
            session.commit()
            return True

    def list_issues_for_project(self, project_id: str) -> list[LinearIssue]:
        """List all issues for a given project (by internal PK)."""
        with Session(self._engine) as session:
            stmt = (
                select(LinearIssue)
                .where(LinearIssue.linear_project_id == project_id)
                .order_by(LinearIssue.priority, LinearIssue.identifier)
            )
            return list(session.exec(stmt).all())
