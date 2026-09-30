"""
AGE 초기 데이터 적재 DAG — 고정 시작일(2026-01-02) ~ 최근 영업일

신규 환경 구축 시 수동 트리거하여 유니버스/ETF 가격/주식 가격 이력을 일괄 수집.
구성종목(HOLDS)은 KIS API가 날짜 지정을 지원하지 않아 현재 스냅샷 1회만 수집한다
(과거 구성종목 백필 없음).
이후 age_sync_universe DAG이 증분 수집을 이어받음.
태그는 age_tagging DAG에서 별도 부여.
"""

from datetime import datetime, timedelta
from airflow.sdk import DAG
from airflow.providers.standard.operators.python import PythonOperator
import logging

from age_utils import (
    get_business_days, get_etf_codes_from_age,
    collect_universe_and_prices, collect_holdings,
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
    description='AGE 초기 데이터 적재 (유니버스/가격 이력, 현재 HOLDS, 수익률)',
    schedule=None,
    catchup=False,
    tags=['etf', 'backfill', 'age'],
)


def get_dates(**context):
    today = datetime.now().strftime('%Y%m%d')
    dates = get_business_days(BACKFILL_START, today)
    log.info(f"Backfill: {len(dates)} business days ({BACKFILL_START} ~ {today})")
    return dates


def backfill_universe_and_prices(**context):
    dates = context['ti'].xcom_pull(task_ids='get_dates')
    if not dates:
        return
    collect_universe_and_prices(dates)


def collect_current_holds(**context):
    """현재 구성종목 스냅샷 1회 수집 (KIS는 날짜 지정 불가 → 최근 거래일로 기록).

    Stock 노드가 여기서 생성되므로 주식 가격 백필보다 먼저 실행해야 한다.
    """
    dates = context['ti'].xcom_pull(task_ids='get_dates')
    if not dates:
        return
    collect_holdings(list(get_etf_codes_from_age()), dates[-1])


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
t2 = PythonOperator(task_id='backfill_universe_and_prices',
                     python_callable=backfill_universe_and_prices,
                     execution_timeout=timedelta(hours=1), dag=dag)
t3 = PythonOperator(task_id='collect_current_holds',
                     python_callable=collect_current_holds,
                     execution_timeout=timedelta(hours=1), dag=dag)
t4 = PythonOperator(task_id='backfill_stock_prices',
                     python_callable=backfill_stock_prices,
                     execution_timeout=timedelta(hours=3), dag=dag)
t5 = PythonOperator(task_id='backfill_returns',
                     python_callable=backfill_returns, dag=dag)

t1 >> t2 >> t3 >> t4 >> t5
