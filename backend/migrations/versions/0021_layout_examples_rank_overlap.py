"""layout_examples: seed examples for the rank and overlap skills and the weight filter

Chained questions that pick from an earlier result by a number (return, fee,
net assets, weight threshold) and questions about the holdings two ETFs share.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-17 22:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0021'
down_revision: Union[str, Sequence[str], None] = '0020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slot(skill, title, display, args, name=None):
    # 키 순서는 플래너 출력 스키마와 같게 (skill, name, title, display, args)
    return {"skill": skill, **({"name": name} if name else {}), "title": title, "display": display, "args": args}


def _plan(*rows):
    return {"rows": [{"slots": list(row)} for row in rows]}


def _narrative(instruction):
    return [_slot("narrative", "해설", "text", {"instruction": instruction})]


# 0013과 같은 원칙: 질문 유형마다 하나, 대상은 자리표시자, 평가 세트(evals/answer_eval.json)와 대상·문장이 겹치지 않게.
# 임베딩은 embed_code_examples DAG가 채운다 (status='active' → 'embedded')
SEEDS = [
    # ── 앞 결과를 수치로 다시 고르기 (rank) ──
    {
        "question": "삼성전자를 담은 ETF 중 1개월 수익률이 가장 높은 ETF 3개의 구성종목 보여줘",
        "description": "앞 순위와 다른 기준(수익률·보수·순자산)으로 다시 고를 때는 순위 슬롯의 결과를 넉넉히 받아 rank로 고르고, "
                       "rank의 결과를 다시 참조로 받는다",
        "plan": _plan(
            [_slot("stock_holders", "<종목> 담은 ETF", "table", {"stocks": ["<종목>"], "top": 30}, name="holders")],
            [_slot("rank", "1개월 수익률 상위 ETF", "bar",
                   {"kind": "etf", "targets": ["@holders.1-30"], "by": "return_1m", "top": 3}, name="best")],
            [_slot("holdings", "1위 ETF 구성종목", "treemap", {"etf": "@best.1"}),
             _slot("holdings", "2위 ETF 구성종목", "treemap", {"etf": "@best.2"}),
             _slot("holdings", "3위 ETF 구성종목", "treemap", {"etf": "@best.3"})],
            _narrative("<종목>을 담은 ETF 중 수익률 상위 ETF들과 그 구성종목 차이를 3문장으로"),
        ),
    },
    {
        "question": "반도체 ETF 중 총보수가 가장 낮은 3개 비교해줘",
        "description": "테마 ETF를 수치 기준으로 고를 때는 되묻지 않고 rank에 theme을 적는다 (낮은 쪽이면 order=asc)",
        "plan": _plan(
            [_slot("rank", "<테마> ETF 총보수 낮은 순", "table",
                   {"kind": "etf", "theme": "<테마>", "by": "expense_ratio", "order": "asc", "top": 3}, name="cheap")],
            [_slot("etf_compare", "기본 정보 비교", "table", {"etfs": ["@cheap.1-3"]})],
            _narrative("총보수가 낮은 <테마> ETF들의 차이를 3문장으로"),
        ),
    },
    {
        "question": "TIGER 반도체 구성종목 중 1개월 동안 가장 많이 오른 3개 종목의 주가 추이",
        "description": "ETF 구성종목을 수익률로 다시 고를 때는 holdings 결과를 rank(kind=stock)로 받는다",
        "plan": _plan(
            [_slot("holdings", "<ETF> 구성종목", "bar", {"etf": "<ETF>", "top": 30}, name="top")],
            [_slot("rank", "1개월 상승률 상위 종목", "bar",
                   {"kind": "stock", "targets": ["@top.1-30"], "by": "return_1m", "top": 3}, name="gainers")],
            [_slot("stock_trend", "상승률 상위 종목 주가 추이", "line", {"stocks": ["@gainers.1-3"], "period": "1m"})],
            _narrative("<ETF> 구성종목 중 많이 오른 종목들의 흐름을 3문장으로"),
        ),
    },
    # ── 비중 조건으로 거르기 (min_weight) ──
    {
        "question": "삼성전자 비중이 30% 넘는 ETF 보여줘",
        "description": "'비중 N% 넘는'처럼 비중 조건이 있으면 순위 스킬의 min_weight로 거른다",
        "plan": _plan(
            [_slot("stock_holders", "<종목> 비중 <N>% 이상 ETF", "bar",
                   {"stocks": ["<종목>"], "top": 30, "min_weight": 30})],
            _narrative("<종목> 비중이 <N>% 넘는 ETF들의 특징을 3문장으로"),
        ),
    },
    {
        "question": "ACE 200 70%, TIGER 반도체 30% 포트폴리오에서 합산 비중 5% 이상 종목만 주가 추이 보여줘",
        "description": "조건으로 거른 결과는 개수를 미리 모르므로, 받는 슬롯을 순위별로 나누지 않고 하나만 만든다",
        "plan": _plan(
            [_slot("portfolio_lookthrough", "합산 비중 <N>% 이상 종목", "table",
                   {"items": [{"asset": "<ETF1>", "allocation": 70}, {"asset": "<ETF2>", "allocation": 30}],
                    "min_weight": 5}, name="pf")],
            [_slot("stock_trend", "주가 추이", "line", {"stocks": ["@pf.1-5"]})],
            _narrative("합산 비중이 큰 종목들의 주가 흐름을 3문장으로"),
        ),
    },
    # ── 두 ETF 구성 겹침 (overlap) ──
    {
        "question": "TIGER 반도체와 ACE 200 구성종목 얼마나 겹쳐?",
        "description": "비중 없이 ETF 두 개만 주고 공통·단독 종목과 겹침을 물으면 holdings 두 개가 아니라 overlap 하나로 계산한다 "
                       "(ETF마다 비중이 적힌 포트폴리오면 portfolio_lookthrough)",
        "plan": _plan(
            [_slot("overlap", "<ETF1>·<ETF2> 구성 겹침", "table", {"etfs": ["<ETF1>", "<ETF2>"]})],
            _narrative("두 ETF가 얼마나 겹치고 무엇이 다른지 3문장으로"),
        ),
    },
    {
        "question": "TIGER 반도체와 SOL AI반도체소부장에 공통으로 들어 있는 종목 주가 추이",
        "description": "두 ETF의 공통 종목을 다른 슬롯에 넘길 때는 overlap 결과를 참조로 받는다 (개수를 미리 모르므로 슬롯 하나)",
        "plan": _plan(
            [_slot("overlap", "<ETF1>·<ETF2> 공통 종목", "table", {"etfs": ["<ETF1>", "<ETF2>"]}, name="common")],
            [_slot("stock_trend", "공통 종목 주가 추이", "line", {"stocks": ["@common.1-5"]})],
            _narrative("두 ETF 공통 종목의 주가 흐름을 3문장으로"),
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
