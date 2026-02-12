# Airflow DAGs

## 1. etf_daily_etl (Apache AGE)

한국 ETF 시장 데이터를 매일 수집하여 Apache AGE 그래프에 저장하는 ETL 파이프라인.

- **DAG ID**: `etf_daily_etl`
- **스케줄**: `0 8 * * 1-5` (평일 08:00 KST)
- **재시도**: 3회, 5분 간격
- **Catchup**: 비활성화

### 데이터 소스

| 소스 | 용도 | 인증 |
|------|------|------|
| KRX Open API (`etf_bydd_trd`) | ETF 일별 시세, 시가총액, 순자산 | `KRX_AUTH_KEY` 환경변수 |
| pykrx 라이브러리 | ETF 메타데이터, 보유종목(PDF), 섹터 분류, 주식 시세 | 불필요 |
| GPT-4.1-mini | 미분류 ETF 태그 자동 부여 | `OPENAI_API_KEY` 환경변수 |

### 태스크 구조

```
start
  └─ fetch_krx_data
       ├─ filter_etf_list
       │    ├─ collect_etf_metadata ─┐
       │    └─ collect_holdings      ├─ tag_new_etfs ─┐
       │         ├─ collect_stock_prices ─────────────┤
       │         └─ detect_portfolio_changes ─────────┤
       └─ collect_prices ────────────────────────────┘
                                                    end
```

### 태스크 상세

#### 1. fetch_krx_data

KRX Open API(`KRXApiClient.get_etf_daily_trading`)로 ETF 전종목 일별매매정보를 수집한다.
누락된 영업일이 있으면 자동으로 백필(과거 데이터 소급 수집)한다.

- AGE에서 마지막 Price 노드의 날짜를 조회하여 백필 시작일을 결정한다.
- DB가 비어있으면(초기 적재) 실행일 기준 45일 전부터 수집하여 약 30 영업일을 확보한다.
- 누락된 평일(월~금)을 순회하며 KRX API를 호출하고, 응답이 없는 날(공휴일)은 자동 skip한다.
- 모든 날짜에서 데이터가 없으면 최근 7일 내 거래일을 탐색하는 fallback을 수행한다.
- 수집 항목: code, name, OHLCV(시가/고가/저가/종가/거래량), 거래대금, NAV, 시가총액, 순자산총액.
- XCom으로 `trading_date`(최신 거래일), `trading_dates`(수집된 거래일 리스트), return value(krx_data 통합 리스트)를 downstream 태스크에 전달한다.

#### 2. filter_etf_list

KRX 데이터에서 투자 분석 대상 ETF를 선별하여 AGE 유니버스를 관리한다.

- AGE의 기존 ETF 노드 코드 목록(= 유니버스)을 읽는다.
- 새로운 ETF 중 아래 조건을 모두 충족하면 ETF 노드를 MERGE하여 유니버스에 추가한다.
  - 순자산 500억 이상
  - 제외 키워드 미포함: 레버리지, 인버스, 채권, 금, 통화, 리츠 등
  - 해외 시장 키워드 미포함: 미국, 중국, 글로벌, S&P, NASDAQ 등
- 한번 등록된 ETF는 이후 조건에 미달하더라도 유니버스에서 제거하지 않는다.
- 유니버스 티커 리스트를 XCom으로 downstream에 전달한다.

**저장:** AGE — `ETF` 노드 (MERGE)

#### 3. collect_etf_metadata

유니버스 ETF의 메타데이터(이름, 보수율, 운용사)를 수집하여 그래프에 저장한다.

- `pykrx.stock.get_etf_ticker_name`으로 ETF 정식 이름을 조회한다.
- `pykrx.ETF_전종목기본종목`에서 전종목 보수율(ETF_TOT_FEE)을 일괄 조회하고, 소수점 2째자리 올림 처리한다.
- ETF 노드의 `name`, `expense_ratio`, `updated_at` 속성을 갱신한다.
- ETF 이름의 prefix(KODEX, TIGER, RISE 등)로 운용사를 추출하여 Company 노드를 생성하고, `(ETF)-[:MANAGED_BY]->(Company)` 관계를 연결한다.
- ETF당 0.1초 딜레이를 두어 API 부하를 방지한다.

