# 실시간 현재가 수집 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 장중 10분마다 포트폴리오 보유 종목의 현재가를 RDB에 수집하고, PriceService를 단순화하여 API 응답 속도를 개선한다.

**Architecture:** 새 `ticker_prices` RDB 테이블에 현재가를 저장하고, PriceService의 폴백 체인을 `캐시→RDB→yfinance`로 변경한다. 새 Airflow DAG가 10분마다 가격 수집 + 스냅샷 갱신을 담당하며, 기존 portfolio_snapshot DAG는 제거한다.

**Tech Stack:** PostgreSQL, SQLAlchemy ORM, Airflow, yfinance, pykrx

---

### Task 1: `ticker_prices` 테이블 추가

**Files:**
- Modify: `docker/db/init/01_extensions.sql:112-135` (테이블 정의 섹션)

**Step 1: SQL 테이블 정의 추가**

`01_extensions.sql`의 `portfolio_snapshots` 테이블 뒤 (124행 이후)에 추가:

```sql
-- Ticker Prices (실시간 현재가 캐시 - 티커별 하루 1건)
CREATE TABLE IF NOT EXISTS ticker_prices (
    ticker     VARCHAR(20)    NOT NULL,
    date       DATE           NOT NULL,
    price      NUMERIC(18, 2) NOT NULL,
    updated_at TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_ticker_prices_date ON ticker_prices(date);
```

**Step 2: 기존 DB에 테이블 수동 생성**

기존 DB에는 init SQL이 다시 실행되지 않으므로, 컨테이너에 직접 실행:

```bash
docker compose exec db psql -U postgres -d etf_atlas -c "
CREATE TABLE IF NOT EXISTS ticker_prices (
    ticker     VARCHAR(20)    NOT NULL,
    date       DATE           NOT NULL,
    price      NUMERIC(18, 2) NOT NULL,
    updated_at TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_ticker_prices_date ON ticker_prices(date);
"
```

**Step 3: Commit**

```bash
git add docker/db/init/01_extensions.sql
git commit -m "feat: ticker_prices 테이블 추가 (실시간 현재가 캐시)"
```

---

### Task 2: `TickerPrice` ORM 모델 추가

**Files:**
- Create: `backend/app/models/ticker_price.py`
- Modify: `backend/app/models/__init__.py`

**Step 1: ORM 모델 작성**

`backend/app/models/ticker_price.py`:

```python
from sqlalchemy import Column, String, Date, Numeric, DateTime, PrimaryKeyConstraint
from datetime import datetime
from ..database import Base


class TickerPrice(Base):
    __tablename__ = "ticker_prices"
    __table_args__ = (PrimaryKeyConstraint("ticker", "date"),)

    ticker = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    price = Column(Numeric(18, 2), nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
```

**Step 2: `__init__.py`에 등록**

`backend/app/models/__init__.py`에 import 추가:

```python
from .ticker_price import TickerPrice
```

`__all__` 리스트에 `"TickerPrice"` 추가.

**Step 3: Commit**

```bash
git add backend/app/models/ticker_price.py backend/app/models/__init__.py
git commit -m "feat: TickerPrice ORM 모델 추가"
```

---

### Task 3: `PriceService` 리팩토링 — AGE 제거, RDB 우선 조회

**Files:**
- Modify: `backend/app/services/price_service.py`

**Step 1: PriceService 수정**

`backend/app/services/price_service.py` 전체를 다음으로 교체:

```python
import time
from decimal import Decimal
from datetime import date, timezone, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text


# Module-level cache: {ticker: (price, timestamp)}
_price_cache: dict[str, tuple[Decimal, float]] = {}
_CACHE_TTL = 60  # seconds


def _today_kst() -> date:
    """KST 기준 오늘 날짜."""
    kst = timezone(timedelta(hours=9))
    return date.today()  # 서버가 KST라 가정; 필요시 datetime.now(kst).date()


class PriceService:
    def __init__(self, db: Session):
        self.db = db

    def get_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        """
        Get latest prices for tickers.
        Strategy:
        1. Return cached prices if within 60 seconds
        2. RDB ticker_prices 테이블에서 최신 가격 조회
        3. 없으면 yfinance로 조회 (폴백)
        CASH is excluded (handled by domain layer).
        """
        query_tickers = [t for t in tickers if t != "CASH"]
        if not query_tickers:
            return {}

        now = time.time()
        prices: dict[str, Decimal] = {}

        # Step 1: Check cache
        missing = []
        for ticker in query_tickers:
            cached = _price_cache.get(ticker)
            if cached and (now - cached[1]) < _CACHE_TTL:
                prices[ticker] = cached[0]
            else:
                missing.append(ticker)

        if not missing:
            return prices

        # Step 2: RDB ticker_prices (최신 날짜 기준)
        rdb_prices = self._get_rdb_prices(missing)
        for ticker, price in rdb_prices.items():
            _price_cache[ticker] = (price, now)
            prices[ticker] = price

        still_missing = [t for t in missing if t not in prices]
        if not still_missing:
            return prices

        # Step 3: yfinance fallback
        yf_prices = self._get_yfinance_prices(still_missing)
        for ticker, price in yf_prices.items():
            _price_cache[ticker] = (price, now)
            prices[ticker] = price

        return prices

    def _get_rdb_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        """ticker_prices 테이블에서 각 티커의 최신 가격 조회 (batch)."""
        if not tickers:
            return {}

        result = self.db.execute(
            text("""
                SELECT DISTINCT ON (ticker) ticker, price
                FROM ticker_prices
                WHERE ticker = ANY(:tickers)
                ORDER BY ticker, date DESC
            """),
            {"tickers": tickers},
        )
        return {row.ticker: Decimal(str(row.price)) for row in result}

    def _get_yfinance_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        """Fetch prices from yfinance with .KS suffix for KRX stocks."""
        prices: dict[str, Decimal] = {}
        try:
            import yfinance as yf
            for ticker in tickers:
                try:
                    yf_ticker = f"{ticker}.KS"
                    info = yf.Ticker(yf_ticker)
                    hist = info.history(period="5d")
                    if not hist.empty:
                        close = hist["Close"].iloc[-1]
                        prices[ticker] = Decimal(str(int(close)))
                except Exception:
                    continue
        except ImportError:
            pass
        return prices

    def get_etf_names(self, tickers: list[str]) -> dict[str, str]:
        """Get ETF names from the etfs table."""
        if not tickers:
            return {}

        query_tickers = [t for t in tickers if t != "CASH"]
        names: dict[str, str] = {}

        if "CASH" in tickers:
            names["CASH"] = "현금"

        if not query_tickers:
            return names

        result = self.db.execute(
            text("SELECT code, name FROM etfs WHERE code = ANY(:tickers)"),
            {"tickers": query_tickers}
        )
        for row in result:
            names[row.code] = row.name

        for t in query_tickers:
            if t not in names:
                names[t] = t

        return names
```

