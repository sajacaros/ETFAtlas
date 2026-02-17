"""
ETF Universe Sync DAG (Apache AGE) — 일일 증분 수집

마지막 수집일 이후 ~ 오늘까지 누락된 영업일의 데이터를 자동 수집.
수집 로직은 age_utils 공용 함수 사용.
메타데이터/구조 재구축은 age_rebuild_graph DAG(주간)에서 수행.
태그는 age_tagging DAG에서 부여.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
import logging

from age_utils import (
    get_db_connection, init_age, execute_cypher_batch,
    get_business_days, get_last_collected_date, get_etf_codes_from_age,
    collect_universe_and_prices, collect_holdings_for_dates,
    collect_stock_prices_for_dates,
    record_collection_run, send_discord_notification,
    update_etf_returns,
    INDEX_TAG_PATTERNS, RULE_ONLY_TAGS,
)

log = logging.getLogger(__name__)

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
    'email_on_failure': False,
}

dag = DAG(
    'age_sync_universe',
    default_args=default_args,
    description='ETF 데이터 일일 증분 수집 (Apache AGE)',
    schedule_interval='0 8 * * 1-5',
    catchup=False,
    tags=['etf', 'daily', 'age'],
)


# ──────────────────────────────────────────────
# Task 함수
# ──────────────────────────────────────────────

def fetch_trading_dates(**context):
    """마지막 수집일 이후 영업일 목록 조회.

    XCom return: 수집 대상 영업일 리스트 (YYYYMMDD)
    """
    today = datetime.now().strftime('%Y%m%d')

    last = get_last_collected_date()
    if not last:
        log.warning("No previous data in AGE. Run age_backfill first.")
        return []

    # 마지막 수집일 다음 날부터
    next_day = (datetime.strptime(last, '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')
    dates = get_business_days(next_day, today)

    if not dates:
        log.info(f"Already up to date (last: {last})")
        return []

    log.info(f"Trading dates to collect: {len(dates)} ({dates[0]} ~ {dates[-1]})")
    return dates


def sync_universe_and_prices(**context):
    """ETF 유니버스 + 가격 증분 수집."""
    ti = context['ti']
    dates = ti.xcom_pull(task_ids='fetch_trading_dates')
    if not dates:
        return

    _, new_etfs = collect_universe_and_prices(dates)
    if new_etfs:
        ti.xcom_push(key='new_etfs', value=new_etfs)


def sync_holdings(**context):
    """HOLDS 엣지 증분 수집."""
    dates = context['ti'].xcom_pull(task_ids='fetch_trading_dates')
    if not dates:
        return
    etf_codes = list(get_etf_codes_from_age())
    collect_holdings_for_dates(etf_codes, dates)


def sync_stock_prices(**context):
    """Stock 가격 증분 수집."""
    dates = context['ti'].xcom_pull(task_ids='fetch_trading_dates')
    if not dates:
        return
    collect_stock_prices_for_dates(dates)


def record_and_notify(**context):
    """수집 완료 기록 + 디스코드 알림. 이미 기록된 날짜면 스킵."""
    dates = context['ti'].xcom_pull(task_ids='fetch_trading_dates')
    if not dates:
        return
    last_date = dates[-1]
    date_str = f"{last_date[:4]}-{last_date[4:6]}-{last_date[6:8]}"
    is_new = record_collection_run(date_str)
    if is_new:
        send_discord_notification(date_str)
    else:
        log.info(f"Already recorded {date_str} — skipping Discord notification")


def sync_returns(**context):
    """수익률 계산."""
    update_etf_returns()


def tag_new_etfs(**context):
    """신규 ETF 룰 기반 태그 부여 (코스피200/코스닥150)."""
    import re

    ti = context['ti']
    new_etfs = ti.xcom_pull(task_ids='sync_universe_and_prices', key='new_etfs')
    if not new_etfs:
        log.info("No new ETFs to tag")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        tag_items = [{'name': t} for t in RULE_ONLY_TAGS]
        execute_cypher_batch(cur, """
            MERGE (t:Tag {name: item.name}) RETURN t
        """, tag_items)

        tagged_pairs = []
        for etf in new_etfs:
            for pattern, tag_name in INDEX_TAG_PATTERNS:
                if re.search(pattern, etf['name']):
                    tagged_pairs.append({'code': etf['code'], 'tag_name': tag_name})
                    break

        if tagged_pairs:
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                MATCH (t:Tag {name: item.tag_name})
                MERGE (e)-[:TAGGED]->(t)
                RETURN 1
            """, tagged_pairs)

        conn.commit()
        log.info(f"Tagged {len(tagged_pairs)}/{len(new_etfs)} new ETFs (rule-based)")

    finally:
        cur.close()
        conn.close()


# ──────────────────────────────────────────────
# DAG 태스크 정의
# ──────────────────────────────────────────────

start = EmptyOperator(task_id='start', dag=dag)
end = EmptyOperator(task_id='end', dag=dag)

t_dates = PythonOperator(task_id='fetch_trading_dates',
                          python_callable=fetch_trading_dates, dag=dag)
t_universe = PythonOperator(task_id='sync_universe_and_prices',
                             python_callable=sync_universe_and_prices, dag=dag)
t_holdings = PythonOperator(task_id='sync_holdings',
                             python_callable=sync_holdings, dag=dag)
t_stock_prices = PythonOperator(task_id='sync_stock_prices',
                                 python_callable=sync_stock_prices, dag=dag)
t_notify = PythonOperator(task_id='record_and_notify',
                           python_callable=record_and_notify, dag=dag)
t_returns = PythonOperator(task_id='sync_returns',
                            python_callable=sync_returns, dag=dag)
t_tags = PythonOperator(task_id='tag_new_etfs',
                         python_callable=tag_new_etfs, dag=dag)

# 의존 관계:
# start → fetch_trading_dates → sync_universe_and_prices
#   → sync_holdings → [sync_stock_prices, record_and_notify]
#   → sync_returns (가격 수집 후)
#   → tag_new_etfs (유니버스 수집 후)
# → end
start >> t_dates >> t_universe
t_universe >> [t_holdings, t_returns, t_tags]
t_holdings >> [t_stock_prices, t_notify]
[t_stock_prices, t_notify, t_returns, t_tags] >> end
