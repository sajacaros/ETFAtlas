"""layout_examples: seed the buy-or-not example (stock_opinion)

"<stock> 살까 말까?" gets the chart analysis, quarterly results, valuation and
the periodic report overview, closed by stock_opinion instead of a narrative:
it rates the chart, financial and report perspectives and a fixed rule turns
the ratings into one verdict. The company and price analysis examples say so,
so they stay without an opinion.

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-29 15:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0037'
down_revision: Union[str, Sequence[str], None] = '0036'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOTE = " 살지 말지 물으면 stock_opinion 예시"
NOTED = ("삼성전자 기업 분석해줘", "삼성전자 주가 분석해줘")


def _slot(skill, title, display, args):
    # 키 순서는 플래너 출력 스키마와 같게 (skill, name, title, display, args)
    return {"skill": skill, "title": title, "display": display, "args": args}


def _plan(*rows):
    return {"rows": [{"slots": list(row)} for row in rows]}


# 0013과 같은 원칙: 질문 유형마다 하나, 대상은 자리표시자, 평가 세트와 대상·문장이 겹치지 않게.
# 임베딩은 embed_code_examples DAG가 채운다 (status='active' → 'embedded')
SEEDS = [
    {
        "question": "삼성전자 지금 사도 될까?",
        "description": "종목을 살지 말지(매수 의견) 물으면 차트(stock_technical), 재무(company_financials·company_valuation), "
                       "보고서(company_report, need 없이 개요)를 두고 마지막에 stock_opinion 하나. narrative는 넣지 않는다 "
                       "(narrative는 매수 의견을 쓰지 않는다)",
        "plan": _plan(
            [_slot("stock_technical", "<종목> 차트 분석", "candlestick", {"stock": "<종목>"})],
            [_slot("company_financials", "<종목> 분기 실적", "bar", {"stock": "<종목>", "basis": "quarter", "periods": 8}),
             _slot("company_valuation", "<종목> 밸류에이션", "table", {"stocks": ["<종목>"]})],
            [_slot("company_report", "<종목> 정기보고서", "markdown", {"stock": "<종목>"})],
            [_slot("stock_opinion", "<종목> 살까 말까", "markdown", {"stock": "<종목>"})],
        ),
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
    for q in NOTED:
        op.execute(sa.text("UPDATE layout_examples SET description = description || :note WHERE question = :q")
                   .bindparams(note=NOTE, q=q))


def downgrade() -> None:
    for s in SEEDS:
        op.execute(sa.text("DELETE FROM layout_examples WHERE question = :q").bindparams(q=s["question"]))
    for q in NOTED:
        op.execute(sa.text("UPDATE layout_examples SET description = replace(description, :note, '') WHERE question = :q")
                   .bindparams(note=NOTE, q=q))
