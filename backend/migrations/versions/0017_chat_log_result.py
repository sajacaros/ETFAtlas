"""chat_logs.result: how each answer ended (completed / cancelled / failed / clarifying / running)

status already tracks feedback and example curation (liked, approved, rejected, ...),
so the answer's outcome gets its own column. Existing rows are backfilled from the
answer text and slot states; clarifying wasn't recorded before, so those stay completed.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-16 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 지난 답변을 판별하는 문구 (orchestrator·chat_service의 STOPPED_ANSWER, FALLBACK_ANSWER)
STOPPED_ANSWERS = (
    "요청하신 대로 중지했습니다.",
    "요청하신 대로 중지했습니다. 지금까지 실행한 단계는 '실행 과정'에서 확인할 수 있어요.",
)
FALLBACK_ANSWER = "죄송합니다. 답변 생성에 실패했습니다. 다시 질문해 주세요."


def upgrade() -> None:
    op.add_column(
        'chat_logs',
        sa.Column('result', sa.String(20), nullable=False, server_default='completed'),
    )
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE chat_logs SET result = 'cancelled' WHERE answer IN (:stopped1, :stopped2) "
            "OR id IN (SELECT chat_log_id FROM chat_slots WHERE status = 'stopped')"
        ),
        {"stopped1": STOPPED_ANSWERS[0], "stopped2": STOPPED_ANSWERS[1]},
    )
    # 답이 비어 있으면 저장 전에 끊긴 것이다
    conn.execute(
        sa.text("UPDATE chat_logs SET result = 'failed' WHERE answer IN (:fallback, '')"),
        {"fallback": FALLBACK_ANSWER},
    )


def downgrade() -> None:
    op.drop_column('chat_logs', 'result')
