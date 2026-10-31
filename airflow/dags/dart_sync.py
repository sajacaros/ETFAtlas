"""
dart_sync — DART 고유번호·공시·주요계정·현금흐름을 RDB에 동기화 (dart_sync_rdb DAG의 태스크 본문)

API 키는 관리자 페이지에서 저장한 dart_settings(암호문)만 쓴다. 없으면 건너뛴다.
"""

import logging
from datetime import datetime, timedelta

from psycopg2.extras import execute_values

from app.utils.encryption import decrypt_value

from age_db import age_cursor, fetch_values
from dart_client import (ACCOUNTS, CASH_FLOW_ACCOUNTS, MULTI_ACCOUNT_BATCH, REPORT_CODES, DartClient, DartError,
                         cash_flow_targets, parse_cash_flow_rows, parse_financial_rows)
from market_calendar import now_kst
from rdb import connection

log = logging.getLogger(__name__)

RECENT_DAYS = 3
BACKFILL_DAYS = 90
FINANCIAL_YEARS = 5  # 3개년 연속 성장을 보려면 연간 실적 4개가 필요하다 (진행 중인 연도 포함 5개 사업연도)
CASH_FLOW_MAX_CALLS = 3000  # 하루 현금흐름 호출 상한 — 처음 채울 때(약 5천 건) 키의 일일 한도(2만 건)를 다른 작업과 나눠 쓴다
CASH_FLOW_QUARTER_YEARS = 2  # 분·반기 현금흐름을 받는 최근 사업연도 수 (올해와 작년)


def load_dart_key(conn) -> str:
    """관리자 페이지에서 저장한 키(암호문). 없거나 복호화에 실패하면 빈 문자열."""
    with conn.cursor() as cur:
        cur.execute("SELECT api_key FROM dart_settings WHERE id = 1")
        row = cur.fetchone()
    if row and row[0]:
        try:
            return decrypt_value(row[0])
        except Exception:
            log.warning("Failed to decrypt dart_settings.api_key (ENCRYPTION_KEY가 바뀌었나?)")
    return ''


def get_dart_client() -> DartClient | None:
    """저장된 키로 만든 DART 클라이언트. 키가 없으면 None."""
    with connection() as conn:
        key = load_dart_key(conn)
    if not key:
        log.warning("DART API 키가 없습니다 (관리자 페이지 > DART에서 저장) — 건너뜁니다")
        return None
    return DartClient(key)


def graph_stocks() -> dict[str, str]:
    """그래프 종목(ETF 제외)의 종목코드 → corp_code. DART에 없는 코드(해외 종목 등)는 빠진다."""
    with age_cursor() as (_, cur):
        codes = set(fetch_values(cur, "MATCH (s:Stock) WHERE coalesce(s.is_etf, false) = false RETURN s.code"))
        cur.execute("SELECT stock_code, corp_code FROM dart_corps WHERE stock_code IS NOT NULL")
        corp_of = dict(cur.fetchall())
    return {code: corp_of[code] for code in codes if code in corp_of}