**저장:** AGE — `ETF`, `Company` 노드, `MANAGED_BY` 관계

#### 4. collect_holdings

유니버스 ETF별 구성종목(보유종목) 상위 20개를 수집하여 그래프에 저장한다.

- **Pass 1 (데이터 수집):**
  - `pykrx.stock.get_etf_portfolio_deposit_file`로 각 ETF의 보유종목과 비중을 조회한다.
  - 비중 기준 상위 20개만 선별한다.
  - 모든 고유 종목 코드에 대해 `get_market_ticker_name`으로 종목명을 조회한다.
  - KOSPI/KOSDAQ 업종 인덱스를 순회하여 종목별 (시장, 섹터) 매핑을 구성한다.
  - ETF당 0.5초 딜레이를 두어 API 부하를 방지한다.

- **노드 사전 생성:**
  - Stock 노드를 일괄 MERGE하고 `name`, `is_etf` 속성을 설정한다.
  - Market, Sector 노드를 일괄 MERGE하고 `(Sector)-[:PART_OF]->(Market)` 관계를 생성한다.
  - `(Stock)-[:BELONGS_TO]->(Sector)` 관계를 일괄 생성한다.

- **Pass 2 (엣지 배치 생성):**
  - `(ETF)-[:HOLDS {date, weight, shares}]->(Stock)` 엣지를 MERGE한다.
  - 50개 ETF 단위로 배치 커밋하여 트랜잭션 크기를 제한한다.

**저장:** AGE — `Stock`, `Market`, `Sector` 노드, `HOLDS`, `BELONGS_TO`, `PART_OF` 관계

#### 5. collect_prices

XCom의 KRX 데이터를 사용하여 **모든 ETF**(유니버스 필터 무관)의 일별 시세를 AGE Price 노드로 저장한다.

- 각 krx_data item의 `date` 필드를 그대로 사용하여 멀티 날짜를 자연스럽게 지원한다.
- 유니버스에 포함되지 않은 ETF도 ETF 노드를 MERGE하여 자동 생성한다.
- AGE 버그를 우회하기 위해 MERGE와 SET을 분리하여 실행한다.
  - 1단계: `(ETF)-[:HAS_PRICE]->(Price {date})` MERGE
  - 2단계: Price 노드에 `open, high, low, close, volume, nav, market_cap, net_assets, trade_value` SET
- 200건 단위로 배치 커밋한다.

**저장:** AGE — `Price` 노드, `(ETF)-[:HAS_PRICE]->(Price)` 관계

#### 6. collect_stock_prices

그래프에 등록된 개별 주식(is_etf=false인 Stock)의 일별 시세를 pykrx에서 수집하여 AGE에 저장한다.

- AGE에서 `is_etf = false`인 Stock 코드 목록을 조회한다.
- XCom의 `trading_dates` 리스트를 사용하여 각 거래일별로 처리한다.
- `pykrx.stock.get_market_ohlcv_by_ticker`로 전 종목 OHLCV를 일괄 조회한 뒤, 그래프에 등록된 종목만 필터링하여 저장한다.
- AGE 버그 우회로 MERGE + SET 분리 실행:
  - 1단계: `(Stock)-[:HAS_PRICE]->(Price {date})` MERGE
  - 2단계: Price 노드에 `open, high, low, close, volume, change_rate` SET
- 날짜별로 커밋한다.

**저장:** AGE — `Price` 노드, `(Stock)-[:HAS_PRICE]->(Price)` 관계

#### 7. detect_portfolio_changes

유니버스 ETF의 전일 대비 구성종목 변동을 감지하여 그래프에 기록한다.

