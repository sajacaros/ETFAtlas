"""
DART Report Index DAG — 정기보고서를 목차 트리로 색인 (챗봇 company_report·company_revenue_mix)

PageIndex 방식: 원문 구조로 목차 트리를 만들고(LLM 없음), 등록된 LLM이 노드마다 '이 절에 든 항목' 한 줄 색인을
붙인다. 챗봇은 그 목차를 보고 질문에 맞는 절을 골라 읽는다. 파서와 요약 프롬프트는 backend의 app.services.report_tree.

1. queue_reports: 그래프 종목의 최근 1년 정기보고서(주요계정·공시 목록의 접수번호, 같은 기간이면 정정본)를
   stock_reports에 pending으로 올린다.
   첨부만 바꾼 공시([첨부정정]·[첨부추가])와 옛 기간의 정정본은 올리지 않고, 이미 올라 있으면 지운다.
2. build_trees: 원문 zip을 받아(stock_report_docs) 트리를 만든다 → tree. 파서 버전이 바뀐 보고서는 보관한 원문으로
   다시 만들고, 내용이 같은 노드(content_hash)는 요약을 이어받는다. DART가 원문을 주지 않는 접수번호(상태 014)는
   missing으로 두고 다시 받지 않는다 — 그 회사의 같은 기간 공시를 DART에서 다시 받아 두어, 다음 실행이 그 전 접수를 올린다.
3. summarize_nodes: 등록된 LLM(관리자 페이지 ai_settings, 추론 끔)으로 노드 요약 → summarized.
   처음에는 보고서가 수천 건이라 실행당 시간 예산 안에서 종목별 최신 보고서부터 한다. 트리만 있어도 챗봇은 제목으로 고른다.
   REPORT_SUMMARY_ENDPOINTS(환경변수, JSON 목록)에 같은 모델을 띄운 서버를 더 적으면 요약을 나눠 보낸다 (밀린 색인을 빨리 끝낼 때).
4. prune_reports: 정정본이 색인된 원래 보고서와 1년 지난 보고서(종목마다 최신 1건은 남긴다)를 지운다.
5. make_overviews: 종목별 최신 보고서(챗봇 company_report가 고르는 것)의 개요(사업 구조·영업 상황·위험 요인·소송)를
   등록된 LLM으로 만들어 stock_reports.overview에 남긴다. 매수 의견(stock_opinion)이 개요를 읽으므로 질문이 오기 전에 채워 둔다.

본문은 report_index.py에 있다.
"""

from datetime import datetime, timedelta

from airflow.sdk import DAG
from airflow.providers.standard.operators.python import PythonOperator

import report_index
from report_index import BUILD_MINUTES, OVERVIEW_MINUTES, SUMMARY_MINUTES

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=10),
    'email_on_failure': False,
}

dag = DAG(
    'dart_report_index',
    default_args=default_args,
    description='DART 정기보고서 목차 트리 색인 (원문 → 트리 → 등록 LLM 노드 요약 → 최신 보고서 개요)',
    schedule='0 21 * * *',  # 매일 21:00 KST — dart_sync_rdb(평일 19:20)가 공시·주요계정을 받은 뒤. 주말엔 밀린 요약을 한다
    catchup=False,
    max_active_runs=1,
    # 배포하면 바로 21:00부터 돈다 — 색인 전에는 company_report가 답하지 못한다. 이미 색인한 보고서는 다시 하지 않는다
    is_paused_upon_creation=False,
    tags=['dart', 'daily', 'rdb', 'llm'],
)


t_queue = PythonOperator(task_id='queue_reports', python_callable=report_index.queue_reports, dag=dag)
t_trees = PythonOperator(task_id='build_trees', python_callable=report_index.build_trees, dag=dag,
                         execution_timeout=timedelta(minutes=BUILD_MINUTES + 30))
t_summaries = PythonOperator(task_id='summarize_nodes', python_callable=report_index.summarize_nodes, dag=dag,
                             execution_timeout=timedelta(minutes=SUMMARY_MINUTES + 30))
t_prune = PythonOperator(task_id='prune_reports', python_callable=report_index.prune_reports, dag=dag)
t_overviews = PythonOperator(task_id='make_overviews', python_callable=report_index.make_overviews, dag=dag,
                             execution_timeout=timedelta(minutes=OVERVIEW_MINUTES + 30))

t_queue >> t_trees >> t_summaries >> t_prune >> t_overviews
