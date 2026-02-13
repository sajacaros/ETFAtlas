"""
Realtime Price Collection DAG
- 장중 10분마다 포트폴리오 보유 종목의 현재가를 RDB에 업서트
- 현재가 업서트 후 포트폴리오 스냅샷도 갱신
- 거래일 + 장중(09:00~15:30) 여부를 체크하여 불필요한 실행 방지
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from airflow import DAG
from airflow.operators.python import PythonOperator, ShortCircuitOperator
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
    'realtime_prices_rdb',
    default_args=default_args,
    description='장중 10분 주기 현재가 수집 + 스냅샷 갱신',
    schedule_interval='*/10 9-15 * * 1-5',
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


def check_market_open(**context):
    """거래일 + 장중 여부 확인. False 반환 시 후속 태스크 스킵."""
    from pykrx import stock as pykrx_stock

    now_kst = datetime.now(KST)
    today_str = now_kst.strftime('%Y%m%d')

    # 15:30 이후면 스킵
    market_close = now_kst.replace(hour=15, minute=30, second=0, microsecond=0)
    if now_kst >= market_close:
        log.info(f"Market closed (now={now_kst.strftime('%H:%M')}). Skipping.")
        return False

    # pykrx로 거래일 확인
    trading_days = pykrx_stock.get_market_ohlcv(today_str, today_str, "005930")
    if trading_days.empty:
        log.info(f"{today_str} is not a trading day. Skipping.")
        return False

    log.info(f"Market open. Proceeding with price collection.")
    return True


def collect_prices(**context):
    """포트폴리오 보유 종목의 현재가를 yfinance에서 조회하여 ticker_prices에 업서트."""
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
                yf_ticker = f"{ticker}.KS"
                hist = yf.Ticker(yf_ticker).history(period="1d")
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
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        today = datetime.now(KST).date()
        today_str = today.isoformat()

        # 보유 종목이 있는 포트폴리오 조회
        cur.execute("SELECT DISTINCT portfolio_id FROM holdings")
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
            for ticker, qty in holdings:
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
            prev_value = Decimal(str(prev[0])) if prev else None
            change_amount = total_value - prev_value if prev_value else None
            change_rate = (
                float(change_amount / prev_value * 100)
                if prev_value and prev_value != 0 else None
            )

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
                    change_rate = EXCLUDED.change_rate
            """, (pid, today_str, total_value, prev_value,
                  change_amount, change_rate))
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