- 각 ETF에 대해 오늘/어제의 HOLDS 관계를 AGE에서 조회하여 비교한다.
- 감지 기준:
  - **신규 편입 (added):** 오늘 보유하지만 어제는 없던 종목
  - **완전 편출 (removed):** 어제 보유했지만 오늘은 없는 종목
  - **비중 변동 (increased/decreased):** 비중 차이가 5%p 이상인 종목
- 변동이 감지되면 `Change` 노드를 CREATE하고 `(ETF)-[:HAS_CHANGE]->(Change)` 관계를 생성한다.
- Change 노드 속성: `id`(UUID), `stock_code`, `stock_name`, `change_type`, `before_weight`, `after_weight`, `weight_change`, `detected_at`.
- ETF별로 커밋하며, 실패 시 해당 ETF만 rollback하고 다음으로 진행한다.

**저장:** AGE — `Change` 노드, `(ETF)-[:HAS_CHANGE]->(Change)` 관계

#### 8. tag_new_etfs

TAGGED 관계가 없는 미분류 ETF에 GPT-4.1-mini를 사용하여 태그를 자동 부여한다.

- AGE에서 전체 ETF 목록을 조회하고, 이미 `(ETF)-[:TAGGED]->(Tag)` 관계가 있는 ETF를 제외한다.
- 미분류 ETF별로 보유종목(HOLDS) TOP 10의 종목명을 조회한다.
- ETF 이름 + 보유종목 정보를 10개씩 묶어 LLM에 배치 호출한다.
- LLM은 `ETFTagBatchResult` (Pydantic structured output)로 ETF당 1~3개 태그를 반환한다.
  - 태그 카테고리: 산업(반도체, 2차전지 등), 테마(AI, 로봇 등), 스타일(배당, 대형주 등), 지수(시장지수)
- Tag 노드를 MERGE하고 `(ETF)-[:TAGGED]->(Tag)` 관계를 MERGE한다.
- 배치별로 커밋하며, 실패 시 해당 배치만 rollback하고 다음으로 진행한다.

**저장:** AGE — `Tag` 노드, `(ETF)-[:TAGGED]->(Tag)` 관계

---

## 2. etf_rdb_etl (RDB)

KRX API에서 ETF 메타데이터를 수집하여 RDB `etfs` 테이블에 동기화한다.

- **DAG ID**: `etf_rdb_etl`
- **스케줄**: `0 7 * * 1-5` (평일 07:00 KST)
- **재시도**: 3회, 5분 간격
- **Catchup**: 비활성화
- `etf_daily_etl`과 독립적으로 동작 (자체 KRX 수집, AGE 의존 없음)

### 태스크 구조

```
start → fetch_krx_data → sync_etfs_to_rdb → end
```

### 태스크 상세

#### 1. fetch_krx_data

KRX Open API에서 ETF 일별매매정보를 수집한다. AGE 백필 로직 없이 최근 거래일 데이터만 조회한다.

- `KRXApiClient.get_etf_daily_trading`을 호출하여 전종목 데이터를 가져온다.
- 실행일(ds_nodash)부터 최대 7일 전까지 순회하며 데이터가 있는 최근 거래일을 탐색한다.
- RDB sync에 필요한 최소 필드(code, name, net_assets)만 추출하여 XCom으로 전달한다.
- `KRX_AUTH_KEY` 환경변수가 없으면 빈 리스트를 반환한다.

#### 2. sync_etfs_to_rdb

XCom으로 전달받은 KRX 데이터를 사용하여 **모든 ETF** 메타데이터를 RDB `etfs` 테이블에 동기화한다.

- ETF 이름의 prefix(KODEX, TIGER, RISE 등)에서 운용사를 추출하여 `issuer` 컬럼에 저장한다.
- `INSERT ... ON CONFLICT (code) DO UPDATE`로 UPSERT하여 기존 데이터를 갱신한다.
- 갱신 대상 컬럼: `name`, `issuer`, `net_assets`, `updated_at`.
- 개별 ETF 실패 시 해당 건만 skip하고 나머지는 계속 처리한다.

