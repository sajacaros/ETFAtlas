"""
ETF 태깅 DAG (Apache AGE)

아직 자동 태깅되지 않은 ETF(ETF.tagged_at 없음, 즉 신규 편입)만 룰 기반 + 키워드 + LLM으로 태깅한다.
이미 태깅된 ETF는 매주 다시 LLM에 돌리지 않는다 — LLM 결과가 실행마다 달라 태그가 흔들리기 때문.
규칙이나 태그 목록을 바꿨으면 params.full_rebuild=true로 수동 실행해 전체를 다시 태깅한다.
관리자가 수동 지정한 ETF(ETF.manual_tags)는 규칙/LLM을 건너뛰고 지정한 태그를 그대로 쓴다.
LLM 접속 설정 필요 (관리자 페이지 또는 LLM_API_* 환경변수, LiteLLM 프록시). 수동 트리거 또는 주간 스케줄.
"""

from datetime import datetime, timedelta
from airflow.sdk import DAG, Param
from airflow.providers.standard.operators.python import PythonOperator

from age_db import AGE_WRITE_POOL
from etf_tagging import tag_all_etfs as run_tagging

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'email_on_failure': False,
}

dag = DAG(
    'age_tagging',
    default_args=default_args,
    description='신규 ETF 태깅 (룰 + LLM), full_rebuild로 전체 재태깅',
    schedule='0 3 * * 6',  # 토요일 03:00 KST
    catchup=False,
    params={'full_rebuild': Param(False, type='boolean',
                                  description='이미 태깅된 ETF까지 전체 다시 태깅')},
    tags=['etf', 'weekly', 'age', 'tagging'],
)


def tag_all_etfs(**context):
    """대상 ETF 태깅 (etf_tagging.tag_all_etfs). full_rebuild면 이미 태깅된 ETF까지."""
    run_tagging(full_rebuild=bool(context['params'].get('full_rebuild')))


# ── DAG 태스크 정의 ──

PythonOperator(
    task_id='tag_all_etfs',
    python_callable=tag_all_etfs,
    execution_timeout=timedelta(minutes=30),
    pool=AGE_WRITE_POOL,
    dag=dag,
)
