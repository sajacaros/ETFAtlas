# ETF 과거 가격 데이터 백필 설계

## 목적
RDB `etfs` 테이블에 등록된 전체 ETF의 2025년 1월 1일부터 현재까지의 일별 종가를 `ticker_prices` 테이블에 수집한다. 리스크 분석 정확도 향상, 대시보드 차트 기간 확장, 백테스팅/성과 분석 등 다목적으로 활용한다.

## 결정사항
- **수집 대상**: RDB `etfs` 테이블 전체 ETF
- **데이터 소스**: yfinance (기존 realtime DAG과 동일)
- **저장 위치**: RDB `ticker_prices` 테이블 (ticker + date 복합키)
- **실행 방식**: 단발성 Python 스크립트 (`scripts/backfill_ticker_prices.py`)

## 설계

### 스크립트 흐름
1. RDB `etfs` 테이블에서 전체 ETF code 목록 조회
2. 코드에 `.KS` suffix → yfinance 티커 생성
3. 20개씩 배치로 `yfinance.download()` 호출 (start=2025-01-01, end=today)
4. 각 티커별 일별 종가를 `ticker_prices`에 upsert
5. 배치 간 2초 sleep (rate limit 방지)
6. 실패 티커는 마지막에 개별 재시도 1회
7. 결과 요약 출력

### 핵심 구현 사항
- `yfinance.download(tickers, start, end)` 멀티 티커 배치 다운로드 활용
- `ON CONFLICT (ticker, date) DO UPDATE SET price = EXCLUDED.price` upsert
- psycopg2로 직접 DB 연결 (기존 DAG 패턴과 동일)
- 진행률 로깅: `[batch 1/10] 수집 완료: 18/20 종목`

### 환경
- `scripts/` 디렉토리의 기존 uv 프로젝트에 yfinance 의존성 추가
- DB 연결: 환경변수 `DATABASE_URL` 또는 기본값 `postgresql://postgres:postgres@localhost:5432/etf_atlas`
