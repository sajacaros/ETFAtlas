"""
Portfolio Snapshot DAG
- 포트폴리오 보유 종목의 현재가를 yfinance에서 조회하여 일별 스냅샷 저장
- etf_daily_etl과 독립적으로 동작 (유니버스 밖 종목도 처리)
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import logging

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
    'portfolio_snapshot',
    default_args=default_args,
    description='포트폴리오 일별 스냅샷 (yfinance 기반)',
    schedule_interval='0 16 * * 1-5',  # 평일 16:00 KST (장 마감 후)
    catchup=False,
    tags=['portfolio', 'snapshot'],
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


def fetch_prices_yfinance(tickers):
    """yfinance로 최근 5거래일 종가 조회. ticker -> [(date, Decimal), ...] 맵 반환 (날짜 오름차순)."""
    from decimal import Decimal
    import yfinance as yf

    prices = {}
    for ticker in tickers:
        try:
            hist = yf.Ticker(f"{ticker}.KS").history(period="5d")
            if not hist.empty:
                entries = []
                for idx in range(len(hist)):
                    close = hist["Close"].iloc[idx]
                    dt = hist.index[idx].date()
                    if close > 0:
                        entries.append((dt, Decimal(str(int(close)))))
                if entries:
                    prices[ticker] = entries  # 날짜 오름차순
        except Exception as e:
            log.warning(f"yfinance failed for {ticker}: {e}")
    return prices


def _calc_portfolio_value(holdings, ticker_prices, target_date):
    """특정 날짜의 포트폴리오 평가금액을 계산한다.
    ticker_prices: {ticker: [(date, Decimal), ...]}  날짜 오름차순
    target_date에 가장 가까운(이하) 종가를 사용한다.
    """
    from decimal import Decimal

    total = Decimal('0')
    for ticker, qty in holdings:
        if ticker == 'CASH':
            total += qty
        elif ticker in ticker_prices:
            # target_date 이하에서 가장 최근 종가
            price = None
            for dt, p in ticker_prices[ticker]:
                if dt <= target_date:
                    price = p
            if price:
                total += qty * price
    return total


def snapshot_portfolios(**context):
    """포트폴리오 스냅샷 저장 - yfinance에서 직접 가격 조회.
    스냅샷 이력이 없는 포트폴리오는 최근 3거래일을 백필한다.
    """
    from decimal import Decimal

    BACKFILL_DAYS = 3

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # 보유 종목이 있는 포트폴리오 조회
        cur.execute("SELECT DISTINCT portfolio_id FROM holdings")
        portfolio_ids = [row[0] for row in cur.fetchall()]

        if not portfolio_ids:
            log.info("No portfolios with holdings found")
            return

        # 전체 고유 티커 수집 (CASH 제외)
        cur.execute("SELECT DISTINCT ticker FROM holdings WHERE ticker != 'CASH'")
        all_tickers = [row[0] for row in cur.fetchall()]

        # yfinance에서 한번에 가격 조회 (최근 5거래일)
        ticker_prices = fetch_prices_yfinance(all_tickers) if all_tickers else {}
        log.info(f"Fetched prices for {len(ticker_prices)}/{len(all_tickers)} tickers")

        # 거래일 목록 추출 (전체 티커에서 유니크한 날짜들, 오름차순)
        all_dates = set()
        for entries in ticker_prices.values():
            for dt, _ in entries:
                all_dates.add(dt)
        trading_dates = sorted(all_dates)

        if not trading_dates:
            log.info("No trading dates found from yfinance")
            return

        latest_date = trading_dates[-1]
        backfill_dates = trading_dates[-BACKFILL_DAYS:]  # 최근 3거래일
        log.info(f"Latest date: {latest_date}, backfill dates: {backfill_dates}")

        # 기존 스냅샷이 있는 포트폴리오 식별
        cur.execute("""
            SELECT DISTINCT portfolio_id FROM portfolio_snapshots
            WHERE portfolio_id = ANY(%s)
        """, (portfolio_ids,))
        has_snapshot = {row[0] for row in cur.fetchall()}

        snapshot_count = 0
        for pid in portfolio_ids:
            cur.execute("SELECT ticker, quantity FROM holdings WHERE portfolio_id = %s", (pid,))
            holdings = cur.fetchall()

            # 스냅샷 이력이 없으면 최근 3거래일 백필, 있으면 최신 날짜만
            target_dates = backfill_dates if pid not in has_snapshot else [latest_date]

            for snap_date in target_dates:
                date_str = snap_date.isoformat()
                total_value = _calc_portfolio_value(holdings, ticker_prices, snap_date)

                # 전일 스냅샷 조회
                cur.execute("""
                    SELECT total_value FROM portfolio_snapshots
                    WHERE portfolio_id = %s AND date < %s
                    ORDER BY date DESC LIMIT 1
                """, (pid, date_str))
                prev = cur.fetchone()
                prev_value = prev[0] if prev else None
                change_amount = total_value - prev_value if prev_value else None
                change_rate = float(change_amount / prev_value * 100) if prev_value and prev_value != 0 else None

                # UPSERT
                cur.execute("""
                    INSERT INTO portfolio_snapshots (portfolio_id, date, total_value, prev_value, change_amount, change_rate, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (portfolio_id, date)
                    DO UPDATE SET total_value = EXCLUDED.total_value,
                                  prev_value = EXCLUDED.prev_value,
                                  change_amount = EXCLUDED.change_amount,
                                  change_rate = EXCLUDED.change_rate
                """, (pid, date_str, total_value, prev_value, change_amount, change_rate))
                snapshot_count += 1

        conn.commit()
        log.info(f"Snapshot complete. Saved {snapshot_count} portfolio snapshots "
                 f"({len(portfolio_ids)} portfolios, "
                 f"{len(portfolio_ids) - len(has_snapshot)} backfilled)")

    finally:
        cur.close()
        conn.close()


task_snapshot = PythonOperator(
    task_id='snapshot_portfolios',
    python_callable=snapshot_portfolios,
    dag=dag,
)
