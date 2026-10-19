"""company report layout examples name the report instead of "최근 보고서"

company_report now retitles its slot with the report it read ("2026년 반기보고서").
The layout examples' slot title and narrative instructions said "최근 보고서",
so the narrative wrote "최근 보고서에 따르면" instead of the report name.

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-19 19:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0027'
down_revision: Union[str, Sequence[str], None] = '0026'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

QUESTIONS = ("삼성전자 기업 분석해줘", "현대모비스는 무슨 사업을 하는 회사야?")
# (이전, 새) — plan JSON 안의 문구
REPLACEMENTS = [
    ("<종목> 최근 보고서 요약", "<종목> 정기보고서 요약"),
    ("<종목>의 최근 보고서가 설명하는 사업과 영업 상황을",
     "<종목>의 정기보고서(어느 보고서인지 '2026년 반기보고서'처럼 이름을 밝혀서)가 설명하는 사업과 영업 상황을"),
    ("<종목>의 사업 구조와 매출 비중을 보고서 요약 기준으로 3문장으로",
     "<종목>의 사업 구조와 매출 비중을 정기보고서 요약 기준으로, 어느 보고서인지 이름을 밝혀 3문장으로"),
]


def _replace(pairs) -> None:
    for old, new in pairs:
        op.execute(sa.text("UPDATE layout_examples SET plan = replace(plan, :old, :new) WHERE question IN :qs")
                   .bindparams(sa.bindparam("qs", expanding=True), old=old, new=new, qs=list(QUESTIONS)))


def upgrade() -> None:
    _replace(REPLACEMENTS)


def downgrade() -> None:
    _replace([(new, old) for old, new in REPLACEMENTS])
