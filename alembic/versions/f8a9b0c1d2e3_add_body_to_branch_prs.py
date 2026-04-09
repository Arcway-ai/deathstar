"""add body column to branch_prs

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-04-09 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a9b0c1d2e3'
down_revision: str | None = 'e7f8a9b0c1d2'
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column('branch_prs', sa.Column('body', sa.String(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('branch_prs', 'body')
