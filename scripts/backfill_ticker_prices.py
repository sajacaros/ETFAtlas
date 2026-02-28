"""One-time backfill: download daily close prices for all ETFs from yfinance
and upsert into the ticker_prices table."""
import logging
import os
import time
from datetime import date
from decimal import Decimal

import pandas as pd
import psycopg2
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

DB_URL = os.environ.get('DATABASE_URL', 'postgresql://postgres:postgres@localhost:9602/etf_atlas')

START_DATE = '2025-01-01'
BATCH_SIZE = 20


def parse_db_url(url):
    url = url.replace('postgresql://', '')
    auth, host_db = url.split('@')
    user, password = auth.split(':')
    host_port, database = host_db.split('/')
    if ':' in host_port:
        host, port = host_port.split(':')
    else:
        host, port = host_port, 5432
    return dict(host=host, port=int(port), database=database, user=user, password=password)


def get_etf_codes(conn):
    """Read all ETF codes from the etfs table."""
    cur = conn.cursor()
    cur.execute("SELECT code FROM etfs ORDER BY code")
    codes = [row[0] for row in cur.fetchall()]
    cur.close()
    return codes


def upsert_prices(conn, ticker, hist_df):
    """Upsert daily close prices for a single ticker. Returns the number of rows upserted."""
    if hist_df is None or hist_df.empty:
        return 0

    cur = conn.cursor()
    count = 0
    for idx, row in hist_df.iterrows():
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
        """, (ticker, d.isoformat(), close))
        count += 1

    cur.close()
    return count


def download_batch(yf_tickers, start, end):
    """Download historical data for a batch of tickers. Returns DataFrame or None."""
    try:
        data = yf.download(yf_tickers, start=start, end=end, progress=False, threads=True)
        if data is None or data.empty:
            return None
        return data
    except Exception as e:
        log.error(f"Download error: {e}")
        return None


def main():
    conn = psycopg2.connect(**parse_db_url(DB_URL))
    log.info("Connected to database.")

    try:
        codes = get_etf_codes(conn)
        log.info(f"Found {len(codes)} ETF codes.")

        if not codes:
            log.info("No ETF codes found. Exiting.")
            return

        end_date = date.today().isoformat()

        # Split into batches
        batches = [codes[i:i + BATCH_SIZE] for i in range(0, len(codes), BATCH_SIZE)]
        total_batches = len(batches)

        total_rows = 0
        success_tickers = set()
        failed_tickers = []

        for batch_idx, batch_codes in enumerate(batches, start=1):
            yf_tickers = [f"{code}.KS" for code in batch_codes]
            log.info(f"[batch {batch_idx}/{total_batches}] Downloading {len(yf_tickers)} tickers...")

            data = download_batch(yf_tickers, start=START_DATE, end=end_date)

            batch_rows = 0
            if data is not None and not data.empty:
                is_multi = isinstance(data.columns, pd.MultiIndex)

                for code, yf_ticker in zip(batch_codes, yf_tickers):
                    try:
                        if is_multi:
                            ticker_data = data.xs(yf_ticker, level="Ticker", axis=1)
                        else:
                            ticker_data = data

                        if ticker_data is not None and not ticker_data.empty:
                            rows = upsert_prices(conn, code, ticker_data)
                            batch_rows += rows
                            if rows > 0:
                                success_tickers.add(code)
                        else:
                            failed_tickers.append(code)
                    except Exception as e:
                        log.warning(f"Error processing {code}: {e}")
                        conn.rollback()
                        failed_tickers.append(code)
            else:
                failed_tickers.extend(batch_codes)

            conn.commit()
            log.info(f"[batch {batch_idx}/{total_batches}] Upserted {batch_rows} rows")
            total_rows += batch_rows

            if batch_idx < total_batches:
                time.sleep(2)

        # Retry failed tickers individually
        if failed_tickers:
            unique_failed = list(dict.fromkeys(failed_tickers))
            log.info(f"Retrying {len(unique_failed)} failed tickers individually...")
            retry_rows = 0

            for i, code in enumerate(unique_failed, start=1):
                yf_ticker = f"{code}.KS"
                log.info(f"  Retry [{i}/{len(unique_failed)}] {code}...")
                try:
                    hist = yf.Ticker(yf_ticker).history(start=START_DATE, end=end_date)
                    if hist is not None and not hist.empty:
                        rows = upsert_prices(conn, code, hist)
                        conn.commit()
                        retry_rows += rows
                        if rows > 0:
                            success_tickers.add(code)
                            log.info(f"    Success: {rows} rows")
                        else:
                            log.info(f"    No data")
                    else:
                        log.info(f"    No data returned")
                except Exception as e:
                    log.warning(f"    Error: {e}")
                    conn.rollback()
                time.sleep(1)

            total_rows += retry_rows
            log.info(f"Retry upserted {retry_rows} rows")

        # Final failed list (tickers that never succeeded)
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


if __name__ == '__main__':
    main()
