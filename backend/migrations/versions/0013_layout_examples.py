"""layout_examples: few-shot examples for the chatbot layout planner, with seed examples

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-13 10:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slot(skill, title, display, args, name=None):
    # 키 순서는 플래너 출력 스키마와 같게 (skill, name, title, display, args)
    slot = {"skill": skill, **({"name": name} if name else {}), "title": title, "display": display, "args": args}
    return slot


def _plan(*rows):
    return {"rows": [{"slots": list(row)} for row in rows]}


# 시드 예시: 질문 유형(스킬 조합·참조 패턴)마다 하나씩. 한 유형에 몰리면 무관한 질문에도 그 예시가 붙는다.
# 대상 이름은 자리표시자로 두고(플래너가 현재 질문의 값으로 바꾼다), 평가 세트(evals/layout_eval.json)와 대상·문장이 겹치지 않게 한다.
# 설명에는 스킬의 개수 제한 같은 숫자를 적지 않는다 — 제한이 바뀌면 틀린 설명이 되고, 정확한 숫자는 검증 오류가 알려 준다.
# 임베딩은 embed_code_examples DAG가 채운다 (status='active' → 'embedded')
def _narrative(instruction):
    return [_slot("narrative", "해설", "text", {"instruction": instruction})]


SEEDS = [
    # ── 종목 → ETF 순위 ──
    {
        "question": "삼성전자를 가장 많이 보유한 ETF는?",
        "description": "종목 비중 순위만 물으면 stock_holders 하나와 해설",
        "plan": _plan(
            [_slot("stock_holders", "<종목> 비중 상위 ETF", "bar", {"stocks": ["<종목>"]})],
            _narrative("<종목> 비중이 높은 ETF와 그 차이를 3문장으로"),
        ),
    },
    {
        "question": "테스와 원익IPS를 가장 많이 보유한 ETF는?",
        "description": "여러 종목을 함께 많이 담은 ETF는 종목마다 슬롯을 나누지 않고 stock_holders 하나에 모두 넣는다 (비중 합계 순)",
        "plan": _plan(
            [_slot("stock_holders", "<종목1>·<종목2> 비중 합계 상위 ETF", "bar", {"stocks": ["<종목1>", "<종목2>"]})],
            _narrative("두 종목의 비중 합계가 높은 ETF와 종목별 비중 차이를 3문장으로"),
        ),
    },
    # ── 순위 결과를 다른 슬롯이 이어받기 (참조) ──
    {
        "question": "삼성전자를 가장 많이 보유한 ETF와 해당 ETF의 구성종목 상위 10개 알려줘",
        "description": "아직 모르는 1위 ETF는 순위 슬롯에 name을 붙이고 '@rank.1'로 받는다",
        "plan": _plan(
            [_slot("stock_holders", "<종목> 비중 상위 ETF", "bar", {"stocks": ["<종목>"]}, name="rank")],
            [_slot("holdings", "1위 ETF 구성종목", "treemap", {"etf": "@rank.1", "top": 10})],
            _narrative("<종목> 비중 1위 ETF와 그 구성종목의 특징을 3문장으로"),
        ),
    },
    {
        "question": "테스와 원익IPS를 많이 담은 ETF의 구성종목 보여줘",
        "description": "여러 종목의 비중 합계 1위 ETF를 '@rank.1'로 받아 구성종목을 보여 준다",
        "plan": _plan(
            [_slot("stock_holders", "<종목1>·<종목2> 비중 합계 상위 ETF", "bar",
                   {"stocks": ["<종목1>", "<종목2>"]}, name="rank")],
            [_slot("holdings", "1위 ETF 구성종목", "treemap", {"etf": "@rank.1"})],
            _narrative("두 종목 비중 합계 1위 ETF와 그 구성종목의 특징을 3문장으로"),
        ),
    },
    {
        "question": "삼성전자 비중 상위 10개 ETF의 기간별 수익률을 비교해줘",
        "description": "순위 N개 전부를 목록 인자로 넘길 때 한 슬롯에 다 들어가지 않으면, 같은 스킬 슬롯을 여럿 만들어 "
                       "순위를 빠짐없이 이어서 나눠 담는다. stock_holders의 top은 요청한 개수로",
        "plan": _plan(
            [_slot("stock_holders", "<종목> 비중 상위 ETF", "table", {"stocks": ["<종목>"], "top": 10}, name="rank")],
            [_slot("period_returns", "1~5위 기간별 수익률", "bar", {"etfs": ["@rank.1-5"]}),
             _slot("period_returns", "6~10위 기간별 수익률", "bar", {"etfs": ["@rank.6-10"]})],
            _narrative("<종목> 비중 상위 ETF들의 기간별 수익률 차이를 3문장으로"),
        ),
    },
    {
        "question": "원익IPS를 많이 담은 ETF 상위 3개의 구성종목을 각각 보여줘",
        "description": "순위마다 하나씩('각각') 보여 줄 때, 대상 하나만 받는 스킬은 순위마다 슬롯을 만든다",
        "plan": _plan(
            [_slot("stock_holders", "<종목> 비중 상위 ETF", "bar", {"stocks": ["<종목>"], "top": 3}, name="rank")],
            [_slot("holdings", "1위 ETF 구성종목", "treemap", {"etf": "@rank.1"}),
             _slot("holdings", "2위 ETF 구성종목", "treemap", {"etf": "@rank.2"}),
             _slot("holdings", "3위 ETF 구성종목", "treemap", {"etf": "@rank.3"})],
            _narrative("<종목> 비중 상위 ETF들의 구성종목 차이를 3문장으로"),
        ),
    },
    {
        "question": "한미반도체 비중 상위 8개 ETF를 TIGER 반도체와 함께 가격 추이 비교해줘",
        "description": "이름으로 지정한 ETF와 순위 결과를 함께 비교할 때, 지정한 ETF를 슬롯마다 넣고 남은 자리에 순위를 빠짐없이 이어서 나눠 담는다",
        "plan": _plan(
            [_slot("stock_holders", "<종목> 비중 상위 ETF", "table", {"stocks": ["<종목>"], "top": 8}, name="rank")],
            [_slot("price_trend", "<ETF>와 1~4위", "line", {"etfs": ["<ETF>", "@rank.1-4"]}),
             _slot("price_trend", "<ETF>와 5~8위", "line", {"etfs": ["<ETF>", "@rank.5-8"]})],
            _narrative("<ETF>와 <종목> 비중 상위 ETF들의 가격 흐름 차이를 3문장으로"),
        ),
    },
    {
        "question": "TIGER 반도체 비중 1위 종목의 주가 추이 보여줘",
        "description": "ETF 구성종목 순위를 받아 종목 스킬로 넘길 때도 같은 참조를 쓴다",
        "plan": _plan(
            [_slot("holdings", "<ETF> 구성종목", "bar", {"etf": "<ETF>"}, name="top")],
            [_slot("stock_trend", "1위 종목 주가 추이", "line", {"stocks": ["@top.1"]})],
            _narrative("<ETF> 비중 1위 종목의 주가 흐름을 3문장으로"),
        ),
    },
    # ── ETF 하나·여럿 ──
    {
        "question": "TIGER 반도체 구성종목 보여줘",
        "description": "이름이 주어진 ETF 하나의 구성종목은 holdings 하나",
        "plan": _plan(
            [_slot("holdings", "<ETF> 구성종목", "treemap", {"etf": "<ETF>"})],
            _narrative("<ETF> 구성종목의 특징을 3문장으로"),
        ),
    },
    {
        "question": "TIGER 반도체와 ACE 200 비교해줘",
        "description": "ETF 비교는 기본 정보 비교표와 기간별 수익률. 같은 데이터를 표시만 바꿔 다시 넣지 않는다",
        "plan": _plan(
            [_slot("etf_compare", "기본 정보 비교", "table", {"etfs": ["<ETF1>", "<ETF2>"]})],
            [_slot("period_returns", "기간별 수익률", "bar", {"etfs": ["<ETF1>", "<ETF2>"]})],
            _narrative("두 ETF의 보수·규모·수익률 차이를 3문장으로"),
        ),
    },
    {
        "question": "ACE 200 3개월 가격 추이 보여줘",
        "description": "가격 추이는 price_trend 하나. 기간은 질문에 맞춘다",
        "plan": _plan(
            [_slot("price_trend", "<ETF> 3개월 가격 추이", "line", {"etfs": ["<ETF>"], "period": "3m"})],
            _narrative("<ETF>의 기간 중 가격 흐름을 3문장으로"),
        ),
    },
    {
        "question": "TIGER 반도체 1개월 봉차트",
        "description": "봉차트를 말하면 price_trend의 candlestick 하나. 다른 차트를 덧붙이지 않는다",
        "plan": _plan(
            [_slot("price_trend", "<ETF> 1개월 일봉", "candlestick", {"etfs": ["<ETF>"], "period": "1m"})],
            _narrative("<ETF>의 기간 중 가격 움직임을 3문장으로"),
        ),
    },
    {
        "question": "삼성전자 주가 3개월 추이",
        "description": "개별 종목(ETF가 아닌 주식) 가격은 stock_trend",
        "plan": _plan(
            [_slot("stock_trend", "<종목> 3개월 주가", "line", {"stocks": ["<종목>"], "period": "3m"})],
            _narrative("<종목>의 기간 중 주가 흐름을 3문장으로"),
        ),
    },
    {
        "question": "TIGER 반도체 50%, ACE 200 50%로 담으면 종목 비중이 어떻게 돼?",
        "description": "비중이 적힌 포트폴리오의 종목 노출은 portfolio_lookthrough 하나 (ETF마다 holdings를 만들지 않는다)",
        "plan": _plan(
            [_slot("portfolio_lookthrough", "종목별 합산 비중", "treemap",
                   {"items": [{"asset": "<ETF1>", "allocation": 50}, {"asset": "<ETF2>", "allocation": 50}]})],
            _narrative("포트폴리오의 실제 종목 노출과 겹치는 종목을 3문장으로"),
        ),
    },
    # ── 대상을 하나로 정할 수 없을 때: 되묻기 ──
    {
        "question": "반도체 ETF 구성종목 보여줘",
        "description": "ETF 하나가 필요한데 업종·테마로만 주어지면 고르지 않고 etf_choice(by=theme) 하나로 되묻는다",
        "plan": _plan(
            [_slot("etf_choice", "ETF 선택", "markdown", {"by": "theme", "condition": "<테마>", "purpose": "구성종목"})],
        ),
    },
    {
        "question": "원익IPS가 들어간 ETF의 수익률 추이 보여줘",
        "description": "ETF 하나가 필요한데 '어떤 종목을 담은 ETF'로만 주어지면 etf_choice(by=stock) 하나로 되묻는다",
        "plan": _plan(
            [_slot("etf_choice", "ETF 선택", "markdown", {"by": "stock", "condition": "<종목>", "purpose": "수익률 추이"})],
        ),
    },
    # ── 스킬로 안 되는 질문 ──
    {
        "question": "미래에셋자산운용 ETF 목록 보여줘",
        "description": "운용사·태그별 ETF 목록처럼 스킬이 없는 질문은 agent 하나 (해설을 붙이지 않는다)",
        "plan": _plan(
            [_slot("agent", "<운용사> ETF 목록", "markdown", {"question": "<운용사> ETF 목록 보여줘"})],
        ),
    },
    {
        "question": "TIGER 반도체 구성종목 비중이 지난주랑 비교해서 어떻게 바뀌었어?",
        "description": "보유 비중의 시간에 따른 변화는 현재 구성만 보여 주는 holdings로 답할 수 없어 agent 하나",
        "plan": _plan(
            [_slot("agent", "<ETF> 구성 변화", "markdown",
                   {"question": "<ETF> 구성종목 비중이 지난주와 비교해 어떻게 바뀌었는지 알려줘"})],
        ),
    },
]


def upgrade() -> None:
    op.create_table(
        'layout_examples',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('question_generalized', sa.Text(), nullable=True),
        sa.Column('plan', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='active'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    # pgvector 타입은 SQLAlchemy 모델에 없어 직접 만든다 (code_examples와 같은 768차원)
    op.execute("ALTER TABLE layout_examples ADD COLUMN embedding vector(768)")
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
    op.drop_table('layout_examples')
