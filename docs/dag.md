# Airflow DAG: etf_daily_etl

## 개요

한국 ETF 시장 데이터를 매일 수집하는 ETL 파이프라인.

- **DAG ID**: `etf_daily_etl`
- **스케줄**: `0 8 * * 1-5` (평일 08:00 KST)
- **재시도**: 3회, 5분 간격
- **Catchup**: 비활성화

## 데이터 소스

| 소스 | 용도 | 인증 |
|------|------|------|
| KRX Open API (`etf_bydd_trd`) | ETF 일별 시세, 시가총액, 순자산 | `KRX_AUTH_KEY` 환경변수 |
| pykrx 라이브러리 | ETF 목록, 보유종목(PDF), 섹터 분류, 주식 시세 | 불필요 |

## 태스크 구조

```
start
  ├── collect_etf_list ──┐
  └── fetch_krx_data ────┤
                         ↓
                   filter_etf_list
                    ├── collect_etf_metadata
                    └── collect_holdings
                         ├── collect_stock_prices
                         └── detect_portfolio_changes

  fetch_krx_data ──┬── collect_prices
                   └── sync_etfs_to_rdb

  All paths → end
```

## 태스크 상세

### 1. collect_etf_list

pykrx에서 전체 ETF 티커 목록을 조회한다. 참조용으로만 사용.

### 2. fetch_krx_data

KRX Open API에서 ETF 일별 거래 정보를 수집한다. 누락된 영업일을 자동으로 백필한다.

**백필 로직:**

| 상태 | 동작 |
|------|------|
| DB 비어있음 (초기 적재) | 실행일 기준 45일 전부터 수집 (~30 영업일) |
| 누락일 있음 | DB 마지막 수집일 다음날 ~ 오늘까지 평일 순회 |
| 누락 없음 | 오늘 데이터만 수집 시도 |
| 수집 결과 없음 (장 마감 전/공휴일) | 최근 7일 내 거래일 탐색 fallback |

- 평일(월~금) 후보만 조회, 공휴일은 KRX 응답이 없으면 자동 skip
- `_get_krx_data_for_exact_date`: 정확히 해당 날짜만 조회 (거래일 탐색 없음, 백필용)
- `get_krx_daily_data`: 최대 7일 과거 탐색 (fallback용)

**XCom 출력:**
- `trading_date`: 최신 거래일 1개 (기존 downstream 호환)
- `trading_dates`: 수집된 모든 거래일 리스트 (멀티 날짜 downstream용)
- return value: 모든 날짜의 krx_data 통합 리스트

**수집 항목:** OHLCV, 거래대금, NAV, 시가총액, 순자산총액

### 3. filter_etf_list

ETF 유니버스 필터링. `fetch_krx_data` 결과와 DB의 `etf_universe` 테이블을 기반으로 투자 대상 ETF를 선별한다.

**필터 조건:**
- 순자산 500억 이상
- 제외 키워드: 레버리지, 인버스, 채권, 금, 통화, 리츠 등
- 해외 시장 키워드: 미국, 중국, 글로벌, S&P, NASDAQ 등

**적재 테이블:** `etf_universe` (INSERT ON CONFLICT DO NOTHING)

### 4. collect_etf_metadata

필터링된 ETF의 메타데이터를 Apache AGE 그래프에 저장한다.

- ETF 노드 생성/갱신
- 운용사(Company) 노드 생성 및 `MANAGED_BY` 관계 설정
- 운용사 매핑: KODEX→삼성자산운용, TIGER→미래에셋자산운용 등 15개+

**그래프 구조:**
```
(ETF {code, name, updated_at}) -[:MANAGED_BY]-> (Company {name})
```

### 5. collect_holdings

ETF별 보유종목 상위 20개를 수집하여 그래프에 저장한다.

- pykrx의 `get_etf_portfolio_deposit_file`로 보유 비중 조회
- KOSPI/KOSDAQ 섹터 분류 매핑
- 처리 간격: ETF당 0.5초 딜레이

**그래프 구조:**
```
(ETF) -[:HOLDS {date, weight, shares}]-> (Stock {code, name, is_etf})
(Stock) -[:BELONGS_TO]-> (Sector {name})
(Sector) -[:PART_OF]-> (Market {name})
```

### 6. collect_prices

KRX 데이터에서 **전체 ETF**(필터 무관)의 시세를 RDB에 저장한다. 각 item의 `date` 필드를 사용하여 멀티 날짜 INSERT를 지원한다.

**적재 테이블:** `etf_prices` (UPSERT on `etf_code, date`)
- OHLCV, NAV, 시가총액, 순자산총액, 거래대금

### 7. collect_stock_prices

그래프에 저장된 종목(`is_etf=false`) 중 개별 주식의 시세를 수집한다. XCom의 `trading_dates` 리스트를 사용하여 멀티 날짜 수집을 지원한다.

**적재 테이블:** `stock_prices` (UPSERT on `stock_code, date`)
- OHLCV, 등락률

### 8. detect_portfolio_changes

전일 대비 보유종목 변동을 감지하여 그래프에 기록한다.

**감지 기준:**
- 신규 편입 (added)
- 편출 (removed)
- 비중 변동 5%p 이상 (weight_change)

**그래프 구조:**
```
(ETF) -[:HAS_CHANGE]-> (Change {stock_code, stock_name, change_type, before_weight, after_weight, weight_change, detected_at})
```

### 9. sync_etfs_to_rdb

KRX 데이터의 **전체 ETF** 메타데이터를 RDB `etfs` 테이블에 동기화한다. ETF 이름에서 운용사를 추출하여 `issuer` 컬럼에 저장.

**적재 테이블:** `etfs` (UPSERT on `code`)
- pg_trgm 검색을 위한 기반 데이터

## 적재 테이블 요약

| 테이블 | 저장소 | 적재 태스크 | 키 |
|--------|--------|-------------|-----|
| `etf_universe` | RDB | filter_etf_list | code |
| `etf_prices` | RDB | collect_prices | etf_code, date |
| `stock_prices` | RDB | collect_stock_prices | stock_code, date |
| `etfs` | RDB | sync_etfs_to_rdb | code |
| ETF, Stock, Company, Sector, Market 노드 | AGE | collect_etf_metadata, collect_holdings | code/name |
| Change 노드 | AGE | detect_portfolio_changes | id |

## 환경 변수

| 변수 | 용도 |
|------|------|
| `DATABASE_URL` | PostgreSQL 연결 문자열 |
| `KRX_AUTH_KEY` | KRX Open API 인증 키 |

## 의존성 (requirements.txt)

```
pykrx==1.2.3
psycopg2-binary>=2.9.9
pandas>=2.0.0
setuptools
```
