"""
RDB Backfill DAG
- etfs 테이블의 전체 ETF에 대해 2025-01-01부터 현재까지 일별 종가를 ticker_prices에 백필
- 수동 트리거 전용 (schedule_interval=None)
- yfinance 배치 다운로드 사용, 20개씩 배치 처리
"""

from datetime import datetime, timedelta, date, timezone
from decimal import Decimal
from airflow import DAG
from airflow.operators.python import PythonOperator
import logging
import time

log = logging.getLogger(__name__)

BATCH_SIZE = 20
START_DATE = '2025-01-01'
SLEEP_BETWEEN_BATCHES = 2

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 0,
    'email_on_failure': False,
}

dag = DAG(
    'rdb_backfill',
    default_args=default_args,
    description='ETF 과거 가격 백필 (수동 트리거)',
    schedule_interval=None,
    catchup=False,
    tags=['portfolio', 'backfill', 'prices'],
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


def backfill_prices(**context):
    """etfs 테이블의 전체 ETF에 대해 yfinance로 과거 종가를 수집하여 ticker_prices에 upsert."""
    import yfinance as yf
    import pandas as pd

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # 전체 ETF 코드 조회
        cur.execute("SELECT code FROM etfs ORDER BY code")
        codes = [row[0] for row in cur.fetchall()]
        cur.close()

        if not codes:
            log.info("No ETF codes found in etfs table")
            return

        log.info(f"Total ETFs to backfill: {len(codes)}")
        end_date = date.today().isoformat()

        batches = [codes[i:i + BATCH_SIZE] for i in range(0, len(codes), BATCH_SIZE)]
        total_batches = len(batches)

        total_rows = 0
        success_tickers = set()
        failed_tickers = []

        for batch_idx, batch_codes in enumerate(batches, start=1):
            yf_tickers = [f"{code}.KS" for code in batch_codes]
            log.info(f"[batch {batch_idx}/{total_batches}] Downloading {len(yf_tickers)} tickers...")

            try:
                data = yf.download(yf_tickers, start=START_DATE, end=end_date, progress=False, threads=True)
            except Exception as e:
                log.error(f"[batch {batch_idx}] Download error: {e}")
                failed_tickers.extend(batch_codes)
                continue

            if data is None or data.empty:
                failed_tickers.extend(batch_codes)
                continue

            is_multi = isinstance(data.columns, pd.MultiIndex)
            batch_rows = 0
            cur = conn.cursor()

            for code, yf_ticker in zip(batch_codes, yf_tickers):
                try:
                    if is_multi:
                        ticker_data = data.xs(yf_ticker, level="Ticker", axis=1)
                    else:
                        ticker_data = data

                    if ticker_data is None or ticker_data.empty:
                        failed_tickers.append(code)
                        continue

                    count = 0
                    for idx, row in ticker_data.iterrows():
                        d = idx.date() if hasattr(idx, 'date') else idx
                        try:
                            close = Decimal(str(int(row["Close"])))
                        except (ValueError, TypeError, KeyError):
                            continue
                        cur.execute("""
                            INSERT INTO ticker_prices (ticker, date, price, updated_at)
                            VALUES (%s, %s, %s, NOW())
                            ON CONFLICT (ticker, date)
                            DO UPDATE SET price = EXCLUDED.price, updated_at = NOW()
                        """, (code, d.isoformat(), close))
                        count += 1

                    batch_rows += count
                    if count > 0:
                        success_tickers.add(code)
                    else:
                        failed_tickers.append(code)
                except Exception as e:
                    log.warning(f"Error processing {code}: {e}")
                    conn.rollback()
                    failed_tickers.append(code)

            conn.commit()
            cur.close()
            total_rows += batch_rows
            log.info(f"[batch {batch_idx}/{total_batches}] Upserted {batch_rows} rows")

            if batch_idx < total_batches:
                time.sleep(SLEEP_BETWEEN_BATCHES)

        # 실패 티커 개별 재시도
        if failed_tickers:
            unique_failed = list(dict.fromkeys(failed_tickers))
            log.info(f"Retrying {len(unique_failed)} failed tickers individually...")
            cur = conn.cursor()
            retry_rows = 0

            for i, code in enumerate(unique_failed, start=1):
                try:
                    hist = yf.Ticker(f"{code}.KS").history(start=START_DATE, end=end_date)
                    if hist is not None and not hist.empty:
                        count = 0
                        for idx, row in hist.iterrows():
                            d = idx.date() if hasattr(idx, 'date') else idx
                            try:
                                close = Decimal(str(int(row["Close"])))
                            except (ValueError, TypeError, KeyError):
                                continue
                            cur.execute("""
                                INSERT INTO ticker_prices (ticker, date, price, updated_at)
                                VALUES (%s, %s, %s, NOW())
                                ON CONFLICT (ticker, date)
                                DO UPDATE SET price = EXCLUDED.price, updated_at = NOW()
                            """, (code, d.isoformat(), close))
                            count += 1
                        conn.commit()
                        retry_rows += count
                        if count > 0:
                            success_tickers.add(code)
                            log.info(f"  Retry [{i}/{len(unique_failed)}] {code}: {count} rows")
                except Exception as e:
                    log.warning(f"  Retry [{i}/{len(unique_failed)}] {code} failed: {e}")
                    conn.rollback()
                time.sleep(1)

            cur.close()
            total_rows += retry_rows

        final_failed = [c for c in dict.fromkeys(failed_tickers) if c not in success_tickers]

        log.info("=" * 50)
        log.info(f"Backfill complete.")
        log.info(f"  Total rows upserted : {total_rows}")
        log.info(f"  Success tickers     : {len(success_tickers)}")
        log.info(f"  Failed tickers      : {len(final_failed)}")
        if final_failed:
            log.info(f"  Failed codes        : {final_failed[:20]}{'...' if len(final_failed) > 20 else ''}")

    finally:
        conn.close()


task_backfill = PythonOperator(
    task_id='backfill_prices',
    python_callable=backfill_prices,
    dag=dag,
)
