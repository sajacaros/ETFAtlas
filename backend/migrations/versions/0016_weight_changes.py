"""weight_changes: active-ETF weight changes computed by Airflow; drop discord_watch_etfs

Discord alerts and the web weight-change page now cover every active ETF and read
the changes Airflow stores here instead of computing them separately.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-14 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('discord_watch_etfs')
    op.create_table(
        'weight_changes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('base_date', sa.String(10), nullable=False),
        sa.Column('prev_date', sa.String(10), nullable=False),
        sa.Column('etf_code', sa.String(20), nullable=False),
        sa.Column('etf_name', sa.Text(), nullable=False),
        sa.Column('stock_code', sa.String(20), nullable=False),
        sa.Column('stock_name', sa.Text(), nullable=False),
        sa.Column('change_type', sa.String(10), nullable=False),
        sa.Column('previous_weight', sa.Float(), nullable=False),
        sa.Column('current_weight', sa.Float(), nullable=False),
        sa.Column('weight_change', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('base_date', 'etf_code', 'stock_code', name='uq_weight_changes_date_etf_stock'),
    )
    op.create_index('ix_weight_changes_base_date', 'weight_changes', ['base_date'])
    op.create_table(
        'weight_change_dates',
        sa.Column('base_date', sa.String(10), nullable=False),
        sa.Column('computed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('base_date'),
    )


def downgrade() -> None:
    op.drop_table('weight_change_dates')
    op.drop_index('ix_weight_changes_base_date', table_name='weight_changes')
    op.drop_table('weight_changes')
    op.create_table(
        'discord_watch_etfs',
        sa.Column('etf_code', sa.String(20), nullable=False),
        sa.Column('etf_name', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('etf_code'),
    )
