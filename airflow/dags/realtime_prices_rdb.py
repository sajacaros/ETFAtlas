"""
Realtime Price Collection DAG
- 장중 10분마다 포트폴리오 보유 종목의 현재가를 RDB에 업서트
- 현재가 업서트 후 포트폴리오 스냅샷도 갱신
- 거래일 + 장중(09:00~15:30) 여부를 체크하여 불필요한 실행 방지
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from airflow.sdk import DAG
from airflow.providers.standard.operators.python import PythonOperator, ShortCircuitOperator
import logging

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=2),
    'email_on_failure': False,
}

dag = DAG(
    'rdb_realtime_prices',
    default_args=default_args,
    description='장중 10분 주기 현재가 수집 + 스냅샷 갱신',
    schedule='*/10 9-15 * * 1-5',
    catchup=False,
    tags=['portfolio', 'realtime', 'prices'],
)


def get_db_connection():
    import psycopg2
    import os

    db_url = os.environ.get(
        'DATABASE_URL',
        'postgresql://postgres:postgres@db:5432/etf_atlas'
    )

    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', '')

    if '@' in db_url:
        auth, host_db = db_url.split('@')
        user, password = auth.split(':')
        host_port, database = host_db.split('/')
        if ':' in host_port:
            host, port = host_port.split(':')
        else:
            host = host_port
            port = 5432
    else:
        user = 'postgres'
        password = 'postgres'
        host = 'db'
        port = 5432
        database = 'etf_atlas'

    return psycopg2.connect(
        host=host, port=int(port), database=database,
        user=user, password=password
    )


def _is_market_open(day) -> bool | None:
    """개장일 여부. market_calendar 캐시 → 없으면 KIS 국내휴장일조회(1일 1회 권장) 후 저장."""
    from age_utils import get_kis_client

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT is_open FROM market_calendar WHERE date = %s", (day,))
        row = cur.fetchone()
        if row is not None:
            return row[0]

        kis = get_kis_client()
        if kis is None:
            return None
        try:
            is_open = kis.is_market_open(day.strftime('%Y%m%d'))
        except Exception as e:
            log.warning(f"KIS holiday lookup failed: {e}")
            return None
        if is_open is not None:
            cur.execute(
                "INSERT INTO market_calendar (date, is_open) VALUES (%s, %s) "
                "ON CONFLICT (date) DO UPDATE SET is_open = EXCLUDED.is_open, checked_at = NOW()",
                (day, is_open),
            )
            conn.commit()
        return is_open
    finally:
        cur.close()
        conn.close()


def check_market_open(**context):
    """오늘 가격 수집이 필요한지 확인.
    1) 휴장일이면 → 스킵 (KIS 국내휴장일조회, market_calendar에 하루 1회 캐시)
    2) 오늘 가격이 없으면 → 수집
    3) 장 마감(15:30) 후 이미 수집했으면 → 스킵
    4) 장중이면 → 수집 (10분마다 업데이트)
    """
    now_kst = datetime.now(KST)
    today_str = now_kst.strftime('%Y%m%d')
    today_iso = now_kst.date().isoformat()

    # 1) 거래일 확인
    is_open = _is_market_open(now_kst.date())
    if is_open is False:
        log.info(f"{today_str} is not a trading day. Skipping.")
        return False
    if is_open is None:
        log.warning(f"Could not determine market status for {today_str}. Proceeding.")

    # 2) 오늘 최종 업데이트 시간 확인
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT MAX(updated_at) FROM ticker_prices WHERE date = %s",
            (today_iso,)
        )
        row = cur.fetchone()
        last_updated = row[0] if row else None
    finally:
        cur.close()
        conn.close()

    if last_updated is None:
        log.info("No prices for today yet. Proceeding.")
        return True

    # 3) 장 마감 후 이미 수집했으면 스킵
    market_close = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)

    if last_updated.tzinfo:
        last_updated_kst = last_updated.astimezone(KST)
    else:
        last_updated_kst = last_updated.replace(tzinfo=KST)

    if last_updated_kst >= market_close:
        log.info(
            f"Already collected after market close "
            f"(last_update={last_updated_kst.strftime('%H:%M')}). Skipping."
        )
        return False

    # 4) 장중 — 수집 진행
    log.info(
        f"Last update at {last_updated_kst.strftime('%H:%M')}, "
        f"before market close. Proceeding."
    )
    return True


def collect_prices(**context):
    """포트폴리오 보유 종목의 현재가를 yfinance에서 조회하여 ticker_prices(오늘 날짜)에 업서트."""
    import yfinance as yf

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # 보유 종목 티커 조회 (CASH 제외)
        cur.execute("SELECT DISTINCT ticker FROM holdings WHERE ticker != 'CASH'")
        tickers = [row[0] for row in cur.fetchall()]

        if not tickers:
            log.info("No tickers found in holdings")
            return

        log.info(f"Collecting prices for {len(tickers)} tickers")

        today = datetime.now(KST).date()
        success_count = 0

        for ticker in tickers:
            try:
                hist = yf.Ticker(f"{ticker}.KS").history(period="1d")
                if not hist.empty:
                    close = Decimal(str(int(hist["Close"].iloc[-1])))
                    cur.execute("""
                        INSERT INTO ticker_prices (ticker, date, price, updated_at)
                        VALUES (%s, %s, %s, NOW())
                        ON CONFLICT (ticker, date)
                        DO UPDATE SET price = EXCLUDED.price, updated_at = NOW()
                    """, (ticker, today.isoformat(), close))
                    success_count += 1
            except Exception as e:
                log.warning(f"Failed to fetch price for {ticker}: {e}")

        conn.commit()
        log.info(f"Upserted {success_count}/{len(tickers)} ticker prices")

    finally:
        cur.close()
        conn.close()


def update_snapshots(**context):
    """ticker_prices 기반으로 포트폴리오 스냅샷 갱신."""
    # backend 암호화 유틸 (컨테이너 PYTHONPATH=/opt/backend)
    from app.utils.encryption import encrypt_value, decrypt_value

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        today = datetime.now(KST).date()
        today_str = today.isoformat()

        # 보유 종목이 있는 포트폴리오 조회
        cur.execute("""
            SELECT DISTINCT h.portfolio_id
            FROM holdings h
            JOIN portfolios p ON p.id = h.portfolio_id
            WHERE p.snapshot_enabled = true
        """)
        portfolio_ids = [row[0] for row in cur.fetchall()]

        if not portfolio_ids:
            log.info("No portfolios with holdings found")
            return

        # 오늘자 ticker_prices 조회
        cur.execute(
            "SELECT ticker, price FROM ticker_prices WHERE date = %s",
            (today_str,)
        )
        price_map = {row[0]: Decimal(str(row[1])) for row in cur.fetchall()}

        if not price_map:
            log.info("No prices available for today. Skipping snapshot update.")
            return

        snapshot_count = 0
        for pid in portfolio_ids:
            cur.execute(
                "SELECT ticker, quantity FROM holdings WHERE portfolio_id = %s",
                (pid,)
            )
            holdings = cur.fetchall()

            # 평가금액 계산
            total_value = Decimal('0')
            for ticker, enc_qty in holdings:
                qty = Decimal(decrypt_value(enc_qty))
                if ticker == 'CASH':
                    total_value += qty
                elif ticker in price_map:
                    total_value += qty * price_map[ticker]

            # 전일 스냅샷 조회 (변동률 계산용)
            cur.execute("""
                SELECT total_value FROM portfolio_snapshots
                WHERE portfolio_id = %s AND date < %s
                ORDER BY date DESC LIMIT 1
            """, (pid, today_str))
            prev = cur.fetchone()
            if prev and prev[0]:
                prev_value = Decimal(decrypt_value(prev[0]))
            else:
                prev_value = None
            change_amount = total_value - prev_value if prev_value else None
            change_rate = (
                float(change_amount / prev_value * 100)
                if prev_value and prev_value != 0 else None
            )

            # Encrypt values before storing
            enc_total = encrypt_value(str(total_value))
            enc_prev = encrypt_value(str(prev_value)) if prev_value is not None else None
            enc_change_amt = encrypt_value(str(change_amount)) if change_amount is not None else None
            enc_change_rate = encrypt_value(str(change_rate)) if change_rate is not None else None

            # UPSERT
            cur.execute("""
                INSERT INTO portfolio_snapshots
                    (portfolio_id, date, total_value, prev_value,
                     change_amount, change_rate, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (portfolio_id, date)
                DO UPDATE SET
                    total_value = EXCLUDED.total_value,
                    prev_value = EXCLUDED.prev_value,
                    change_amount = EXCLUDED.change_amount,
                    change_rate = EXCLUDED.change_rate,
                    updated_at = NOW()
            """, (pid, today_str, enc_total, enc_prev,
                  enc_change_amt, enc_change_rate))
            snapshot_count += 1

        conn.commit()
        log.info(f"Updated {snapshot_count} portfolio snapshots")

    finally:
        cur.close()
        conn.close()


# Tasks
task_check_market = ShortCircuitOperator(
    task_id='check_market_open',
    python_callable=check_market_open,
    dag=dag,
)

task_collect_prices = PythonOperator(
    task_id='collect_prices',
    python_callable=collect_prices,
    dag=dag,
)

task_update_snapshots = PythonOperator(
    task_id='update_snapshots',
    python_callable=update_snapshots,
    dag=dag,
)

# Dependencies
task_check_market >> task_collect_prices >> task_update_snapshots
