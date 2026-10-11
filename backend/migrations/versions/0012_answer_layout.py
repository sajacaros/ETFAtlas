"""answer layout: chat logs keep the screen layout, each area's content goes to chat_slots

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-11 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chat_logs', sa.Column('layout', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table(
        'chat_slots',
        sa.Column('chat_log_id', sa.Integer(), sa.ForeignKey('chat_logs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('slot_id', sa.String(length=20), nullable=False),
        sa.Column('skill', sa.String(length=50), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('chat_log_id', 'slot_id'),
    )


def downgrade() -> None:
    op.drop_table('chat_slots')
    op.drop_column('chat_logs', 'layout')
