"""portfolio chat key: identify a portfolio in chatbot commands

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07 10:00:00.000000
"""
import secrets
import string
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALPHABET = string.ascii_letters + string.digits


def _new_key() -> str:
    # 모델의 generate_chat_key와 같은 형식 (마이그레이션은 앱 코드에 기대지 않는다)
    return "pf_" + "".join(secrets.choice(_ALPHABET) for _ in range(10))


def upgrade() -> None:
    op.add_column('portfolios', sa.Column('chat_key', sa.String(length=16), nullable=True))
    conn = op.get_bind()
    ids = [row.id for row in conn.execute(sa.text("SELECT id FROM portfolios"))]
    for portfolio_id in ids:
        conn.execute(
            sa.text("UPDATE portfolios SET chat_key = :key WHERE id = :id"),
            {"key": _new_key(), "id": portfolio_id},
        )
    op.alter_column('portfolios', 'chat_key', existing_type=sa.String(length=16), nullable=False)
    op.create_unique_constraint('portfolios_chat_key_key', 'portfolios', ['chat_key'])


def downgrade() -> None:
    op.drop_constraint('portfolios_chat_key_key', 'portfolios', type_='unique')
    op.drop_column('portfolios', 'chat_key')
