"""layout_examples: seed examples for the company analysis skills (DART financials and disclosures)

"<stock> 분석해줘" puts the price trend and the ETFs holding it next to the
DART quarterly results and recent disclosures, then a narrative.

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-19 16:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0025'
down_revision: Union[str, Sequence[str], None] = '0024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slot(skill, title, display, args, name=None):
    # 키 순서는 플래너 출력 스키마와 같게 (skill, name, title, display, args)
    return {"skill": skill, **({"name": name} if name else {}), "title": title, "display": display, "args": args}


def _plan(*rows):
    return {"rows": [{"slots": list(row)} for row in rows]}


def _narrative(instruction):
    return [_slot("narrative", "해설", "text", {"instruction": instruction})]


# 0013과 같은 원칙: 질문 유형마다 하나, 대상은 자리표시자, 평가 세트와 대상·문장이 겹치지 않게.
# 임베딩은 embed_code_examples DAG가 채운다 (status='active' → 'embedded')
SEEDS = [
    {
        "question": "삼성전자 기업 분석해줘",
        "description": "종목 하나를 '분석'해 달라면 주가 추이와 담은 ETF(ETF Atlas만의 데이터), DART 실적과 최근 공시를 나란히 두고 "
                       "해설로 묶는다. 매수·매도 판단은 하지 않는다",
        "plan": _plan(
            [_slot("stock_trend", "<종목> 주가 추이", "line", {"stocks": ["<종목>"], "period": "6m"}),
             _slot("stock_holders", "<종목> 담은 ETF", "bar", {"stocks": ["<종목>"], "top": 10})],
            [_slot("company_financials", "<종목> 분기 실적", "bar", {"stock": "<종목>", "basis": "quarter", "periods": 8}),
             _slot("company_disclosures", "<종목> 최근 공시", "markdown", {"stock": "<종목>", "days": 90})],
            _narrative("<종목>의 주가 흐름, 담은 ETF, 실적 추이, 최근 공시를 사실 위주로 4문장으로 (투자 권유 없이)"),
        ),
    },
    {
        "question": "LG화학 요즘 실적 어때?",
        "description": "실적만 물으면 주가·ETF 없이 실적과 그 실적 공시가 보이는 최근 공시만. 연간을 말하면 basis=year",
        "plan": _plan(
            [_slot("company_financials", "<종목> 분기 실적", "table", {"stock": "<종목>", "basis": "quarter", "periods": 8})],
            [_slot("company_disclosures", "<종목> 최근 공시", "markdown", {"stock": "<종목>", "days": 90, "limit": 10})],
            _narrative("<종목>의 최근 분기 실적과 전년 동기 대비 변화를 3문장으로"),
        ),
    },
    {
        "question": "기아 최근 공시 뭐 있어?",
        "description": "공시만 물으면 company_disclosures 하나와 해설. 해설은 공시 제목만 알고 본문은 모른다",
        "plan": _plan(
            [_slot("company_disclosures", "<종목> 최근 공시", "markdown", {"stock": "<종목>", "days": 30})],
            _narrative("<종목>의 최근 공시를 제목 기준으로 종류별로 2~3문장으로 정리 (본문 내용은 추측하지 않는다)"),
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


def downgrade() -> None:
    for s in SEEDS:
        op.execute(sa.text("DELETE FROM layout_examples WHERE question = :q").bindparams(q=s["question"]))
