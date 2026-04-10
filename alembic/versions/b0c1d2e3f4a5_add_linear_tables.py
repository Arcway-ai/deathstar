"""add linear_projects and linear_issues tables

Revision ID: b0c1d2e3f4a5
Revises: a9b0c1d2e3f4
Create Date: 2026-04-10 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b0c1d2e3f4a5'
down_revision: str | None = 'a9b0c1d2e3f4'
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        'linear_projects',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('repo', sa.String(), nullable=False),
        sa.Column('conversation_id', sa.String(), sa.ForeignKey('conversations.id', ondelete='SET NULL'), nullable=True),
        sa.Column('linear_project_id', sa.String(), nullable=False),
        sa.Column('linear_team_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False, server_default=''),
        sa.Column('state', sa.String(), nullable=False, server_default='planned'),
        sa.Column('url', sa.String(), nullable=False, server_default=''),
        sa.Column('last_synced_at', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_linear_projects_repo', 'linear_projects', ['repo'])
    op.create_index('idx_linear_projects_linear_id', 'linear_projects', ['linear_project_id'], unique=True)
    op.create_index('idx_linear_projects_conversation', 'linear_projects', ['conversation_id'])

    op.create_table(
        'linear_issues',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('linear_project_id', sa.String(), sa.ForeignKey('linear_projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('repo', sa.String(), nullable=False),
        sa.Column('linear_issue_id', sa.String(), nullable=False),
        sa.Column('identifier', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='backlog'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('branch', sa.String(), nullable=True),
        sa.Column('assignee', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=False, server_default=''),
        sa.Column('last_synced_at', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_linear_issues_linear_id', 'linear_issues', ['linear_issue_id'], unique=True)
    op.create_index('idx_linear_issues_project', 'linear_issues', ['linear_project_id'])
    op.create_index('idx_linear_issues_repo_branch', 'linear_issues', ['repo', 'branch'])


def downgrade() -> None:
    op.drop_table('linear_issues')
    op.drop_table('linear_projects')
