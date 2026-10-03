"""chat sessions: per-session history with rolling summary, refined questions

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-03 20:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('summarized_until_log_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_chat_sessions_user_id'), 'chat_sessions', ['user_id'], unique=False)

    op.add_column('chat_logs', sa.Column('session_id', sa.Integer(), nullable=True))
    op.add_column('chat_logs', sa.Column('refined_question', sa.Text(), nullable=True))
    op.create_index(op.f('ix_chat_logs_session_id'), 'chat_logs', ['session_id'], unique=False)
    op.create_foreign_key(
        'chat_logs_session_id_fkey', 'chat_logs', 'chat_sessions', ['session_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('chat_logs_session_id_fkey', 'chat_logs', type_='foreignkey')
    op.drop_index(op.f('ix_chat_logs_session_id'), table_name='chat_logs')
    op.drop_column('chat_logs', 'refined_question')
    op.drop_column('chat_logs', 'session_id')
    op.drop_index(op.f('ix_chat_sessions_user_id'), table_name='chat_sessions')
    op.drop_table('chat_sessions')
