"""
가격 이력 백필 DAG (수동 트리거)

지난 N일(기본 400일 — 1년 수익률에 1년 전 거래일이 필요하다)의 영업일 중 Price가 빠진 날을 KIS 일봉으로 채운다 — ETF와 그래프 종목(Stock) 모두.
정기 수집은 수집을 시작한 날부터만 쌓으므로, 1개월~1년 수익률이 나오려면 한 번 돌려야 한다.

- 종가·시고저·거래량(·거래대금)만 채운다. NAV·순자산·시가총액은 현재가 API라 지난 날짜는 비워 둔다
- 이미 있는 (코드, 날짜)는 건드리지 않으므로 여러 번 돌려도 된다
- 최근 PRICE_REFILL_BUSINESS_DAYS 영업일은 정기 수집이 쓰는 범위라 빼고 채운다 (같은 날 Price 중복 방지)
- 끝나면 ETF 수익률(return_1d/1w/1m)을 다시 계산한다
- AGE에 쓰는 태스크는 pool age_write(슬롯 1)로 정기 수집과 동시에 돌지 않는다
"""

import logging
from datetime import datetime, timedelta

from airflow.sdk import DAG, Param
from airflow.providers.standard.operators.python import PythonOperator

from age_db import AGE_WRITE_POOL
from collect_prices import backfill_price_days, collect_stock_prices_for_dates, fill_missing_etf_prices
from returns import update_etf_returns

log = logging.getLogger(__name__)

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'email_on_failure': False,
}

dag = DAG(
    'backfill_prices',
    default_args=default_args,
    description='ETF·종목 가격 이력 백필 (수동 트리거)',
    schedule=None,
    catchup=False,
    max_active_runs=1,
    params={'days': Param(400, type='integer', minimum=30, maximum=800,
                          description='며칠 전까지 채울지 (달력 기준). 1년 수익률에는 1년 전 거래일이 있어야 해 365보다 넉넉히')},
    tags=['etf', 'manual', 'age'],
)


def plan_days(**context):
    days = backfill_price_days(int(context['params']['days']))
    log.info(f"Backfill range: {len(days)} business days {days[:1]}~{days[-1:]}")
    return days


def backfill_etf_prices(**context):
    days = context['ti'].xcom_pull(task_ids='plan_days')
    log.info(f"ETF prices backfilled: {fill_missing_etf_prices(days)}")


def backfill_stock_prices(**context):
    collect_stock_prices_for_dates(context['ti'].xcom_pull(task_ids='plan_days'))


t_plan = PythonOperator(task_id='plan_days', python_callable=plan_days, dag=dag)
t_etf = PythonOperator(task_id='backfill_etf_prices', python_callable=backfill_etf_prices,
                       execution_timeout=timedelta(hours=2), pool=AGE_WRITE_POOL, dag=dag)
t_stock = PythonOperator(task_id='backfill_stock_prices', python_callable=backfill_stock_prices,
                         execution_timeout=timedelta(hours=3), pool=AGE_WRITE_POOL, dag=dag)
t_returns = PythonOperator(task_id='update_returns', python_callable=update_etf_returns, pool=AGE_WRITE_POOL, dag=dag)

t_plan >> t_etf >> t_stock >> t_returns
