"""member management: password resets, keep chat logs/code examples when a user is deleted

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-03 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'password_resets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(op.f('ix_password_resets_user_id'), 'password_resets', ['user_id'], unique=False)

    # 회원을 삭제해도 챗봇 로그(코드 예제 큐레이션 자료)와 코드 예제는 작성자만 비우고 남긴다
    op.alter_column('chat_logs', 'user_id', existing_type=sa.INTEGER(), nullable=True)
    op.drop_constraint('chat_logs_user_id_fkey', 'chat_logs', type_='foreignkey')
    op.create_foreign_key('chat_logs_user_id_fkey', 'chat_logs', 'users', ['user_id'], ['id'], ondelete='SET NULL')
    op.drop_constraint('code_examples_created_by_fkey', 'code_examples', type_='foreignkey')
    op.create_foreign_key('code_examples_created_by_fkey', 'code_examples', 'users', ['created_by'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('code_examples_created_by_fkey', 'code_examples', type_='foreignkey')
    op.create_foreign_key('code_examples_created_by_fkey', 'code_examples', 'users', ['created_by'], ['id'])
    op.drop_constraint('chat_logs_user_id_fkey', 'chat_logs', type_='foreignkey')
    op.create_foreign_key('chat_logs_user_id_fkey', 'chat_logs', 'users', ['user_id'], ['id'])
    op.alter_column('chat_logs', 'user_id', existing_type=sa.INTEGER(), nullable=False)
    op.drop_index(op.f('ix_password_resets_user_id'), table_name='password_resets')
    op.drop_table('password_resets')
