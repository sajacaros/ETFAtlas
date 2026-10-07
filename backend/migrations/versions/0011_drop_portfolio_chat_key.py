"""drop portfolio chat key: the /portfolio chatbot command is removed

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-07 20:00:00.000000
"""
import secrets
import string
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALPHABET = string.ascii_letters + string.digits


def upgrade() -> None:
    op.drop_constraint('portfolios_chat_key_key', 'portfolios', type_='unique')
    op.drop_column('portfolios', 'chat_key')


def downgrade() -> None:
    # 0010과 같은 방식으로 다시 발급한다 (예전 키는 되살리지 않는다)
    op.add_column('portfolios', sa.Column('chat_key', sa.String(length=16), nullable=True))
    conn = op.get_bind()
    ids = [row.id for row in conn.execute(sa.text("SELECT id FROM portfolios"))]
    for portfolio_id in ids:
        key = "pf_" + "".join(secrets.choice(_ALPHABET) for _ in range(10))
        conn.execute(sa.text("UPDATE portfolios SET chat_key = :key WHERE id = :id"), {"key": key, "id": portfolio_id})
    op.alter_column('portfolios', 'chat_key', existing_type=sa.String(length=16), nullable=False)
    op.create_unique_constraint('portfolios_chat_key_key', 'portfolios', ['chat_key'])
