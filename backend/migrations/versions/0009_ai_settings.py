"""ai settings

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-06 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ai_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('llm_api_base', sa.Text(), nullable=True),
        sa.Column('llm_api_key', sa.Text(), nullable=True),
        sa.Column('llm_model', sa.Text(), nullable=True),
        sa.Column('embedding_api_base', sa.Text(), nullable=True),
        sa.Column('embedding_api_key', sa.Text(), nullable=True),
        sa.Column('embedding_model', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('ai_settings')
