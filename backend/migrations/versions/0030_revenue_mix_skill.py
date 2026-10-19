"""company_revenue_mix: the revenue mix without the report summary

Asked only for main customers or the revenue mix, the answer showed the whole
report summary above the narrative, burying the answer. The revenue mix is now
its own skill, so a report may be cached with its mix but no summary yet
(stock_report_summaries.summary becomes nullable), and the 0029 main-customer
example lays out company_revenue_mix + narrative instead of company_report.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-19 23:00:00.000000
"""
import importlib.util
import json
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0030'
down_revision: Union[str, Sequence[str], None] = '0029'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slot(skill, title, display, args):
    return {"skill": skill, "title": title, "display": display, "args": args}


# 0029 예시를 고쳐 쓴다 — 질문이 같아 임베딩은 그대로 둔다
SEEDS = [
    {
        "question": "셀트리온 주요 고객이 어디야?",
        "description": "주요 고객·매출처·매출 구성(제품·지역별)만 물으면 company_revenue_mix 하나와 해설. 보고서 요약(company_report)은 "
                       "기업 분석·사업 내용을 물을 때만 쓴다. 해설은 질문에 바로 답하고, 고객 이름이 공시되지 않았으면 그렇다고 밝힌다",
        "plan": {"rows": [
            {"slots": [_slot("company_revenue_mix", "<종목> 매출 구성", "bar", {"stock": "<종목>"})]},
            {"slots": [_slot("narrative", "해설", "text", {
                "instruction": "<종목>의 주요 고객(매출처)과 매출 구성을 정기보고서 기준으로, 어느 보고서인지 이름을 밝혀 "
                               "2~3문장으로. 고객 이름이 공시되지 않았으면 그렇다고 쓴다"})]},
        ]},
    },
]


def _update(seeds) -> None:
    for s in seeds:
        op.execute(sa.text("UPDATE layout_examples SET plan = :plan, description = :description WHERE question = :q")
                   .bindparams(plan=json.dumps(s["plan"], ensure_ascii=False), description=s["description"], q=s["question"]))


def upgrade() -> None:
    op.alter_column('stock_report_summaries', 'summary', existing_type=sa.Text(), nullable=True)
    _update(SEEDS)


def downgrade() -> None:
    spec = importlib.util.spec_from_file_location("seeds_0029", Path(__file__).parent / "0029_layout_example_customers.py")
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    _update(previous.SEEDS)
    op.execute("DELETE FROM stock_report_summaries WHERE summary IS NULL")  # 매출 구성만 뽑은 보고서 — 다시 읽으면 된다
    op.alter_column('stock_report_summaries', 'summary', existing_type=sa.Text(), nullable=False)
