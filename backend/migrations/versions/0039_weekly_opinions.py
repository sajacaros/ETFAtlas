"""weekly buy opinions for every stock (opinion_runs, stock_opinions, stock_reports.tagline)

Every Saturday morning the backend runs the buy-or-not opinion (stock_opinion)
on every stock the ETFs hold and posts the ten best "worth buying" stocks to
Discord. Each stock's ratings are kept per run so the next week can mark new
entries and a restarted backend skips stocks it already judged. tagline is a
one-line (50 characters) description of what the company does, written from
the report overview for the stocks that make the list.

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-31 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0039'
down_revision: Union[str, Sequence[str], None] = '0038'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'opinion_runs',
        sa.Column('run_on', sa.Date(), nullable=False),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('heartbeat_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('run_on'),
    )
    op.create_table(
        'stock_opinions',
        sa.Column('run_on', sa.Date(), nullable=False),
        sa.Column('stock_code', sa.String(6), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('verdict', sa.String(20), nullable=False),
        sa.Column('score', sa.Float(), nullable=True),
        sa.Column('chart_rating', sa.String(10), nullable=True),
        sa.Column('financials_rating', sa.String(10), nullable=True),
        sa.Column('report_rating', sa.String(10), nullable=True),
        sa.Column('company_type', sa.Text(), nullable=True),
        sa.Column('reasons', postgresql.JSONB(), nullable=True),
        sa.Column('market_cap', sa.Float(), nullable=True),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['run_on'], ['opinion_runs.run_on'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('run_on', 'stock_code'),
    )
    op.add_column('stock_reports', sa.Column('tagline', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('stock_reports', 'tagline')
    op.drop_table('stock_opinions')
    op.drop_table('opinion_runs')
