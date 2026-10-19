"""stock_report_summaries.breakdowns: revenue mix charts from the report tables

company_report splits its slot into revenue-mix charts plus the summary. The
breakdowns (segment, product, region, customer) are read from the report's
tables once and cached with the summary. NULL means not read yet.

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-19 21:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0028'
down_revision: Union[str, Sequence[str], None] = '0027'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stock_report_summaries', sa.Column('breakdowns', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('stock_report_summaries', 'breakdowns')
