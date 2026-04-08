"""add partial unique index for active preview deployments

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-04-08 10:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: str | None = 'd6e7f8a9b0c1'
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    # Partial unique index: only one active (non-destroyed, non-failed) preview
    # per repo+branch+provider.  Closes the TOCTOU race in the application-level
    # duplicate check by letting PostgreSQL enforce uniqueness atomically.
    op.create_index(
        'uq_preview_active_repo_branch_provider',
        'preview_deployments',
        ['repo', 'branch', 'provider'],
        unique=True,
        postgresql_where=sa.text("status NOT IN ('destroyed', 'failed')"),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_preview_active_repo_branch_provider',
        table_name='preview_deployments',
    )
