# pykrx 데이터 매핑

## 개요

pykrx 라이브러리를 통해 수집하는 데이터와 DB 저장 구조 매핑

---

## ETF 유니버스 정의

### 포함 조건

| 조건 | 설명 |
|------|------|
| 국내 주식형 ETF | 국내 상장 주식으로 구성 |
| 해외 주식형 ETF | S&P500, 나스닥, 해외 섹터 등 |
| 순자산 1,000억 이상 | 유동성 확보 |

### 제외 조건

| 조건 | 제외 이유 |
|------|----------|
| 합성 ETF | 실물 구성종목 없음 (스왑 계약) |
| 파생 ETF | 선물/옵션 기반 |
| 레버리지/인버스 ETF | 파생 상품, 일별 수익률 추종 |
| 커버드콜 ETF | 옵션 전략 포함 |
| 채권 ETF | 주식 종목 아님 |
| 원자재/금 ETF | 주식 종목 아님 |
| 통화 ETF | 주식 종목 아님 |

### 필터링 로직

```python
def filter_etf_universe(etf_list: list) -> list:
    """ETF 유니버스 필터링"""

    # 제외 키워드 (ETF 이름 기준)
    EXCLUDE_KEYWORDS = [
        # 레버리지/인버스
        '레버리지', '인버스', '2X', '곱버스',
        # 합성/파생
        '합성', '선물',
        # 커버드콜
        '커버드콜', '커버드', 'covered',
        # 채권
        '채권', '국채', '회사채', '크레딧', '금리',
        # 원자재/금/통화
        '금현물', '골드', 'gold', '은현물', '원유', 'WTI',
        '달러', '엔화', '유로', '원화',
    ]

    # 순자산 기준 (억원)
    MIN_ASSET = 1000

    filtered = []
    for etf in etf_list:
        name_lower = etf['name'].lower()

        # 제외 키워드 체크
        if any(kw.lower() in name_lower for kw in EXCLUDE_KEYWORDS):
            continue

        # 순자산 체크
        if etf.get('total_asset', 0) < MIN_ASSET:
            continue

        filtered.append(etf)

    return filtered
```

### 예상 유니버스 규모

| 전체 ETF | 필터 후 예상 |
|----------|-------------|
| ~700개 | ~150~200개 |

---

## 1. ETF 목록 수집

### pykrx 함수

```python
from pykrx import stock

# 특정 날짜의 ETF 티커 목록
tickers = stock.get_etf_ticker_list("20250201")
# ['152100', '069500', '278530', ...]
```

### 추가 정보 수집

```python
# ETF 기본 정보 (개별 조회 필요)
# pykrx에서 직접 제공하지 않는 정보는 KRX 정보데이터시스템 참조 필요

# 시가총액/순자산 조회
df = stock.get_etf_ohlcv_by_date("20250101", "20250201", "152100")
```

### DB 매핑 (Apache AGE - ETF 노드)

| pykrx | DB 필드 | 타입 | 비고 |
|-------|---------|------|------|
| ticker | code | string | PK |
| - | name | string | 별도 수집 필요 |
| - | type | string | 액티브/패시브 분류 필요 |
| - | manager | string | 별도 수집 필요 |
| - | inception_date | date | 별도 수집 필요 |

### ETF 메타정보 수집 방안

pykrx에서 ETF 이름, 운용사 등 메타정보 직접 제공하지 않음.

**대안 1: KRX 정보데이터시스템 크롤링**
```python
# http://data.krx.co.kr/contents/MDC/MDI/mdiLoader
# ETF 종목정보 페이지에서 수집
```

**대안 2: 네이버 금융 크롤링**
```python
# https://finance.naver.com/api/sise/etfItemList.nhn
import requests

url = "https://finance.naver.com/api/sise/etfItemList.nhn"
params = {"etfType": 0}  # 0: 국내, 1: 해외
response = requests.get(url, params=params)
data = response.json()

# 결과 예시
# {
#   "etfItemList": [
#     {
#       "itemcode": "152100",
#       "itemname": "TIGER 200",
#       "aession": "미래에셋자산운용",
#       ...
#     }
#   ]
# }
```

**대안 3: 초기 데이터 CSV 준비**
- ETF 메타정보를 CSV로 준비하여 초기 로드
- 이후 신규 ETF만 수동/반자동 추가

---

## 2. ETF 구성종목 (PDF) 수집

### pykrx 함수

```python
from pykrx import stock

# ETF PDF (Portfolio Deposit File) 조회
df = stock.get_etf_portfolio_deposit_file("152100")
```

### 반환 데이터 구조

