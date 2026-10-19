"""
DART Sync DAG — 챗봇 기업 분석의 실적·공시

- dart_corps: DART 고유번호 전체 (종목코드 → corp_code, 그래프 밖 상장사 안내용)
- stock_disclosures: 그래프 종목의 공시 목록. 매일 전체 회사의 최근 3일을 받아 그래프 종목만 남기고,
  공시가 하나도 없는 종목은 회사별로 최근 90일을 백필한다.
- stock_financials: 그래프 종목의 주요계정(매출액·영업이익·순이익·자산·부채·자본).
  최근 3개 사업연도 × 4개 보고서를 매일 다시 받는다 (100개 회사씩 묶어 하루 수십 건).

API 키는 관리자 페이지에 저장한 dart_settings가 우선, 없으면 환경변수 DART_API_KEY. 둘 다 없으면 건너뛴다.
"""

from datetime import datetime, timedelta
import logging
import os

from airflow.sdk import DAG
from airflow.providers.standard.operators.python import PythonOperator

from age_utils import get_db_connection, init_age, execute_cypher, _parse_age_value

log = logging.getLogger(__name__)

RECENT_DAYS = 3
BACKFILL_DAYS = 90
FINANCIAL_YEARS = 3

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 2,
    'retry_delay': timedelta(minutes=10),
    'email_on_failure': False,
}

dag = DAG(
    'dart_sync_rdb',
    default_args=default_args,
    description='DART 고유번호·공시·주요계정 RDB 동기화 (챗봇 기업 분석)',
    schedule='20 19 * * 1-5',  # 평일 19:20 KST — 장 마감 후 공시까지 반영
    catchup=False,
    max_active_runs=1,
    tags=['dart', 'daily', 'rdb'],
)


def load_dart_key(conn) -> str:
    """관리자 페이지에서 저장한 키(암호문)가 우선, 없거나 복호화 실패면 환경변수."""
    # backend 암호화 유틸 (컨테이너 PYTHONPATH=/opt/backend)
    from app.utils.encryption import decrypt_value

    cur = conn.cursor()
    try:
        cur.execute("SELECT api_key FROM dart_settings WHERE id = 1")
        row = cur.fetchone()
    finally:
        cur.close()
    if row and row[0]:
        try:
            return decrypt_value(row[0])
        except Exception:
            log.warning("Failed to decrypt dart_settings.api_key; using environment")
    return os.environ.get('DART_API_KEY', '')


def _client():
    from dart_client import DartClient

    conn = get_db_connection()
    try:
        key = load_dart_key(conn)
    finally:
        conn.close()
    if not key:
        log.warning("DART API 키가 없습니다 (관리자 페이지 > DART 또는 DART_API_KEY) — 건너뜁니다")
        return None
    return DartClient(key)


def graph_stocks() -> dict[str, str]:
    """그래프 종목(ETF 제외)의 종목코드 → corp_code. DART에 없는 코드(해외 종목 등)는 빠진다."""
    conn = get_db_connection()
    cur = init_age(conn)
    try:
        codes = {
            _parse_age_value(row[0])
            for row in execute_cypher(cur, "MATCH (s:Stock) WHERE coalesce(s.is_etf, false) = false RETURN s.code")
            if row[0]
        }
        cur.execute("SELECT stock_code, corp_code FROM dart_corps WHERE stock_code IS NOT NULL")
        corp_of = dict(cur.fetchall())
    finally:
        cur.close()
        conn.close()
    return {code: corp_of[code] for code in codes if code in corp_of}


def sync_corps(**context):
    client = _client()
    if client is None:
        return
    corps = client.corp_codes()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        from psycopg2.extras import execute_values

        execute_values(cur, """
            INSERT INTO dart_corps (corp_code, corp_name, stock_code, modify_date) VALUES %s
            ON CONFLICT (corp_code) DO UPDATE SET
                corp_name = EXCLUDED.corp_name, stock_code = EXCLUDED.stock_code, modify_date = EXCLUDED.modify_date
        """, [(c['corp_code'], c['corp_name'], c['stock_code'], c['modify_date']) for c in corps], page_size=1000)
        conn.commit()
    finally:
        cur.close()
        conn.close()
    log.info("dart_corps: %d (상장 %d)", len(corps), sum(1 for c in corps if c['stock_code']))


