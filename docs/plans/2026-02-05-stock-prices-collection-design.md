# Stock 가격 수집 기능 설계

## 개요

ETF가 보유한 Stock(주식)의 일별 가격 데이터를 수집한다.
보유종목 중 ETF인 것은 가격 수집에서 제외하되, 그래프에는 저장하여 관계 정보를 유지한다.

## 요구사항

1. 관리 중인 Stock들의 종가/상승률 매일 수집
2. 보유종목 중 ETF인 것은 가격 수집 제외 (그래프에는 저장)
3. ETF 보유종목의 경우 ETF명이 표시되도록

## 데이터 소스

- pykrx 라이브러리 사용 (기존 프로젝트에서 사용 중)
- `stock.get_market_ohlcv_by_ticker(date)` - 전체 종목 OHLCV 한 번에 조회

---

## 설계

### 1. Stock 노드 변경

**현재:**
```
(Stock {code, name})
```

**변경 후:**
```
(Stock {code, name, is_etf})
```

**collect_holdings 로직 변경:**
```python
# 보유종목이 ETF인지 확인
etf_tickers = set(stock.get_etf_ticker_list(date))

for stock_code in holdings:
    is_etf = stock_code in etf_tickers

    if is_etf:
        # ETF면 ETF 이름 조회
        stock_name = stock.get_etf_ticker_name(stock_code)
    else:
        # 주식이면 주식 이름 조회
        stock_name = stock.get_market_ticker_name(stock_code)

    # Stock 노드 저장 (is_etf 속성 포함)
    MERGE (s:Stock {code: $code})
    SET s.name = $name, s.is_etf = $is_etf
```

### 2. stock_prices 테이블

```sql
CREATE TABLE IF NOT EXISTS stock_prices (
    stock_code VARCHAR(20) NOT NULL,
    date DATE NOT NULL,
    open_price DECIMAL(12, 2),
    high_price DECIMAL(12, 2),
    low_price DECIMAL(12, 2),
    close_price DECIMAL(12, 2),
    volume BIGINT,
    change_rate DECIMAL(8, 4),  -- 등락률 (%)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (stock_code, date)
);

CREATE INDEX IF NOT EXISTS idx_stock_prices_date ON stock_prices(date);
```

### 3. ETL 태스크 추가

**새 태스크: `collect_stock_prices`**
```python
def collect_stock_prices(**context):
    """Stock 가격 데이터 수집 (is_etf=false인 Stock만)"""
    from pykrx import stock

    # 1. 그래프에서 is_etf=false인 Stock 코드 목록 조회
    cypher = """
        MATCH (s:Stock {is_etf: false})
        RETURN s.code
    """
    stock_codes = execute_cypher(cur, cypher)

    # 2. pykrx로 해당 날짜 전체 주식 OHLCV 조회 (한 번에)
    df = stock.get_market_ohlcv_by_ticker(date)

    # 3. stock_codes에 해당하는 것만 필터링해서 저장
    for code in stock_codes:
        if code in df.index:
            # stock_prices 테이블에 INSERT
```

**DAG 의존성:**
```
현재:
collect_holdings → detect_changes → end

변경:
collect_holdings → [collect_stock_prices, detect_changes] → end
```

---

## 변경 파일 목록

1. `docker/db/init/01_extensions.sql` - stock_prices 테이블 추가
2. `airflow/dags/etf_daily_etl.py` - collect_holdings 수정, collect_stock_prices 태스크 추가
