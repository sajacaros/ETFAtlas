"""
AGE 초기 데이터 백필 DAG — 고정 시작일(2026-01-02) ~ 최근 영업일

신규 환경 구축 시 수동 트리거하여 모든 AGE 데이터를 일괄 수집.
이후 age_sync_universe DAG이 증분 수집을 이어받음.
태그는 age_tagging DAG에서 별도 부여.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import logging

from age_utils import (
    get_db_connection, init_age, execute_cypher,
    get_business_days, get_etf_codes_from_age,
    collect_universe_and_prices, collect_holdings_for_dates,
    collect_stock_prices_for_dates,
    update_etf_returns,
)

log = logging.getLogger(__name__)

BACKFILL_START = "20260102"

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2026, 1, 1),
    'retries': 0,
    'email_on_failure': False,
}

dag = DAG(
    'age_backfill',
    default_args=default_args,
    description='AGE 초기 데이터 백필 (유니버스/가격/HOLDS/수익률)',
    schedule_interval=None,
    catchup=False,
    tags=['etf', 'backfill', 'age'],
)


def get_dates(**context):
    today = datetime.now().strftime('%Y%m%d')
    dates = get_business_days(BACKFILL_START, today)
    log.info(f"Backfill: {len(dates)} business days ({BACKFILL_START} ~ {today})")
    return dates


def cleanup_graph(**context):
    """기존 HOLDS 엣지 삭제 (백필 전 초기화).

    이어서 수집 시(HOLDS 데이터가 이미 존재) cleanup을 건너뜀.
    """
    conn = get_db_connection()
    cur = init_age(conn)
    try:
        # 이미 HOLDS가 있으면 이어서 수집 모드 → cleanup 건너뜀
        results = execute_cypher(cur, """
            MATCH ()-[h:HOLDS]->()
            RETURN h.date
            LIMIT 1
        """)
        if results and results[0][0]:
            log.info("Existing HOLDS data found — skipping cleanup (resume mode)")
            return

        execute_cypher(cur, """
            MATCH ()-[h:HOLDS]->()
            DELETE h
            RETURN count(*)
        """)
        conn.commit()
        log.info("Deleted all existing HOLDS edges")
    finally:
        cur.close()
        conn.close()


def backfill_universe_and_prices(**context):
    dates = context['ti'].xcom_pull(task_ids='get_dates')
    if not dates:
        return
    collect_universe_and_prices(dates)


def _get_existing_holds_dates() -> set[str]:
    """AGE에서 이미 HOLDS가 있는 날짜 집합 조회 (YYYYMMDD)."""
    conn = get_db_connection()
    cur = init_age(conn)
    try:
        results = execute_cypher(cur, """
            MATCH ()-[h:HOLDS]->()
            WITH DISTINCT h.date AS d
            RETURN d
        """)
        dates_set = set()
        for row in results:
            if row[0]:
                raw = str(row[0]).strip('"')
                dates_set.add(raw.replace('-', ''))
        return dates_set
    finally:
        cur.close()
        conn.close()


def backfill_holds(**context):
    dates = context['ti'].xcom_pull(task_ids='get_dates')
    if not dates:
        return

    existing = _get_existing_holds_dates()
    remaining = [d for d in dates if d not in existing]
    log.info(f"HOLDS: {len(existing)} dates already collected, "
             f"{len(remaining)} remaining out of {len(dates)}")

    if not remaining:
        log.info("All HOLDS dates already collected — skipping")
        return

    etf_codes = list(get_etf_codes_from_age())
    collect_holdings_for_dates(etf_codes, remaining)


def backfill_stock_prices(**context):
    dates = context['ti'].xcom_pull(task_ids='get_dates')
    if not dates:
        return
    collect_stock_prices_for_dates(dates)


def backfill_returns(**context):
    update_etf_returns()
    log.info("Backfill complete. Run 'age_tagging' DAG to apply ETF tags.")


# ── DAG 태스크 정의 ──

t1 = PythonOperator(task_id='get_dates', python_callable=get_dates, dag=dag)
t2 = PythonOperator(task_id='cleanup_graph', python_callable=cleanup_graph, dag=dag)
t3 = PythonOperator(task_id='backfill_universe_and_prices',
                     python_callable=backfill_universe_and_prices,
                     execution_timeout=timedelta(hours=1), dag=dag)
t4 = PythonOperator(task_id='backfill_holds',
                     python_callable=backfill_holds,
                     execution_timeout=timedelta(hours=6), dag=dag)
t5 = PythonOperator(task_id='backfill_stock_prices',
                     python_callable=backfill_stock_prices,
                     execution_timeout=timedelta(hours=3), dag=dag)
t6 = PythonOperator(task_id='backfill_returns',
                     python_callable=backfill_returns, dag=dag)

t1 >> t2 >> t3 >> t4 >> t5 >> t6