**저장:** RDB `etfs` — 프론트엔드 ETF 검색(pg_trgm 퍼지 매칭)과 포트폴리오 ETF 이름 조회에 사용

---

## 3. portfolio_snapshot (RDB)

사용자 포트폴리오의 보유종목 현재가를 yfinance에서 조회하여 일별 평가금액 스냅샷을 저장한다.

- **DAG ID**: `portfolio_snapshot`
- **스케줄**: `0 16 * * 1-5` (평일 16:00 KST, 장 마감 후)
- **재시도**: 3회, 5분 간격
- **Catchup**: 비활성화
- `etf_daily_etl`과 독립적으로 동작 (유니버스 밖 종목도 처리)

### 태스크 구조

```
snapshot_portfolios
```

### 태스크 상세

#### 1. snapshot_portfolios

RDB의 포트폴리오 보유종목 정보를 기반으로 일별 평가금액을 계산하여 스냅샷을 저장한다.

- RDB `holdings` 테이블에서 보유종목이 있는 포트폴리오 ID를 조회한다.
- 전체 고유 티커(CASH 제외)를 수집하고, yfinance로 최근 5거래일 종가를 일괄 조회한다 (`{ticker}.KS`).
- 각 포트폴리오별로 평가금액을 계산한다:
  - CASH 티커: price=1.0으로 고정, quantity가 곧 금액
  - ETF/주식: 해당 날짜 이하에서 가장 최근 종가 × 보유수량
- 스냅샷 이력이 없는 포트폴리오는 최근 3거래일을 백필(소급 생성)하고, 이력이 있으면 최신 거래일만 처리한다.
- 전일 스냅샷과 비교하여 변동액(`change_amount`)과 변동률(`change_rate`)을 계산한다.
- `INSERT ... ON CONFLICT (portfolio_id, date) DO UPDATE`로 UPSERT한다.

**저장:** RDB `portfolio_snapshots` — 포트폴리오 대시보드 차트 및 수익률 표시에 사용

---

## 저장 대상별 요약

### RDB

| 테이블 | DAG | 적재 태스크 | 키 | 용도 |
|--------|-----|-------------|-----|------|
| `etfs` | etf_rdb_etl | sync_etfs_to_rdb | code | pg_trgm 퍼지 검색, 포트폴리오 ETF 이름 조회 |
| `portfolio_snapshots` | portfolio_snapshot | snapshot_portfolios | portfolio_id, date | 포트폴리오 일별 평가금액 이력 |

### Apache AGE

| 노드/관계 | DAG | 적재 태스크 | 용도 |
|-----------|-----|-------------|------|
| `ETF` | etf_daily_etl | filter_etf_list, collect_etf_metadata, collect_prices | 유니버스 관리, 메타데이터 |
| `Company`, `MANAGED_BY` | etf_daily_etl | collect_etf_metadata | 운용사 |
| `Stock`, `Market`, `Sector`, `HOLDS`, `BELONGS_TO`, `PART_OF` | etf_daily_etl | collect_holdings | 보유종목, 섹터 분류 |
| `Price`, `(ETF)-[:HAS_PRICE]->` | etf_daily_etl | collect_prices | ETF 가격 시계열 |
| `Price`, `(Stock)-[:HAS_PRICE]->` | etf_daily_etl | collect_stock_prices | 주식 가격 시계열 |
| `Change`, `HAS_CHANGE` | etf_daily_etl | detect_portfolio_changes | 보유종목 변동 이력 |
| `Tag`, `TAGGED` | etf_daily_etl | tag_new_etfs | ETF 테마 분류 |

## 환경 변수

| 변수 | 용도 |
|------|------|
| `DATABASE_URL` | PostgreSQL 연결 문자열 |
| `KRX_AUTH_KEY` | KRX Open API 인증 키 |
| `OPENAI_API_KEY` | GPT-4.1-mini (태그 분류용) |

## 의존성 (requirements.txt)

```
pykrx==1.2.3
psycopg2-binary>=2.9.9
pandas>=2.0.0
setuptools
yfinance
langchain-openai
```
