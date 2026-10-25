"""periodic reports as a table-of-contents tree (stock_reports, report_nodes) instead of a summary cache

company_report read four chapters of the latest report, clipped to 36k characters,
and cached one fixed-shape summary, so it could not answer anything outside that
summary (R&D spend, headcount, largest shareholder, ...). Reports are now indexed
ahead of time by the dart_report_index DAG the PageIndex way: the original zip is
kept, the document becomes a tree of chapters and sections whose bodies are stored
as blocks (headings, paragraphs, tables with merged cells resolved), and the
registered LLM writes a one-line index for each node. company_report picks nodes
from that tree for the question. stock_report_summaries goes away; the overview
and revenue-mix caches move onto stock_reports.

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-25 18:00:00.000000
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0033'
down_revision: Union[str, Sequence[str], None] = '0032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slot(skill, title, display, args):
    return {"skill": skill, "title": title, "display": display, "args": args}


def _lookup(need, title, instruction):
    return {"rows": [
        {"slots": [_slot("company_report", f"<종목> {title}", "markdown", {"stock": "<종목>", "need": need})]},
        {"slots": [_slot("narrative", "해설", "text", {"instruction": instruction})]},
    ]}


LOOKUP_DESCRIPTION = (
    "정기보고서에 적힌 특정 사실(연구개발비, 직원 수·급여, 최대주주, 배당, 소송·제재, 원재료·가동률, 시설투자, 임원 보수, "
    "자기주식 등)을 물으면 company_report에 need로 찾을 것을 한 줄로 적은 슬롯 하나와 짧은 해설. 매출·영업이익 같은 주요계정 "
    "수치는 company_financials"
)
# 임베딩은 embed_code_examples DAG가 채운다 (status='active' → 'embedded')
SEEDS = [
    {
        "question": "삼성전자 연구개발비 얼마나 써?",
        "description": LOOKUP_DESCRIPTION,
        "plan": _lookup("연구개발비용과 매출액 대비 비율", "연구개발비",
                        "보고서에서 찾은 <종목>의 연구개발비와 매출 대비 비율을, 어느 보고서인지 이름을 밝혀 1~2문장으로"),
    },
    {
        "question": "SK하이닉스 직원 수랑 평균 연봉 알려줘",
        "description": LOOKUP_DESCRIPTION,
        "plan": _lookup("직원 수와 1인 평균 급여액", "직원 현황",
                        "보고서에서 찾은 <종목>의 직원 수와 1인 평균 급여를, 어느 보고서 기준인지 밝혀 1~2문장으로"),
    },
    {
        "question": "현대차 최대주주가 누구야?",
        "description": LOOKUP_DESCRIPTION,
        "plan": _lookup("최대주주와 특수관계인 지분율", "최대주주",
                        "보고서에서 찾은 <종목>의 최대주주와 지분율을, 어느 보고서 기준인지 밝혀 1~2문장으로"),
    },
]


def upgrade() -> None:
    op.create_table(
        'stock_reports',
        sa.Column('rcept_no', sa.String(14), nullable=False),
        sa.Column('stock_code', sa.String(6), nullable=False),
        sa.Column('report_nm', sa.Text(), nullable=False),
        sa.Column('period', sa.String(7), nullable=True),
        sa.Column('status', sa.String(12), nullable=False, server_default='pending'),
        sa.Column('parser_version', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('indexed_at', sa.DateTime(), nullable=True),
        sa.Column('summarized_at', sa.DateTime(), nullable=True),
        sa.Column('overview', sa.Text(), nullable=True),
        sa.Column('breakdowns', sa.Text(), nullable=True),
        sa.Column('model', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('rcept_no'),
    )
    op.create_index('ix_stock_reports_stock_code', 'stock_reports', ['stock_code'])
    op.create_table(
        'stock_report_docs',
        sa.Column('rcept_no', sa.String(14), sa.ForeignKey('stock_reports.rcept_no', ondelete='CASCADE'), nullable=False),
        sa.Column('zip', sa.LargeBinary(), nullable=False),
        sa.Column('fetched_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('rcept_no'),
    )
    op.create_table(
        'report_nodes',
        sa.Column('rcept_no', sa.String(14), sa.ForeignKey('stock_reports.rcept_no', ondelete='CASCADE'), nullable=False),
        sa.Column('node_id', sa.String(24), nullable=False),
        sa.Column('parent_id', sa.String(24), nullable=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('level', sa.Integer(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('chars', sa.Integer(), nullable=False),
        sa.Column('blocks', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(40), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('summary_model', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('rcept_no', 'node_id'),
    )
    op.drop_index('ix_stock_report_summaries_stock_code', table_name='stock_report_summaries')
    op.drop_table('stock_report_summaries')

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
    # 요약 캐시는 비어 있는 채로 되살린다 — 처음 물을 때 다시 만든다
    op.create_table(
        'stock_report_summaries',
        sa.Column('rcept_no', sa.String(14), nullable=False),
        sa.Column('stock_code', sa.String(6), nullable=False),
        sa.Column('report_nm', sa.Text(), nullable=False),
        sa.Column('sections', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('breakdowns', sa.Text(), nullable=True),
        sa.Column('model', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('rcept_no'),
    )
    op.create_index('ix_stock_report_summaries_stock_code', 'stock_report_summaries', ['stock_code'])
    op.drop_table('report_nodes')
    op.drop_table('stock_report_docs')
    op.drop_index('ix_stock_reports_stock_code', table_name='stock_reports')
    op.drop_table('stock_reports')
