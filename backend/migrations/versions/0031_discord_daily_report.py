"""discord daily report: rise threshold + notification kind

After the 16:30 collection, the DAG sends a daily report (collection summary and
ETFs that rose past rise_threshold) to Discord. Its history shares
discord_notification_logs with the weight-change alerts, told apart by kind.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-21 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0031'
down_revision: Union[str, Sequence[str], None] = '0030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('discord_settings',
                  sa.Column('rise_threshold', sa.Float(), nullable=False, server_default='3.0'))
    op.add_column('discord_notification_logs',
                  sa.Column('kind', sa.String(20), nullable=False, server_default='weight_change'))


def downgrade() -> None:
    op.drop_column('discord_notification_logs', 'kind')
    op.drop_column('discord_settings', 'rise_threshold')