def _save_disclosures(cur, items, stocks: dict[str, str]) -> int:
    from psycopg2.extras import execute_values

    rows = [
        (i['rcept_no'], i['stock_code'], i['corp_code'], i['report_nm'].strip(),
         datetime.strptime(i['rcept_dt'], '%Y%m%d').date(), i.get('flr_nm'), (i.get('rm') or '').strip() or None)
        for i in items if (i.get('stock_code') or '').strip() in stocks
    ]
    if rows:
        execute_values(cur, """
            INSERT INTO stock_disclosures (rcept_no, stock_code, corp_code, report_nm, rcept_dt, flr_nm, rm) VALUES %s
            ON CONFLICT (rcept_no) DO UPDATE SET report_nm = EXCLUDED.report_nm, rm = EXCLUDED.rm
        """, rows)
    return len(rows)


def sync_disclosures(**context):
    client = _client()
    if client is None:
        return
    stocks = graph_stocks()
    today = datetime.now()
    fmt = lambda d: d.strftime('%Y%m%d')  # noqa: E731

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 백필 대상은 최근 공시를 저장하기 전에 정한다 — 먼저 저장하면 최근 3일에 공시가 있는 종목이 백필에서 빠진다
        cur.execute("SELECT DISTINCT stock_code FROM stock_disclosures")
        have = {row[0] for row in cur.fetchall()}
        missing = [code for code in stocks if code not in have]

        recent = list(client.disclosures(fmt(today - timedelta(days=RECENT_DAYS)), fmt(today)))
        saved = _save_disclosures(cur, recent, stocks)
        conn.commit()
        backfilled = 0
        for code in missing:
            items = list(client.disclosures(fmt(today - timedelta(days=BACKFILL_DAYS)), fmt(today), stocks[code]))
            backfilled += _save_disclosures(cur, items, stocks)
            conn.commit()
    finally:
        cur.close()
        conn.close()
    log.info("stock_disclosures: 최근 %d건, 백필 %d개 종목 %d건", saved, len(missing), backfilled)


def sync_financials(**context):
    from psycopg2.extras import execute_values
    from dart_client import MULTI_ACCOUNT_BATCH, REPORT_CODES, DartError, parse_financial_rows

    client = _client()
    if client is None:
        return
    stocks = graph_stocks()
    corp_codes = sorted(set(stocks.values()))
    year = datetime.now().year

    conn = get_db_connection()
    cur = conn.cursor()
    saved = failed = 0
    try:
        for bsns_year in range(year - FINANCIAL_YEARS + 1, year + 1):
            for reprt_code in REPORT_CODES:
                for start in range(0, len(corp_codes), MULTI_ACCOUNT_BATCH):
                    batch = corp_codes[start:start + MULTI_ACCOUNT_BATCH]
                    try:
                        rows = parse_financial_rows(client.financials(batch, bsns_year, reprt_code))
                    except DartError as e:
                        failed += 1
                        log.warning("fnlttMultiAcnt %s %s failed: %s", bsns_year, reprt_code, e)
                        continue
                    rows = [r for r in rows if r['stock_code'] in stocks]
                    if not rows:
                        continue
                    execute_values(cur, """
                        INSERT INTO stock_financials
                            (stock_code, bsns_year, reprt_code, fs_div, account, amount, amount_cum, rcept_no, fetched_at)
                        VALUES %s
                        ON CONFLICT (stock_code, bsns_year, reprt_code, fs_div, account) DO UPDATE SET
                            amount = EXCLUDED.amount, amount_cum = EXCLUDED.amount_cum,
                            rcept_no = EXCLUDED.rcept_no, fetched_at = EXCLUDED.fetched_at
                    """, [(r['stock_code'], r['bsns_year'], r['reprt_code'], r['fs_div'], r['account'],
                           r['amount'], r['amount_cum'], r['rcept_no'], datetime.now()) for r in rows])
                    conn.commit()
                    saved += len(rows)
    finally:
        cur.close()
        conn.close()
    log.info("stock_financials: %d행 (%d개 회사, 실패 호출 %d)", saved, len(corp_codes), failed)
    if failed and not saved:
        raise RuntimeError("모든 주요계정 호출이 실패했습니다")


t_corps = PythonOperator(task_id='sync_corps', python_callable=sync_corps, dag=dag)
t_disclosures = PythonOperator(task_id='sync_disclosures', python_callable=sync_disclosures, dag=dag)
t_financials = PythonOperator(task_id='sync_financials', python_callable=sync_financials, dag=dag)

t_corps >> [t_disclosures, t_financials]
