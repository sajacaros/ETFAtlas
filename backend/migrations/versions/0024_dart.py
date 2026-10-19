"""dart: API key setting + corp codes, financials and disclosures for chatbot company analysis

The chatbot's company snapshot reads quarterly financials and recent
disclosures from DART. The DART key is entered on the admin page and kept
encrypted in dart_settings (no environment fallback). dart_corps holds
every company DART knows, so a listed stock that no collected ETF holds can
be told apart from a name that does not exist.

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-19 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0024'
down_revision: Union[str, Sequence[str], None] = '0023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dart_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('api_key', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'dart_corps',
        sa.Column('corp_code', sa.String(8), nullable=False),
        sa.Column('corp_name', sa.Text(), nullable=False),
        sa.Column('stock_code', sa.String(6), nullable=True),
        sa.Column('modify_date', sa.String(8), nullable=True),
        sa.PrimaryKeyConstraint('corp_code'),
    )
    op.create_index('ix_dart_corps_stock_code', 'dart_corps', ['stock_code'])
    op.create_index('ix_dart_corps_corp_name', 'dart_corps', ['corp_name'])
    op.create_table(
        'stock_financials',
        sa.Column('stock_code', sa.String(6), nullable=False),
        sa.Column('bsns_year', sa.Integer(), nullable=False),
        sa.Column('reprt_code', sa.String(5), nullable=False),
        sa.Column('fs_div', sa.String(3), nullable=False),
        sa.Column('account', sa.Text(), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=True),
        sa.Column('amount_cum', sa.BigInteger(), nullable=True),
        sa.Column('rcept_no', sa.String(14), nullable=True),
        sa.Column('fetched_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('stock_code', 'bsns_year', 'reprt_code', 'fs_div', 'account'),
    )
    op.create_table(
        'stock_disclosures',
        sa.Column('rcept_no', sa.String(14), nullable=False),
        sa.Column('stock_code', sa.String(6), nullable=False),
        sa.Column('corp_code', sa.String(8), nullable=False),
        sa.Column('report_nm', sa.Text(), nullable=False),
        sa.Column('rcept_dt', sa.Date(), nullable=False),
        sa.Column('flr_nm', sa.Text(), nullable=True),
        sa.Column('rm', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('rcept_no'),
    )
    op.create_index('ix_stock_disclosures_stock_date', 'stock_disclosures', ['stock_code', 'rcept_dt'])


def downgrade() -> None:
    op.drop_index('ix_stock_disclosures_stock_date', table_name='stock_disclosures')
    op.drop_table('stock_disclosures')
    op.drop_table('stock_financials')
    op.drop_index('ix_dart_corps_corp_name', table_name='dart_corps')
    op.drop_index('ix_dart_corps_stock_code', table_name='dart_corps')
    op.drop_table('dart_corps')
    op.drop_table('dart_settings')
