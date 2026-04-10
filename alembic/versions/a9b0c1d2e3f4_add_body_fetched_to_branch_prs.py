"""add body_fetched column to branch_prs

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
Create Date: 2026-04-09 19:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9b0c1d2e3f4'
down_revision: str | None = 'f8a9b0c1d2e3'
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column('branch_prs', sa.Column('body_fetched', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    # Mark existing rows that already have a body as fetched
    op.execute("UPDATE branch_prs SET body_fetched = true WHERE body != ''")


def downgrade() -> None:
    op.drop_column('branch_prs', 'body_fetched')
