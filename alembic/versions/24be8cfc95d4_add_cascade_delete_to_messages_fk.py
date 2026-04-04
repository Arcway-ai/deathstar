"""add cascade delete to messages FK

Revision ID: 24be8cfc95d4
Revises: a1b2c3d4e5f6
Create Date: 2026-04-04 16:04:17.636579
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '24be8cfc95d4'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Use batch mode for SQLite compatibility (recreates table under the hood)
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_constraint("fk_messages_conversation_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_messages_conversation_id",
            "conversations",
            ["conversation_id"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("messages", schema=None) as batch_op:
        batch_op.drop_constraint("fk_messages_conversation_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_messages_conversation_id",
            "conversations",
            ["conversation_id"],
            ["id"],
        )
