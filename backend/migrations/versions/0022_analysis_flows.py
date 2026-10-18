"""analysis_flows: saved node graphs for the stock analysis flow

Each user can save flows (nodes and the edges between them) and load them
back onto the canvas. Run results are not stored.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-18 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0022'
down_revision: Union[str, Sequence[str], None] = '0021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'analysis_flows',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('graph', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_analysis_flows_user_id', 'analysis_flows', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_analysis_flows_user_id', table_name='analysis_flows')
    op.drop_table('analysis_flows')
