"""discord settings: separate threshold for newly added holdings

A stock newly added to an active ETF is worth a look at a smaller weight than an
existing holding's change, so added rows get their own threshold (default 2%p).

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-22 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0032'
down_revision: Union[str, Sequence[str], None] = '0031'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('discord_settings',
                  sa.Column('added_threshold', sa.Float(), nullable=False, server_default='2.0'))


def downgrade() -> None:
    op.drop_column('discord_settings', 'added_threshold')
