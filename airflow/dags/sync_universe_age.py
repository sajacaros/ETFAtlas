"""
ETF Universe Sync DAG (Apache AGE) — 일일 증분 수집

마지막 수집일 이후 ~ 종가가 확정된 마지막 날까지 누락된 영업일의 데이터를 자동 수집.
AGE가 비어 있으면(첫 실행) 최근 거래일 하루만 수집한다 — 과거 이력 백필은 하지 않는다.
증분 기준은 전체 최근 날짜 하나라 일부 ETF만 실패한 날은 그 뒤에 다시 받지 않으므로,
최근 영업일 몇 날의 빠진 (ETF, 날짜)를 매번 다시 채운다(refill_missing_etf_prices).
구성종목(HOLDS)은 KIS API가 날짜 지정을 지원하지 않아 항상 최근 거래일 스냅샷만 수집한다.
16:30 실행은 그날 종가를 받고 일일 리포트(수집 요약·상승 ETF)를 디스코드로 보낸다.
수집 로직은 age_utils 공용 함수 사용. 태그는 age_tagging DAG에서 부여.
"""

from datetime import datetime, timedelta
from airflow.sdk import DAG
from airflow.timetables.trigger import MultipleCronTriggerTimetable
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.standard.operators.empty import EmptyOperator
import logging

from age_utils import (
    get_db_connection, init_age, execute_cypher_batch,
    get_business_days, last_settled_day, get_last_collected_date, get_etf_codes_from_age,
    collect_universe_and_prices, refill_missing_etf_prices, refresh_latest_snapshot_values, collect_holdings, compute_weight_changes,
    collect_stock_prices_for_dates,
    record_collection_run, send_discord_notification, send_daily_report,
    update_etf_returns,
    INDEX_TAG_PATTERNS, RULE_ONLY_TAGS, holdings_target_date,
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
    # 매일 08:50·16:30 KST. 16:30은 그날 종가를 받고, 다음 날 08:50은 그날 NAV·순자산을 다시 쓴다.
    # 구성종목은 개장일에만 그날 날짜로 받으며(holdings_target_date) 16:30에는 아침에 빠진 ETF만 다시 받는다
    schedule=MultipleCronTriggerTimetable('50 8 * * *', '30 16 * * *', timezone='Asia/Seoul'),
    catchup=False,
    max_active_runs=1,  # 수동 실행이 정기 실행과 겹치면 Price 노드가 중복될 수 있다
    tags=['etf', 'daily', 'age'],
)


# ──────────────────────────────────────────────
# Task 함수
# ──────────────────────────────────────────────

