# 실시간 현재가 수집 및 포트폴리오 평가 설계

## 배경

현재 장중 가격 조회 시 PriceService가 AGE → yfinance 폴백 체인을 타면서 1~3초 지연이 발생한다.
또한 portfolio_snapshots는 하루 1회(16시)만 갱신되어 장중 실시간 평가액 반영이 안 된다.

## 목표

- 장중 10분마다 포트폴리오 보유 종목의 현재가를 RDB에 업서트
- PriceService 폴백 체인을 단순화하여 응답 속도 개선
- 포트폴리오 스냅샷을 10분마다 갱신하여 대시보드 실시간 반영
- 기존 portfolio_snapshot DAG를 새 DAG에 통합

## 설계

### 1. 새 RDB 테이블: `ticker_prices`

```sql
CREATE TABLE ticker_prices (
    ticker     VARCHAR(20)   NOT NULL,
    date       DATE          NOT NULL,
    price      NUMERIC(18,2) NOT NULL,
    updated_at TIMESTAMP     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, date)
);
```

- 티커+날짜 조합으로 하루 1건 유지 (UPSERT)
- 장중 10분마다 갱신, 마지막 갱신이 당일 종가로 확정

### 2. PriceService 변경

**기존**: `캐시(60s) → AGE당일종가 → yfinance → AGE최신종가(폴백)`
**변경**: `캐시(60s) → RDB ticker_prices → yfinance`

- AGE 가격 조회 로직 제거
- RDB 조회는 단순 SQL SELECT (batch IN 쿼리, N+1 문제 없음)
- yfinance는 RDB에도 없을 때만 폴백

### 3. 새 Airflow DAG: `collect_realtime_prices`

- **스케줄**: `*/10 9-15 * * 1-5` (평일 09:00~15:50, 10분 간격)
- **거래일 판단**: pykrx로 당일이 거래일인지 확인, 아니면 스킵
- **시간 체크**: KST 15:30 이후면 스킵

#### Task 1: 현재가 수집

1. 전체 포트폴리오에서 고유 보유 티커 목록 조회
2. yfinance로 현재가 배치 조회
3. `ticker_prices` 테이블에 UPSERT

#### Task 2: 스냅샷 갱신

1. `ticker_prices`에서 가격 조회
2. 포트폴리오별 평가액 계산 (SUM(quantity * price))
3. `portfolio_snapshots`에 UPSERT (total_value, change_amount, change_rate)

### 4. 기존 DAG 변경

- `portfolio_snapshot.py` 제거 (역할이 새 DAG로 통합)
- `etf_daily_etl.py` 변경 없음 (AGE 종가 수집은 그대로 유지)

### 5. 최종 DAG 구성 (3개)

| DAG | 스케줄 | 역할 |
|-----|--------|------|
| `etf_daily_etl` | 08:00 평일 | KRX 데이터 수집 → AGE (메타/보유/종가) |
| `etf_daily_etl_age` | 기존 | AGE 관련 ETL |
| `collect_realtime_prices` (신규) | */10 장중 평일 | RDB 현재가 업서트 + 스냅샷 갱신 |

## 기대 효과

| 항목 | 기존 | 변경 후 |
|------|------|---------|
| 리밸런싱 계산 응답 | 1~3초 (yfinance) | ~50ms (RDB) |
| 보유종목 현황 조회 | 1~3초 | ~50ms |
| 대시보드 평가액 갱신 | 하루 1회 | 10분마다 |
| PriceService 복잡도 | 4단계 폴백 | 2단계 폴백 |