핵심 변경:
- `GraphService` import 및 의존성 제거
- `__init__`에서 `graph_service` 파라미터 제거
- AGE 조회 (step 2, 4) → RDB `_get_rdb_prices()` 1개 메서드로 교체
- `DISTINCT ON` + `ORDER BY date DESC`로 배치 조회 (N+1 해소)

**Step 2: PriceService 생성자 호출부 확인**

`PriceService(db)` 로 이미 호출하는 곳 (portfolio.py:296, 656). `graph_service` 인자를 전달하지 않으므로 변경 불필요.
단, `PriceService(db, graph_service)` 로 호출하는 곳이 있으면 수정 필요 — 현재 코드에는 없음.

**Step 3: Commit**

```bash
git add backend/app/services/price_service.py
git commit -m "refactor: PriceService AGE 의존 제거, RDB ticker_prices 우선 조회로 변경"
```

---

### Task 4: 새 Airflow DAG `collect_realtime_prices` 작성

**Files:**
- Create: `airflow/dags/collect_realtime_prices.py`

**Step 1: DAG 작성**

`airflow/dags/collect_realtime_prices.py`:

```python
"""
Realtime Price Collection DAG
- 장중 10분마다 포트폴리오 보유 종목의 현재가를 RDB에 업서트
- 현재가 업서트 후 포트폴리오 스냅샷도 갱신
- 거래일 + 장중(09:00~15:30) 여부를 체크하여 불필요한 실행 방지
"""

from datetime import datetime, timedelta, timezone, date
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
    'collect_realtime_prices',
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
```

**Step 2: Commit**

```bash
git add airflow/dags/collect_realtime_prices.py
git commit -m "feat: 장중 10분 주기 현재가 수집 DAG 추가"
```

---

### Task 5: `portfolio_snapshot.py` DAG 제거

**Files:**
- Delete: `airflow/dags/portfolio_snapshot.py`

**Step 1: 삭제**

```bash
git rm airflow/dags/portfolio_snapshot.py
```

**Step 2: Commit**

```bash
git commit -m "refactor: portfolio_snapshot DAG 제거 (collect_realtime_prices로 통합)"
```

---

### Task 6: 배포 및 검증

**Step 1: Backend 컨테이너 리빌드**

PriceService 변경이 반영되려면 backend 리빌드 필요:

```bash
docker compose up -d --build backend
```

**Step 2: DB 테이블 생성**

```bash
docker compose exec db psql -U postgres -d etf_atlas -c "
CREATE TABLE IF NOT EXISTS ticker_prices (
    ticker     VARCHAR(20)    NOT NULL,
    date       DATE           NOT NULL,
    price      NUMERIC(18, 2) NOT NULL,
    updated_at TIMESTAMP      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_ticker_prices_date ON ticker_prices(date);
"
```

**Step 3: Airflow DAG 확인**

Airflow UI에서:
- `portfolio_snapshot` DAG가 사라졌는지 확인
- `collect_realtime_prices` DAG가 나타나는지 확인
- DAG 수동 트리거하여 정상 동작 확인

**Step 4: API 응답 확인**

```bash
# 리밸런싱 계산 API 호출 후 응답 시간 확인
curl -w "\n%{time_total}s\n" -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/portfolios/<id>/calculate
```

**Step 5: Commit (전체 변경 사항이 모두 반영된 경우)**

```bash
git add -A
git commit -m "chore: 실시간 현재가 수집 기능 배포 확인"
```