def fetch_trading_dates(**context):
    """마지막 수집일 이후 영업일 목록 조회. 첫 실행이면 최근 거래일 하루.

    XCom return: 수집 대상 영업일 리스트 (YYYYMMDD)
    """
    end_date = last_settled_day(datetime.now())

    last = get_last_collected_date()
    if last:
        # 마지막 수집일 다음 날부터
        start = (datetime.strptime(last, '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')
        dates = get_business_days(start, end_date)
    else:
        # 첫 실행(빈 AGE): 백필 없이 최근 거래일 하루만 수집
        start = (datetime.now() - timedelta(days=10)).strftime('%Y%m%d')
        dates = get_business_days(start, end_date)[-1:]
        log.info(f"No previous data in AGE. First run collects latest trading day only: {dates}")

    if not dates:
        if last:
            log.info(f"Already up to date (last: {last})")
        else:
            log.warning("No business days found — check KIS_APP_KEY/KIS_APP_SECRET")
        return []

    log.info(f"Trading dates to collect: {len(dates)} ({dates[0]} ~ {dates[-1]})")
    return dates


def sync_universe_and_prices(**context):
    """ETF 유니버스 + 가격 증분 수집. 새 날짜가 없어도 최근 빠진 가격은 다시 채운다.

    새 날짜가 없으면(전날 16:30에 받은 뒤의 아침 실행) 마지막 수집일 NAV·순자산을 지금 현재가로 다시 쓴다.
    """
    ti = context['ti']
    dates = ti.xcom_pull(task_ids='fetch_trading_dates')
    if dates:
        _, new_etfs, actual_dates = collect_universe_and_prices(dates)
        if new_etfs:
            ti.xcom_push(key='new_etfs', value=new_etfs)
        if actual_dates:
            ti.xcom_push(key='actual_dates', value=actual_dates)
    else:
        refresh_latest_snapshot_values()

    refill_missing_etf_prices()


# 구성종목 조회 실패가 이 비율 이상이면 태스크를 실패시켜 Airflow 재시도로 빠진 ETF만 다시 받는다
HOLDINGS_RETRY_FAILURE_RATIO = 0.2


def sync_holdings(**context):
    """구성종목(KIS)을 HOLDS로 저장. 받은 날짜(YYYYMMDD)를 돌려준다(XCom) — 받지 않았으면 None.

    가격과 따로, 개장일이면 그날 공시된 구성을 그날 날짜로 받는다(holdings_target_date). KIS는 과거 날짜를 주지 않는다.
    실패가 많으면 태스크 재시도로 빠진 ETF만 다시 받고(이미 받은 ETF는 건너뜀), 마지막 시도면
    받은 것만으로 진행한다.
    """
    ti = context['ti']
    target = holdings_target_date(datetime.now())
    if not target:
        log.info("No holdings to fetch (non-trading day or before 08:35) — skipping holdings")
        return None

    etf_codes = list(get_etf_codes_from_age())
    failed = collect_holdings(etf_codes, target)
    if failed:
        ratio = len(failed) / len(etf_codes)
        last_try = ti.try_number > context['task'].retries
        if ratio >= HOLDINGS_RETRY_FAILURE_RATIO and not last_try:
            raise RuntimeError(f"Holdings failed for {len(failed)}/{len(etf_codes)} ETFs — retrying")
        log.warning(f"Giving up holdings for {len(failed)}/{len(etf_codes)} ETFs on {target}: {sorted(failed)}")
    return target


def sync_stock_prices(**context):
    """Stock 가격 증분 수집."""
    ti = context['ti']
    dates = ti.xcom_pull(task_ids='sync_universe_and_prices', key='actual_dates')
    if not dates:
        return
    collect_stock_prices_for_dates(dates)


def sync_weight_changes(**context):
    """액티브 ETF 비중 변화 계산·저장. 웹 화면과 디스코드 알림이 이 결과를 읽는다."""
    if not context['ti'].xcom_pull(task_ids='sync_holdings'):
        return  # 이번 실행에서 구성종목을 받지 않았다
    compute_weight_changes()


def _latest_collected_date(ti) -> str | None:
    """이번 실행에서 구성종목을 받은 날짜(YYYY-MM-DD). 수집 기록·알림은 가격이 아니라 구성종목 날짜를 따른다."""
    bd = ti.xcom_pull(task_ids='sync_holdings')
    if not bd:
        return None
    return f"{bd[:4]}-{bd[4:6]}-{bd[6:8]}"


def record_collection(**context):
    """수집 완료 기록 + 웹 알림(pg_notify). 비중변화 계산이 실패해도 기록한다."""
    date_str = _latest_collected_date(context['ti'])
    if date_str:
        record_collection_run(date_str)


def notify_discord(**context):
    """디스코드 비중변화 알림. 이미 보낸 날짜는 건너뛰고, 실패하면 태스크 재시도로 다시 보낸다."""
    date_str = _latest_collected_date(context['ti'])
    if date_str:
        send_discord_notification(date_str)


def notify_daily_report(**context):
    """장 마감 뒤 실행이면 그날 수집 결과 요약과 많이 오른 ETF를 디스코드로 보낸다.

    그날 종가를 받은 실행(16:30)만 보낸다 — 아침 실행이 받는 전날 가격은 리포트하지 않는다.
    """
    ti = context['ti']
    dates = ti.xcom_pull(task_ids='sync_universe_and_prices', key='actual_dates')
    today = datetime.now().strftime('%Y%m%d')
    if not dates or dates[-1] != today:
        log.info(f"No closing prices for today ({today}) in this run — skipping daily report")
        return
    new_etfs = ti.xcom_pull(task_ids='sync_universe_and_prices', key='new_etfs')
    send_daily_report(f"{today[:4]}-{today[4:6]}-{today[6:8]}", new_etfs)


def sync_returns(**context):
    """수익률 계산. 새 거래일 데이터가 없으면 스킵하여 기존 값 유지."""
    ti = context['ti']
    dates = ti.xcom_pull(task_ids='sync_universe_and_prices', key='actual_dates')
    if not dates:
        return
    update_etf_returns()


def tag_new_etfs(**context):
    """신규 ETF 룰 기반 태그 부여 (코스피/코스닥)."""
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
t_changes = PythonOperator(task_id='sync_weight_changes',
                            python_callable=sync_weight_changes, dag=dag)
# 비중변화 계산 뒤에 기록해야 웹 알림이 새 계산 결과를 본다. 계산이 실패해도 기록은 한다
t_record = PythonOperator(task_id='record_collection',
                           python_callable=record_collection, trigger_rule='all_done', dag=dag)
t_discord = PythonOperator(task_id='notify_discord',
                            python_callable=notify_discord, dag=dag)
t_returns = PythonOperator(task_id='sync_returns',
                            python_callable=sync_returns, dag=dag)
t_tags = PythonOperator(task_id='tag_new_etfs',
                         python_callable=tag_new_etfs, dag=dag)
# 주식 가격·구성종목이 일부 실패해도 리포트는 보낸다 — 요약에 빠진 수가 드러난다
t_report = PythonOperator(task_id='notify_daily_report',
                           python_callable=notify_daily_report, trigger_rule='all_done', dag=dag)

# 의존 관계:
# start → fetch_trading_dates → sync_universe_and_prices
#   → sync_holdings → [sync_stock_prices, sync_weight_changes → [record_collection, notify_discord]]
#   → sync_returns (가격 수집 후)
#   → [sync_stock_prices, sync_returns] → notify_daily_report (16:30 실행만)
#   → tag_new_etfs (유니버스 수집 후)
# → end
start >> t_dates >> t_universe
t_universe >> [t_holdings, t_returns, t_tags]
t_holdings >> [t_stock_prices, t_changes]
t_changes >> [t_record, t_discord]
[t_stock_prices, t_returns] >> t_report
[t_report, t_record, t_discord, t_tags] >> end