def sync_corps():
    client = get_dart_client()
    if client is None:
        return
    corps = client.corp_codes()
    with connection() as conn, conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO dart_corps (corp_code, corp_name, stock_code, modify_date) VALUES %s
            ON CONFLICT (corp_code) DO UPDATE SET
                corp_name = EXCLUDED.corp_name, stock_code = EXCLUDED.stock_code, modify_date = EXCLUDED.modify_date
        """, [(c['corp_code'], c['corp_name'], c['stock_code'], c['modify_date']) for c in corps], page_size=1000)
        conn.commit()
    log.info("dart_corps: %d (상장 %d)", len(corps), sum(1 for c in corps if c['stock_code']))


def disclosure_rows(items, stocks) -> list[tuple]:
    """DART 공시 목록 → stock_disclosures 행. stocks(종목코드 모음)에 든 회사만."""
    return [
        (i['rcept_no'], i['stock_code'], i['corp_code'], i['report_nm'].strip(),
         datetime.strptime(i['rcept_dt'], '%Y%m%d').date(), i.get('flr_nm'), (i.get('rm') or '').strip() or None)
        for i in items if (i.get('stock_code') or '').strip() in stocks
    ]


def save_disclosures(cur, items, stocks) -> int:
    """공시 목록 중 stocks에 든 회사 것을 stock_disclosures에 넣는다(커밋은 부르는 쪽). 넣은 수를 돌려준다."""
    rows = disclosure_rows(items, stocks)
    if rows:
        execute_values(cur, """
            INSERT INTO stock_disclosures (rcept_no, stock_code, corp_code, report_nm, rcept_dt, flr_nm, rm) VALUES %s
            ON CONFLICT (rcept_no) DO UPDATE SET report_nm = EXCLUDED.report_nm, rm = EXCLUDED.rm
        """, rows)
    return len(rows)


def sync_disclosures():
    client = get_dart_client()
    if client is None:
        return
    stocks = graph_stocks()
    today = now_kst()
    fmt = lambda d: d.strftime('%Y%m%d')  # noqa: E731

    with connection() as conn, conn.cursor() as cur:
        # 백필 대상은 최근 공시를 저장하기 전에 정한다 — 먼저 저장하면 최근 3일에 공시가 있는 종목이 백필에서 빠진다
        cur.execute("SELECT DISTINCT stock_code FROM stock_disclosures")
        have = {row[0] for row in cur.fetchall()}
        missing = [code for code in stocks if code not in have]

        recent = list(client.disclosures(fmt(today - timedelta(days=RECENT_DAYS)), fmt(today)))
        saved = save_disclosures(cur, recent, stocks)
        conn.commit()
        backfilled = 0
        for code in missing:
            items = list(client.disclosures(fmt(today - timedelta(days=BACKFILL_DAYS)), fmt(today), stocks[code]))
            backfilled += save_disclosures(cur, items, stocks)
            conn.commit()
    log.info("stock_disclosures: 최근 %d건, 백필 %d개 종목 %d건", saved, len(missing), backfilled)


UPSERT_FINANCIALS = """
    INSERT INTO stock_financials
        (stock_code, bsns_year, reprt_code, fs_div, account, amount, amount_cum, rcept_no, fetched_at)
    VALUES %s
    ON CONFLICT (stock_code, bsns_year, reprt_code, fs_div, account) DO UPDATE SET
        amount = EXCLUDED.amount, amount_cum = EXCLUDED.amount_cum,
        rcept_no = EXCLUDED.rcept_no, fetched_at = EXCLUDED.fetched_at
"""


def save_financials(cur, rows: list[dict]) -> None:
    fetched_at = now_kst()
    execute_values(cur, UPSERT_FINANCIALS, [
        (r['stock_code'], r['bsns_year'], r['reprt_code'], r['fs_div'], r['account'],
         r['amount'], r['amount_cum'], r['rcept_no'], fetched_at) for r in rows])


def sync_financials():
    client = get_dart_client()
    if client is None:
        return
    stocks = graph_stocks()
    corp_codes = sorted(set(stocks.values()))
    year = now_kst().year

    saved = failed = 0
    with connection() as conn, conn.cursor() as cur:
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
                    save_financials(cur, rows)
                    conn.commit()
                    saved += len(rows)
    log.info("stock_financials: %d행 (%d개 회사, 실패 호출 %d)", saved, len(corp_codes), failed)
    if failed and not saved:
        raise RuntimeError("모든 주요계정 호출이 실패했습니다")


def sync_cash_flows():
    client = get_dart_client()
    if client is None:
        return
    stocks = graph_stocks()
    year = now_kst().year
    saved = failed = 0
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT stock_code, bsns_year, reprt_code, fs_div, rcept_no FROM stock_financials "
                    "WHERE account = ANY(%s) AND rcept_no IS NOT NULL", (list(ACCOUNTS),))
        reports = [r for r in cur.fetchall() if r[0] in stocks]
        cur.execute("SELECT stock_code, bsns_year, reprt_code, fs_div, rcept_no FROM stock_financials WHERE account = %s",
                    (next(iter(CASH_FLOW_ACCOUNTS)),))
        done = set(cur.fetchall())
        targets = cash_flow_targets(reports, done, year, CASH_FLOW_QUARTER_YEARS, CASH_FLOW_MAX_CALLS)
        for stock_code, bsns_year, reprt_code, fs_div, rcept_no in targets:
            try:
                items = client.statements(stocks[stock_code], bsns_year, reprt_code, fs_div)
            except DartError as e:
                failed += 1
                log.warning("fnlttSinglAcntAll %s %s %s failed: %s", stock_code, bsns_year, reprt_code, e)
                continue
            save_financials(cur, parse_cash_flow_rows(items, stock_code, bsns_year, reprt_code, fs_div, rcept_no))
            conn.commit()
            saved += 1
    pending = len(cash_flow_targets(reports, done, year, CASH_FLOW_QUARTER_YEARS, len(reports))) - saved
    log.info("현금흐름: 보고서 %d개 저장 (실패 호출 %d, 남은 보고서 %d)", saved, failed, max(pending, 0))
    if failed and not saved:
        raise RuntimeError("모든 현금흐름 호출이 실패했습니다")
