"""discord_notification_logs: history of Discord weight-change alerts

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-14 11:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'discord_notification_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('base_date', sa.String(10), nullable=False),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('threshold', sa.Float(), nullable=False),
        sa.Column('items', postgresql.JSONB(), nullable=False),
        sa.Column('message_count', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_discord_notification_logs_base_date', 'discord_notification_logs', ['base_date'])


def downgrade() -> None:
    op.drop_index('ix_discord_notification_logs_base_date', table_name='discord_notification_logs')
    op.drop_table('discord_notification_logs')
