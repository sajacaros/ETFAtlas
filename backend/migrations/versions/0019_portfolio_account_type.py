"""portfolios.account_type: IRP or pension savings (PENSION_SAVINGS)

Each account type allows different holdings, so portfolios record which account they
are for. Shared snapshots keep the type at the time of sharing. Existing portfolios
start as PENSION_SAVINGS; existing snapshots take their portfolio's type.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-17 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'portfolios',
        sa.Column('account_type', sa.String(20), nullable=False, server_default='PENSION_SAVINGS'),
    )
    op.add_column(
        'shared_portfolios',
        sa.Column('account_type', sa.String(20), nullable=False, server_default='PENSION_SAVINGS'),
    )
    op.execute(
        """
        UPDATE shared_portfolios s SET account_type = p.account_type
          FROM portfolios p WHERE p.id = s.portfolio_id
        """
    )


def downgrade() -> None:
    op.drop_column('shared_portfolios', 'account_type')
    op.drop_column('portfolios', 'account_type')
