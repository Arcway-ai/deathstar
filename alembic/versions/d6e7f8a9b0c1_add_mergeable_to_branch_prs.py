"""add mergeable columns to branch_prs

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-04-07 14:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6e7f8a9b0c1'
down_revision: str | None = 'c5d6e7f8a9b0'
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column('branch_prs', sa.Column('mergeable', sa.Boolean(), nullable=True))
    op.add_column('branch_prs', sa.Column('mergeable_state', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('branch_prs', 'mergeable_state')
    op.drop_column('branch_prs', 'mergeable')
