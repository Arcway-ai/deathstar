"""add conversation_branches table

Revision ID: a1b2c3d4e5f6
Revises: 8dded911ac73
Create Date: 2026-04-04 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '8dded911ac73'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table('conversation_branches',
        sa.Column('conversation_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('branch', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('added_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('conversation_id', 'branch'),
    )
    op.create_index('idx_conversation_branches_conv', 'conversation_branches', ['conversation_id'], unique=False)

    # Back-fill: copy existing branch associations from the conversations table
    op.execute(
        "INSERT INTO conversation_branches (conversation_id, branch, added_at) "
        "SELECT id, branch, created_at FROM conversations "
        "WHERE branch IS NOT NULL AND branch NOT IN ('main', 'master')"
    )


def downgrade() -> None:
    op.drop_index('idx_conversation_branches_conv', table_name='conversation_branches')
    op.drop_table('conversation_branches')
