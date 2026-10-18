"""flow_runs + flow schedule: record what a saved flow picked and run it daily

A saved flow can now run itself after the market closes and post the change
to Discord. Each day's picks (stocks reaching result nodes) are kept in
flow_runs, one row per flow per day, so later prices can score them.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-18 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0023'
down_revision: Union[str, Sequence[str], None] = '0022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('analysis_flows', sa.Column('schedule_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('analysis_flows', sa.Column('notify', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('analysis_flows', sa.Column('last_scheduled_on', sa.Date(), nullable=True))
    op.create_table(
        'flow_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('flow_id', sa.Integer(), sa.ForeignKey('analysis_flows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('run_date', sa.Date(), nullable=False),
        sa.Column('trigger', sa.String(10), nullable=False),
        sa.Column('picks', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('flow_id', 'run_date', name='uq_flow_runs_flow_date'),
    )


def downgrade() -> None:
    op.drop_table('flow_runs')
    op.drop_column('analysis_flows', 'last_scheduled_on')
    op.drop_column('analysis_flows', 'notify')
    op.drop_column('analysis_flows', 'schedule_enabled')