```python
# DataFrame 컬럼
# - 티커: 종목 코드 (예: '005930')
# - 종목명: 종목 이름 (예: '삼성전자')
# - 비중: 비중 (%) (예: 25.13)
# - 평가금액: 평가금액 (원)
# - 주수: 보유 주수

df.columns
# Index(['티커', '종목명', '비중', '평가금액', '주수'], dtype='object')
```

### 샘플 데이터

```
      티커     종목명     비중        평가금액      주수
0   005930   삼성전자   25.13   5000000000    70000
1   000660  SK하이닉스  12.45   2500000000    15000
2   005380     현대차    8.23   1650000000    12000
...
```

### DB 매핑 (Apache AGE - HOLDS 엣지)

| pykrx 컬럼 | DB 필드 | 타입 | 비고 |
|------------|---------|------|------|
| 티커 | stock_code | string | Stock 노드 연결 |
| 종목명 | stock_name | string | Stock 노드에 저장 |
| 비중 | weight | float | 엣지 속성 |
| 주수 | shares | bigint | 엣지 속성 |
| (수집일) | date | date | 엣지 속성, 스냅샷 날짜 |

### 저장 로직

```python
def save_holdings(etf_code: str, date: str, df: pd.DataFrame):
    """ETF 구성종목을 그래프 DB에 저장"""

    for _, row in df.iterrows():
        # 1. Stock 노드 생성/업데이트
        create_or_update_stock(
            code=row['티커'],
            name=row['종목명']
        )

        # 2. HOLDS 엣지 생성
        create_holds_edge(
            etf_code=etf_code,
            stock_code=row['티커'],
            date=date,
            weight=row['비중'],
            shares=row['주수']
        )
```

---

## 3. ETF 가격 데이터 수집

### pykrx 함수

```python
from pykrx import stock

# 기간별 OHLCV 조회
df = stock.get_etf_ohlcv_by_date("20250101", "20250201", "152100")
```

### 반환 데이터 구조

```python
# DataFrame 인덱스: 날짜 (DatetimeIndex)
# DataFrame 컬럼
# - NAV: 순자산가치
# - 시가, 고가, 저가, 종가: 가격
# - 거래량: 거래량
# - 거래대금: 거래대금
# - 기초지수: 추종 지수값

df.columns
# Index(['NAV', '시가', '고가', '저가', '종가', '거래량', '거래대금', '기초지수'], dtype='object')
```

### 샘플 데이터

```
               NAV    시가    고가    저가    종가     거래량      거래대금    기초지수
날짜
2025-01-02  35123  35100  35300  35000  35200   500000  17500000000   2845.23
2025-01-03  35456  35250  35500  35200  35450   620000  21900000000   2867.45
...
```

### DB 매핑 (PostgreSQL - etf_price 테이블)

| pykrx 컬럼 | DB 필드 | 타입 | 비고 |
|------------|---------|------|------|
| (index) | date | date | PK |
| (파라미터) | etf_code | varchar | PK |
| 시가 | open | int | |
| 고가 | high | int | |
| 저가 | low | int | |
| 종가 | close | int | |
| 거래량 | volume | bigint | |

### 저장 로직

```python
def save_prices(etf_code: str, df: pd.DataFrame):
    """ETF 가격 데이터를 RDB에 저장"""

    records = []
    for date, row in df.iterrows():
        records.append({
            'etf_code': etf_code,
            'date': date.strftime('%Y-%m-%d'),
            'open': int(row['시가']),
            'high': int(row['고가']),
            'low': int(row['저가']),
            'close': int(row['종가']),
            'volume': int(row['거래량'])
        })

    # Upsert (ON CONFLICT UPDATE)
    bulk_upsert_prices(records)
```

---

## 4. 포트폴리오 변화 감지

### 로직

```python
def detect_changes(etf_code: str, today: str, yesterday: str) -> list:
    """두 스냅샷 비교하여 변화 감지"""

    today_holdings = get_holdings(etf_code, today)      # {stock_code: weight}
    yesterday_holdings = get_holdings(etf_code, yesterday)

    changes = []

    # 신규 편입
    for code in today_holdings:
        if code not in yesterday_holdings:
            changes.append({
                'type': 'NEW',
                'stock_code': code,
                'before_weight': None,
                'after_weight': today_holdings[code]
            })

    # 완전 제외
    for code in yesterday_holdings:
        if code not in today_holdings:
            changes.append({
                'type': 'REMOVED',
                'stock_code': code,
                'before_weight': yesterday_holdings[code],
                'after_weight': None
            })

    # 비중 5%p 이상 변화
    for code in today_holdings:
        if code in yesterday_holdings:
            diff = today_holdings[code] - yesterday_holdings[code]
            if abs(diff) >= 5.0:
                changes.append({
                    'type': 'WEIGHT_CHANGE',
                    'stock_code': code,
                    'before_weight': yesterday_holdings[code],
                    'after_weight': today_holdings[code]
                })

    return changes
```

