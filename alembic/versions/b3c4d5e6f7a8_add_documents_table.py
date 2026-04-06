"""add documents table

Revision ID: b3c4d5e6f7a8
Revises: 24be8cfc95d4
Create Date: 2026-04-06 12:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: str | None = '24be8cfc95d4'
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        'documents',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('repo', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('document_type', sa.String(), nullable=False),
        sa.Column('source_conversation_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_documents_repo', 'documents', ['repo', 'updated_at'])


def downgrade() -> None:
    op.drop_index('idx_documents_repo', table_name='documents')
    op.drop_table('documents')
