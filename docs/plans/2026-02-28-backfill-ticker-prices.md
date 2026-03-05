# ETF 과거 가격 백필 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** RDB `etfs` 테이블의 전체 1,070개 ETF에 대해 2025-01-01부터 현재까지 일별 종가를 `ticker_prices`에 백필한다.

**Architecture:** 단발성 Python 스크립트가 DB에서 ETF 코드를 조회하고, yfinance 배치 다운로드로 가격을 수집한 뒤, psycopg2로 upsert한다. 기존 `scripts/` uv 프로젝트에 yfinance 의존성을 추가한다.

**Tech Stack:** Python 3.12, yfinance, psycopg2-binary, uv

---

### Task 1: scripts 프로젝트에 yfinance 의존성 추가

**Files:**
- Modify: `scripts/pyproject.toml`

**Step 1: pyproject.toml에 yfinance 추가**

`scripts/pyproject.toml`의 dependencies에 추가:
```toml
dependencies = [
    "streamlit>=1.30.0",
    "psycopg2-binary>=2.9.9",
    "pyvis>=0.3.2",
    "networkx>=3.0",
    "pandas>=2.0.0",
    "pykrx==1.2.3",
    "yfinance>=0.2.36",
]
```

**Step 2: 의존성 설치**

Run: `cd scripts && uv sync`
Expected: yfinance 및 관련 의존성 설치 완료

**Step 3: Commit**

```bash
git add scripts/pyproject.toml scripts/uv.lock
git commit -m "chore: add yfinance dependency to scripts project"
```

---

### Task 2: 백필 스크립트 작성

**Files:**
- Create: `scripts/backfill_ticker_prices.py`

**Step 1: 스크립트 작성**

```python
"""
ETF 과거 가격 백필 스크립트
- RDB etfs 테이블의 전체 ETF에 대해 2025-01-01~오늘 일별 종가를 ticker_prices에 upsert
- yfinance 배치 다운로드 사용, 20개씩 배치 처리
- 실행: cd scripts && uv run python backfill_ticker_prices.py
"""

import os
import time
import logging
from datetime import datetime, date
from decimal import Decimal

import psycopg2
import yfinance as yf

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:9602/etf_atlas",
)
BATCH_SIZE = 20
START_DATE = "2025-01-01"
SLEEP_BETWEEN_BATCHES = 2


def parse_db_url(url: str) -> dict:
    url = url.replace("postgresql://", "")
    auth, host_db = url.split("@")
    user, password = auth.split(":")
    host_port, database = host_db.split("/")
    if ":" in host_port:
        host, port = host_port.split(":")
    else:
        host, port = host_port, 5432
    return dict(host=host, port=int(port), database=database, user=user, password=password)


def get_etf_codes(conn) -> list[str]:
    """etfs 테이블에서 전체 ETF 코드 조회."""
    cur = conn.cursor()
    cur.execute("SELECT code FROM etfs ORDER BY code")
    codes = [row[0] for row in cur.fetchall()]
    cur.close()
    return codes


def upsert_prices(conn, ticker: str, hist) -> int:
    """히스토리 DataFrame에서 종가를 ticker_prices에 upsert. 삽입 건수 반환."""
    if hist.empty:
        return 0

    cur = conn.cursor()
    count = 0
    for idx, row in hist.iterrows():
        d = idx.date() if hasattr(idx, "date") else idx
        try:
            close = Decimal(str(int(row["Close"])))
        except (ValueError, KeyError):
            continue
        cur.execute(
            """
            INSERT INTO ticker_prices (ticker, date, price, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (ticker, date)
            DO UPDATE SET price = EXCLUDED.price, updated_at = NOW()
            """,
            (ticker, d.isoformat(), close),
        )
        count += 1
    cur.close()
    return count


def download_batch(yf_tickers: list[str], start: str, end: str):
    """yfinance 배치 다운로드. 실패 시 빈 DataFrame 반환."""
    try:
        data = yf.download(yf_tickers, start=start, end=end, progress=False, threads=True)
        return data
    except Exception as e:
        log.error(f"Batch download failed: {e}")
        return None


def main():
    end_date = date.today().isoformat()
    conn = psycopg2.connect(**parse_db_url(DB_URL))

    try:
        codes = get_etf_codes(conn)
        log.info(f"Total ETFs: {len(codes)}")

        batches = [codes[i : i + BATCH_SIZE] for i in range(0, len(codes), BATCH_SIZE)]
        total_upserted = 0
        success_tickers = 0
        failed_tickers = []

        for batch_idx, batch in enumerate(batches, 1):
            yf_tickers = [f"{code}.KS" for code in batch]
            log.info(f"[batch {batch_idx}/{len(batches)}] Downloading {len(batch)} tickers...")

            data = download_batch(yf_tickers, START_DATE, end_date)

            if data is None or data.empty:
                failed_tickers.extend(batch)
                log.warning(f"[batch {batch_idx}] All failed")
                continue

            batch_upserted = 0
            for code in batch:
                yf_ticker = f"{code}.KS"
                try:
                    if len(batch) == 1:
                        ticker_data = data
                    else:
                        ticker_data = data.xs(yf_ticker, level="Ticker", axis=1)

                    if ticker_data.empty or ticker_data["Close"].dropna().empty:
                        failed_tickers.append(code)
                        continue

                    count = upsert_prices(conn, code, ticker_data)
                    batch_upserted += count
                    success_tickers += 1
                except (KeyError, TypeError):
                    failed_tickers.append(code)

            conn.commit()
            total_upserted += batch_upserted
            log.info(f"[batch {batch_idx}] Upserted {batch_upserted} rows")

            if batch_idx < len(batches):
                time.sleep(SLEEP_BETWEEN_BATCHES)

        # 실패 티커 재시도 (개별)
        if failed_tickers:
            log.info(f"Retrying {len(failed_tickers)} failed tickers individually...")
            retry_success = 0
            for code in failed_tickers:
                try:
                    hist = yf.Ticker(f"{code}.KS").history(start=START_DATE, end=end_date)
                    if not hist.empty:
                        count = upsert_prices(conn, code, hist)
                        total_upserted += count
                        retry_success += 1
                    conn.commit()
                    time.sleep(1)
                except Exception as e:
                    log.warning(f"Retry failed for {code}: {e}")

            log.info(f"Retry complete: {retry_success}/{len(failed_tickers)} recovered")
            failed_tickers = [c for c in failed_tickers if c not in []]  # recalc below

        log.info("=" * 50)
        log.info(f"Done! Total rows upserted: {total_upserted}")
        log.info(f"Success: {success_tickers} tickers")
        log.info(f"Initially failed: {len(failed_tickers)} tickers")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
```

**Step 2: 스크립트 실행 테스트**

Run: `cd scripts && uv run python backfill_ticker_prices.py`
Expected: 1,070개 ETF에 대해 배치별 로그 출력, 완료 시 요약 출력

**Step 3: DB에서 결과 확인**

Run: `docker exec etf-atlas-db psql -U postgres -d etf_atlas -c "SELECT COUNT(*), MIN(date), MAX(date) FROM ticker_prices;"`
Expected: min date가 2025-01-02 (첫 거래일) 근처, 행 수 대폭 증가

**Step 4: Commit**

```bash
git add scripts/backfill_ticker_prices.py
git commit -m "feat: add one-time ETF price backfill script (2025-01~present)"
```
