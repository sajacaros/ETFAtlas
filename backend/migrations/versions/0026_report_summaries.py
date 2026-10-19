"""stock_report_summaries + company analysis reads the latest periodic report

The company analysis showed the latest report only as a disclosure title.
company_report reads the narrative chapters of the latest periodic report
(business, MD&A, investor protection, segment note) from DART and caches the
summary by receipt number. The "기업 분석" layout example gains that slot, and
a new example covers "what does this company do".

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-19 17:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0026'
down_revision: Union[str, Sequence[str], None] = '0025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slot(skill, title, display, args, name=None):
    # 키 순서는 플래너 출력 스키마와 같게 (skill, name, title, display, args)
    return {"skill": skill, **({"name": name} if name else {}), "title": title, "display": display, "args": args}


def _plan(*rows):
    return {"rows": [{"slots": list(row)} for row in rows]}


def _narrative(instruction):
    return [_slot("narrative", "해설", "text", {"instruction": instruction})]


ANALYSIS_QUESTION = "삼성전자 기업 분석해줘"
ANALYSIS_DESCRIPTION = (
    "종목 하나를 '분석'해 달라면 주가 추이와 담은 ETF(ETF Atlas만의 데이터), DART 실적과 최근 공시, "
    "가장 최근 정기보고서 본문 요약을 나란히 두고 해설로 묶는다. 매수·매도 판단은 하지 않는다"
)
ANALYSIS_PLAN = _plan(
    [_slot("stock_trend", "<종목> 주가 추이", "line", {"stocks": ["<종목>"], "period": "6m"}),
     _slot("stock_holders", "<종목> 담은 ETF", "bar", {"stocks": ["<종목>"], "top": 10})],
    [_slot("company_financials", "<종목> 분기 실적", "bar", {"stock": "<종목>", "basis": "quarter", "periods": 8}),
     _slot("company_disclosures", "<종목> 최근 공시", "markdown", {"stock": "<종목>", "days": 90})],
    [_slot("company_report", "<종목> 최근 보고서 요약", "markdown", {"stock": "<종목>"})],
    _narrative("<종목>의 최근 보고서가 설명하는 사업과 영업 상황을 중심으로 실적 추이, 주가 흐름, 담은 ETF, "
               "최근 공시를 사실 위주로 5문장으로 (투자 권유 없이)"),
)
OLD_ANALYSIS_DESCRIPTION = (
    "종목 하나를 '분석'해 달라면 주가 추이와 담은 ETF(ETF Atlas만의 데이터), DART 실적과 최근 공시를 나란히 두고 "
    "해설로 묶는다. 매수·매도 판단은 하지 않는다"
)
OLD_ANALYSIS_PLAN = _plan(
    [_slot("stock_trend", "<종목> 주가 추이", "line", {"stocks": ["<종목>"], "period": "6m"}),
     _slot("stock_holders", "<종목> 담은 ETF", "bar", {"stocks": ["<종목>"], "top": 10})],
    [_slot("company_financials", "<종목> 분기 실적", "bar", {"stock": "<종목>", "basis": "quarter", "periods": 8}),
     _slot("company_disclosures", "<종목> 최근 공시", "markdown", {"stock": "<종목>", "days": 90})],
    _narrative("<종목>의 주가 흐름, 담은 ETF, 실적 추이, 최근 공시를 사실 위주로 4문장으로 (투자 권유 없이)"),
)

# 임베딩은 embed_code_examples DAG가 채운다 (status='active' → 'embedded')
SEEDS = [
    {
        "question": "현대모비스는 무슨 사업을 하는 회사야?",
        "description": "무슨 사업을 하는지, 보고서에 뭐라고 나왔는지 물으면 최근 정기보고서 요약 하나와 해설",
        "plan": _plan(
            [_slot("company_report", "<종목> 최근 보고서 요약", "markdown", {"stock": "<종목>"})],
            _narrative("<종목>의 사업 구조와 매출 비중을 보고서 요약 기준으로 3문장으로"),
        ),
    },
]


def _update_analysis(plan, description) -> None:
    op.execute(sa.text("UPDATE layout_examples SET plan = :plan, description = :description WHERE question = :q")
               .bindparams(plan=json.dumps(plan, ensure_ascii=False), description=description, q=ANALYSIS_QUESTION))


def upgrade() -> None:
    op.create_table(
        'stock_report_summaries',
        sa.Column('rcept_no', sa.String(14), nullable=False),
        sa.Column('stock_code', sa.String(6), nullable=False),
        sa.Column('report_nm', sa.Text(), nullable=False),
        sa.Column('sections', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('model', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('rcept_no'),
    )
    op.create_index('ix_stock_report_summaries_stock_code', 'stock_report_summaries', ['stock_code'])

    _update_analysis(ANALYSIS_PLAN, ANALYSIS_DESCRIPTION)
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
    _update_analysis(OLD_ANALYSIS_PLAN, OLD_ANALYSIS_DESCRIPTION)
    op.drop_index('ix_stock_report_summaries_stock_code', table_name='stock_report_summaries')
    op.drop_table('stock_report_summaries')
