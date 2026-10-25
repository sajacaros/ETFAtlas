"""layout_examples: seed an example for ranking ETFs by dividend yield

ETF nodes now carry the trailing twelve-month dividend yield and dividend per
share from the naver profile (dividend_yield, dividend_per_share), and rank can
take every ETF as candidates. Questions like "ETFs paying 5% or more, best
recent price first" filter the whole universe by yield, then re-rank the result
by a period return.

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-25 22:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0034'
down_revision: Union[str, Sequence[str], None] = '0033'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slot(skill, title, display, args, name=None):
    # 키 순서는 플래너 출력 스키마와 같게 (skill, name, title, display, args)
    return {"skill": skill, **({"name": name} if name else {}), "title": title, "display": display, "args": args}


# 0021과 같은 원칙: 대상은 자리표시자, 평가 세트와 문장이 겹치지 않게.
# 임베딩은 embed_code_examples DAG가 채운다 (status='active' → 'embedded')
SEEDS = [
    {
        "question": "분배율 5% 넘는 ETF 중에 1개월 수익률 좋은 순으로 보여줘",
        "description": "배당·분배율 조건은 rank의 dividend_yield로 전체 ETF(targets·theme 비움)에서 거르고, "
                       "남은 개수를 모르므로 넉넉히(top 30) 내보내 다른 기준의 rank가 다시 받는다",
        "plan": {"rows": [
            {"slots": [_slot("rank", "분배율 <N>% 이상 ETF", "table",
                             {"kind": "etf", "by": "dividend_yield", "min_value": 5, "top": 30}, name="payers")]},
            {"slots": [_slot("rank", "1개월 수익률 높은 순", "bar",
                             {"kind": "etf", "targets": ["@payers.1-30"], "by": "return_1m", "top": 10})]},
            {"slots": [_slot("narrative", "해설", "text",
                             {"instruction": "분배율 <N>% 이상 ETF 중 최근 수익률이 좋은 ETF들을, "
                                             "분배율이 최근 12개월 기준이라는 점을 밝혀 3문장으로"})]},
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
