"""add preview_deployments table

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-04-07 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5d6e7f8a9b0'
down_revision: str | None = 'b3c4d5e6f7a8'
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        'preview_deployments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('repo', sa.String(), nullable=False),
        sa.Column('branch', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('provider_service_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('preview_url', sa.String(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_preview_repo_branch', 'preview_deployments', ['repo', 'branch'])
    op.create_index('idx_preview_status', 'preview_deployments', ['status'])


def downgrade() -> None:
    op.drop_index('idx_preview_status', table_name='preview_deployments')
    op.drop_index('idx_preview_repo_branch', table_name='preview_deployments')
    op.drop_table('preview_deployments')
