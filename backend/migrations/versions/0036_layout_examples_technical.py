"""layout_examples: seed examples for chart analysis (stock_technical)

"<stock> 주가 분석해줘" matched the company analysis example and pulled in the
periodic report, results and disclosures. Price questions now get the chart
analysis skill alone — candles with moving averages, Bollinger bands, volume and
an indicator pane — and a narrative that goes through each indicator. The
company analysis example says so, so the two stay apart.

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-27 18:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0036'
down_revision: Union[str, Sequence[str], None] = '0035'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ANALYSIS = "삼성전자 기업 분석해줘"
ANALYSIS_NOTE = " 주가·차트 분석만 물으면 이 구성이 아니라 stock_technical"


def _slot(skill, title, display, args):
    # 키 순서는 플래너 출력 스키마와 같게 (skill, name, title, display, args)
    return {"skill": skill, "title": title, "display": display, "args": args}


def _plan(*rows):
    return {"rows": [{"slots": list(row)} for row in rows]}


def _narrative(instruction):
    return [_slot("narrative", "해설", "text", {"instruction": instruction})]


# 0013과 같은 원칙: 질문 유형마다 하나, 대상은 자리표시자, 평가 세트와 대상·문장이 겹치지 않게.
# 임베딩은 embed_code_examples DAG가 채운다 (status='active' → 'embedded')
SEEDS = [
    {
        "question": "삼성전자 주가 분석해줘",
        "description": "종목 하나의 '주가 분석'·차트 분석은 stock_technical 하나와 지표별 해설. "
                       "정기보고서·실적·공시는 넣지 않는다 (기업 분석과 다르다). 매수·매도 판단은 하지 않는다",
        "plan": _plan(
            [_slot("stock_technical", "<종목> 차트 분석", "candlestick", {"stock": "<종목>"})],
            _narrative("<종목>의 기간 중 주가 흐름을 한 문장으로 쓰고, 이어서 **이동평균**, **MACD**, **RSI**, **스토캐스틱** "
                       "관점을 굵은 머리말로 하나씩 1~2문장씩 (요약의 지표 값과 기준만으로, 앞으로의 방향이나 매수·매도 판단 없이)"),
        ),
    },
    {
        "question": "삼성전자 RSI 어때?",
        "description": "보조지표 하나를 콕 집어 물으면 stock_technical의 first를 그 지표로 두고, 해설도 그 지표 중심으로",
        "plan": _plan(
            [_slot("stock_technical", "<종목> RSI", "candlestick", {"stock": "<종목>", "first": "rsi"})],
            _narrative("<종목>의 RSI(14) 현재 값과 구간, 최근 변화, 기간 중 과매수·과매도 기준을 넘은 날을 2~3문장으로 "
                       "(앞으로의 방향이나 매수·매도 판단 없이)"),
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
    op.execute(sa.text("UPDATE layout_examples SET description = description || :note WHERE question = :q")
               .bindparams(note=ANALYSIS_NOTE, q=ANALYSIS))


def downgrade() -> None:
    for s in SEEDS:
        op.execute(sa.text("DELETE FROM layout_examples WHERE question = :q").bindparams(q=s["question"]))
    op.execute(sa.text("UPDATE layout_examples SET description = replace(description, :note, '') WHERE question = :q")
               .bindparams(note=ANALYSIS_NOTE, q=ANALYSIS))
