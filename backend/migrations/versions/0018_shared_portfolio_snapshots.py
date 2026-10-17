"""shared_portfolios: share a snapshot of a portfolio instead of the live portfolio

Shared pages used to read the portfolio's current target allocations, so editing a
portfolio changed what others saw. Sharing now stores the name and allocations at that
moment. Portfolios that are shared now become snapshots with the same token, so
existing links keep working, and the is_shared/share_token columns are dropped.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-17 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'shared_portfolios',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('share_token', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('portfolio_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('allocations', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['portfolio_id'], ['portfolios.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('share_token'),
    )
    # 지금 공유 중인 포트폴리오는 현재 구성을 스냅샷으로 옮기고 토큰을 그대로 쓴다
    op.execute(
        """
        INSERT INTO shared_portfolios (share_token, user_id, portfolio_id, name, allocations, created_at)
        SELECT p.share_token, p.user_id, p.id, p.name,
               COALESCE(
                   (SELECT jsonb_agg(jsonb_build_object('ticker', t.ticker, 'weight', t.target_weight)
                                     ORDER BY t.id)
                      FROM target_allocations t WHERE t.portfolio_id = p.id),
                   '[]'::jsonb),
               COALESCE(p.updated_at, now())
          FROM portfolios p
         WHERE p.is_shared AND p.share_token IS NOT NULL
        """
    )
    op.drop_column('portfolios', 'is_shared')
    op.drop_column('portfolios', 'share_token')


def downgrade() -> None:
    op.add_column('portfolios', sa.Column('share_token', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('portfolios', sa.Column('is_shared', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_unique_constraint('portfolios_share_token_key', 'portfolios', ['share_token'])
    # 포트폴리오마다 가장 최근 스냅샷의 토큰을 되살린다 (구성은 원본의 현재 값으로 돌아간다)
    op.execute(
        """
        UPDATE portfolios p SET is_shared = TRUE, share_token = s.share_token
          FROM (SELECT DISTINCT ON (portfolio_id) portfolio_id, share_token
                  FROM shared_portfolios WHERE portfolio_id IS NOT NULL
                 ORDER BY portfolio_id, created_at DESC) s
         WHERE p.id = s.portfolio_id
        """
    )
    op.drop_table('shared_portfolios')
