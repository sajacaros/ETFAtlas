"""layout_examples: add company_type to the buy-or-not example, seed a type question

The buy-or-not example gains a company_type slot beside the periodic report so
the screen shows which of the four types (quality compounder, turnaround,
mature and cyclical, emerging) the numbers support; stock_opinion computes the
same type itself and avoids a stock that fits none. "<stock> 무슨 유형이야?"
gets company_type alone with a narrative.

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-29 23:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0038'
down_revision: Union[str, Sequence[str], None] = '0037'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPINION = "삼성전자 지금 사도 될까?"


def _slot(skill, title, display, args):
    # 키 순서는 플래너 출력 스키마와 같게 (skill, name, title, display, args)
    return {"skill": skill, "title": title, "display": display, "args": args}


def _plan(*rows):
    return {"rows": [{"slots": list(row)} for row in rows]}


def _opinion_plan(with_type):
    return _plan(
        [_slot("stock_technical", "<종목> 차트 분석", "candlestick", {"stock": "<종목>"})],
        [_slot("company_financials", "<종목> 분기 실적", "bar", {"stock": "<종목>", "basis": "quarter", "periods": 8}),
         _slot("company_valuation", "<종목> 밸류에이션", "table", {"stocks": ["<종목>"]})],
        [*([_slot("company_type", "<종목> 유형 판정", "table", {"stock": "<종목>"})] if with_type else []),
         _slot("company_report", "<종목> 정기보고서", "markdown", {"stock": "<종목>"})],
        [_slot("stock_opinion", "<종목> 살까 말까", "markdown", {"stock": "<종목>"})],
    )


OPINION_DESCRIPTION = (
    "종목을 살지 말지(매수 의견) 물으면 차트(stock_technical), 재무(company_financials·company_valuation·company_type), "
    "보고서(company_report, need 없이 개요)를 두고 마지막에 stock_opinion 하나. narrative는 넣지 않는다 "
    "(narrative는 매수 의견을 쓰지 않는다)"
)
OLD_DESCRIPTION = (
    "종목을 살지 말지(매수 의견) 물으면 차트(stock_technical), 재무(company_financials·company_valuation), "
    "보고서(company_report, need 없이 개요)를 두고 마지막에 stock_opinion 하나. narrative는 넣지 않는다 "
    "(narrative는 매수 의견을 쓰지 않는다)"
)

# 0013과 같은 원칙: 질문 유형마다 하나, 대상은 자리표시자, 평가 세트와 대상·문장이 겹치지 않게.
# 임베딩은 embed_code_examples DAG가 채운다 (status='active' → 'embedded')
SEEDS = [
    {
        "question": "삼성전자는 성장주야 턴어라운드주야?",
        "description": "종목이 어떤 유형(지속 성장주·턴어라운드주·경기민감·성숙기·신흥·초기 단계)인지 물으면 company_type 하나와 "
                       "판정·기준을 설명하는 해설. 매수 의견은 내지 않는다 (살지 말지까지 물으면 stock_opinion 예시)",
        "plan": _plan(
            [_slot("company_type", "<종목> 유형 판정", "table", {"stock": "<종목>"})],
            [_slot("narrative", "해설", "text", {"instruction": "<종목>이 어느 유형으로 판정됐는지와 그 근거가 된 기준·값, "
                                                                 "어긋난 기준을 3~4문장으로. 보고서로 확인할 기준은 확인하지 않았다고 쓴다"})],
        ),
    },
]


def _set_opinion(plan, description):
    op.execute(sa.text("UPDATE layout_examples SET plan = :plan, description = :d WHERE question = :q")
               .bindparams(plan=json.dumps(plan, ensure_ascii=False), d=description, q=OPINION))


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
    _set_opinion(_opinion_plan(True), OPINION_DESCRIPTION)


def downgrade() -> None:
    for s in SEEDS:
        op.execute(sa.text("DELETE FROM layout_examples WHERE question = :q").bindparams(q=s["question"]))
    _set_opinion(_opinion_plan(False), OLD_DESCRIPTION)
