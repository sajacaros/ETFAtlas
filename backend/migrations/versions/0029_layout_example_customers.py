"""layout example: main customers / revenue mix → company_report + narrative

Asked "who are the main customers", the planner sometimes laid out the report
alone, leaving no sentence that answers the question. company_report now splits
itself into revenue-mix charts and the summary, so the example is one report
slot plus a narrative that answers from them.

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-19 22:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0029'
down_revision: Union[str, Sequence[str], None] = '0028'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slot(skill, title, display, args):
    return {"skill": skill, "title": title, "display": display, "args": args}


# 임베딩은 embed_code_examples DAG가 채운다 (status='active' → 'embedded')
SEEDS = [
    {
        "question": "셀트리온 주요 고객이 어디야?",
        "description": "주요 고객·매출처·매출 구성(제품·지역별)을 물으면 company_report 하나와 해설. company_report가 보고서 표의 "
                       "매출 구성을 차트로 스스로 나눠 보여 준다. 해설은 질문에 바로 답하고, 고객 이름이 공시되지 않았으면 그렇다고 밝힌다",
        "plan": {"rows": [
            {"slots": [_slot("company_report", "<종목> 정기보고서 요약", "markdown", {"stock": "<종목>"})]},
            {"slots": [_slot("narrative", "해설", "text", {
                "instruction": "<종목>의 주요 고객(매출처)과 매출 구성을 정기보고서 기준으로, 어느 보고서인지 이름을 밝혀 "
                               "2~3문장으로. 고객 이름이 공시되지 않았으면 그렇다고 쓴다"})]},
        ]},
    },
]


def upgrade() -> None:
    table = sa.table(
        'layout_examples',
        sa.column('question', sa.Text), sa.column('plan', sa.Text), sa.column('description', sa.Text),
        sa.column('status', sa.String),
    )
    op.bulk_insert(table, [
        {"question": s["question"], "plan": json.dumps(s["plan"], ensure_ascii=False),
         "description": s["description"], "status": "active"}
        for s in SEEDS
    ])


def downgrade() -> None:
    for s in SEEDS:
        op.execute(sa.text("DELETE FROM layout_examples WHERE question = :q").bindparams(q=s["question"]))