### DB 매핑 (Apache AGE - Change 노드)

| 필드 | 타입 | 설명 |
|------|------|------|
| id | string | UUID |
| date | date | 변화 감지 날짜 |
| type | string | "NEW" \| "REMOVED" \| "WEIGHT_CHANGE" |
| stock_code | string | 종목 코드 |
| stock_name | string | 종목명 |
| before_weight | float | 이전 비중 (nullable) |
| after_weight | float | 이후 비중 (nullable) |

---

## 5. Airflow DAG 구조

```python
# airflow/dags/etf_daily_etl.py

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'etf_daily_etl',
    default_args=default_args,
    description='ETF 데이터 일일 수집',
    schedule_interval='0 8 * * 1-5',  # 평일 08:00 KST
    catchup=False,
)

# Task 1: ETF 목록 수집
def collect_etf_list(**context):
    from pykrx import stock
    date = context['ds_nodash']
    tickers = stock.get_etf_ticker_list(date)
    return tickers

task_etf_list = PythonOperator(
    task_id='collect_etf_list',
    python_callable=collect_etf_list,
    dag=dag,
)

# Task 2: 구성종목 수집
def collect_holdings(**context):
    from pykrx import stock
    tickers = context['ti'].xcom_pull(task_ids='collect_etf_list')

    for ticker in tickers:
        try:
            df = stock.get_etf_portfolio_deposit_file(ticker)
            save_holdings(ticker, context['ds'], df)
        except Exception as e:
            log.error(f"Failed to collect holdings for {ticker}: {e}")

task_holdings = PythonOperator(
    task_id='collect_holdings',
    python_callable=collect_holdings,
    dag=dag,
)

# Task 3: 가격 수집
def collect_prices(**context):
    from pykrx import stock
    tickers = context['ti'].xcom_pull(task_ids='collect_etf_list')
    date = context['ds_nodash']

    for ticker in tickers:
        try:
            df = stock.get_etf_ohlcv_by_date(date, date, ticker)
            save_prices(ticker, df)
        except Exception as e:
            log.error(f"Failed to collect prices for {ticker}: {e}")

task_prices = PythonOperator(
    task_id='collect_prices',
    python_callable=collect_prices,
    dag=dag,
)

# Task 4: 변화 감지
def detect_portfolio_changes(**context):
    today = context['ds']
    yesterday = (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
    tickers = context['ti'].xcom_pull(task_ids='collect_etf_list')

    for ticker in tickers:
        try:
            changes = detect_changes(ticker, today, yesterday)
            if changes:
                save_changes(ticker, today, changes)
        except Exception as e:
            log.error(f"Failed to detect changes for {ticker}: {e}")

task_detect_changes = PythonOperator(
    task_id='detect_changes',
    python_callable=detect_portfolio_changes,
    dag=dag,
)

# 의존성
task_etf_list >> [task_holdings, task_prices]
task_holdings >> task_detect_changes
```

---

## 6. 데이터 수집 주의사항

### pykrx 제한사항

| 항목 | 내용 |
|------|------|
| 호출 제한 | 명시적 제한 없으나 과도한 호출 시 차단 가능 |
| 데이터 지연 | 당일 데이터는 장 마감 후 제공 |
| PDF 미제공 ETF | 일부 ETF는 PDF 미제공 |

### 권장 사항

```python
import time

def collect_with_delay(tickers, delay=0.5):
    """API 호출 간 딜레이 추가"""
    for ticker in tickers:
        try:
            df = stock.get_etf_portfolio_deposit_file(ticker)
            yield ticker, df
        except Exception as e:
            yield ticker, None
        time.sleep(delay)  # 0.5초 딜레이
```

### 에러 처리

| 상황 | 처리 |
|------|------|
| PDF 미제공 | 해당 ETF 스킵, 로그 기록 |
| 네트워크 오류 | 3회 재시도 후 실패 기록 |
| 데이터 이상 | 비중 합계 검증 (90~110% 범위) |

---

## 7. 초기 데이터 로드

### 과거 데이터 백필

```python
def backfill_historical_data(start_date: str, end_date: str):
    """과거 데이터 일괄 수집"""

    from datetime import datetime, timedelta

    current = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')

    while current <= end:
        # 주말 스킵
        if current.weekday() < 5:
            date_str = current.strftime('%Y%m%d')

            # ETF 목록
            tickers = stock.get_etf_ticker_list(date_str)

            # 각 ETF 처리
            for ticker in tickers:
                collect_and_save(ticker, date_str)

        current += timedelta(days=1)

# 최근 6개월 데이터 백필
backfill_historical_data('20240801', '20250201')
```
