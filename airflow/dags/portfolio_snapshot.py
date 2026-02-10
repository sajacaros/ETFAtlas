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
    """yfinance로 종가 조회. ticker -> Decimal 맵 반환."""
    from decimal import Decimal
    import yfinance as yf

    prices = {}
    for ticker in tickers:
        try:
            hist = yf.Ticker(f"{ticker}.KS").history(period="5d")
            if not hist.empty:
                close = hist["Close"].iloc[-1]
                date = hist.index[-1].date()
                prices[ticker] = (Decimal(str(int(close))), date)
        except Exception as e:
            log.warning(f"yfinance failed for {ticker}: {e}")
    return prices


def snapshot_portfolios(**context):
    """포트폴리오 스냅샷 저장 - yfinance에서 직접 가격 조회"""
    from decimal import Decimal

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

        # yfinance에서 한번에 가격 조회
        ticker_prices = fetch_prices_yfinance(all_tickers) if all_tickers else {}
        log.info(f"Fetched prices for {len(ticker_prices)}/{len(all_tickers)} tickers")

        # 날짜 결정: 조회된 가격 중 가장 최근 날짜 사용
        if ticker_prices:
            trading_date = max(d for _, d in ticker_prices.values())
        else:
            trading_date = datetime.now().date()

        date_str = trading_date.isoformat()
        log.info(f"Snapshot date: {date_str}")

        snapshot_count = 0
        for pid in portfolio_ids:
            cur.execute("SELECT ticker, quantity FROM holdings WHERE portfolio_id = %s", (pid,))
            holdings = cur.fetchall()

            total_value = Decimal('0')
            for ticker, qty in holdings:
                if ticker == 'CASH':
                    total_value += qty
                elif ticker in ticker_prices:
                    price, _ = ticker_prices[ticker]
                    total_value += qty * price

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
        log.info(f"Snapshot complete. Saved {snapshot_count} portfolio snapshots")

    finally:
        cur.close()
        conn.close()


task_snapshot = PythonOperator(
    task_id='snapshot_portfolios',
    python_callable=snapshot_portfolios,
    dag=dag,
)
