"""account_type → account_types: a portfolio can carry several account type tags

A portfolio can suit both IRP and pension savings, so the single account_type
becomes an array of tags with at least one entry, on portfolios and on shared
snapshots. Each row keeps its current type as its only tag.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-17 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0020'
down_revision: Union[str, Sequence[str], None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ('portfolios', 'shared_portfolios')


def upgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                'account_types', postgresql.ARRAY(sa.String(20)), nullable=False,
                server_default=sa.text("ARRAY['PENSION_SAVINGS']::varchar(20)[]"),
            ),
        )
        op.execute(f"UPDATE {table} SET account_types = ARRAY[account_type]::varchar(20)[]")
        op.create_check_constraint(f'ck_{table}_account_types', table, 'cardinality(account_types) >= 1')
        op.drop_column(table, 'account_type')


def downgrade() -> None:
    for table in TABLES:
        op.add_column(
            table,
            sa.Column('account_type', sa.String(20), nullable=False, server_default='PENSION_SAVINGS'),
        )
        # 태그가 여러 개면 첫 번째(IRP 우선)만 남는다
        op.execute(f"UPDATE {table} SET account_type = account_types[1]")
        op.drop_constraint(f'ck_{table}_account_types', table, type_='check')
        op.drop_column(table, 'account_types')
