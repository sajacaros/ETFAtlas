# KRX API Integration Design

## Overview

pykrx 라이브러리의 가격 데이터 수집을 KRX Open API로 대체하여 더 풍부한 데이터(NAV, 시가총액 등)를 수집한다.

## Scope

### 변경 범위
- **대체**: pykrx `get_etf_ohlcv_by_date()` → KRX API `/etp/etf_bydd_trd`
- **통합**: AUM 필터링과 가격 수집을 단일 API 호출로 통합
- **확장**: DB 스키마에 NAV, 시가총액, 순자산총액, 거래대금 추가
- **유지**: pykrx의 보유종목(PDF) 수집 기능

### 유지 범위
- pykrx: ETF 목록 조회, 보유종목(PDF) 조회
- Apache AGE: 그래프 데이터 저장 (ETF, Stock, HOLDS 관계)

## KRX API Specification

**Endpoint**: `https://data-dbg.krx.co.kr/svc/apis/etp/etf_bydd_trd`

**Request**:
| Name | Type | Description |
|------|------|-------------|
| basDd | string | 기준일자 (YYYYMMDD) |

**Response** (OutBlock_1):
| Name | Type | Description |
|------|------|-------------|
| BAS_DD | string | 기준일자 |
| ISU_CD | string | 종목코드 |
| ISU_NM | string | 종목명 |
| TDD_CLSPRC | string | 종가 |
| CMPPREVDD_PRC | string | 대비 |
| FLUC_RT | string | 등락률 |
| NAV | string | 순자산가치(NAV) |
| TDD_OPNPRC | string | 시가 |
| TDD_HGPRC | string | 고가 |
| TDD_LWPRC | string | 저가 |
| ACC_TRDVOL | string | 거래량 |
| ACC_TRDVAL | string | 거래대금 |
| MKTCAP | string | 시가총액 |
| INVSTASST_NETASST_TOTAMT | string | 순자산총액 |
| LIST_SHRS | string | 상장좌수 |
| IDX_IND_NM | string | 기초지수명 |
| OBJ_STKPRC_IDX | string | 기초지수 종가 |
| CMPPREVDD_IDX | string | 기초지수 대비 |
| FLUC_RT_IDX | string | 기초지수 등락률 |

## Database Schema Changes

### etf_prices 테이블 확장

```sql
ALTER TABLE etf_prices ADD COLUMN nav NUMERIC(14,2);
ALTER TABLE etf_prices ADD COLUMN market_cap BIGINT;
ALTER TABLE etf_prices ADD COLUMN net_assets BIGINT;
ALTER TABLE etf_prices ADD COLUMN trade_value BIGINT;
```

### ETFPrice 모델 (backend/app/models/etf.py)

```python
class ETFPrice(Base):
    # 기존 필드
    id: int
    etf_id: FK
    date: Date
    open_price: Numeric(12,2)
    high_price: Numeric(12,2)
    low_price: Numeric(12,2)
    close_price: Numeric(12,2)
    volume: BigInteger
    created_at: DateTime

    # 추가 필드
    nav: Numeric(14,2)           # 순자산가치
    market_cap: BigInteger        # 시가총액
    net_assets: BigInteger        # 순자산총액
    trade_value: BigInteger       # 거래대금
```

## Architecture

### Data Flow

```
변경 전:
  ETF목록(pykrx) → 필터링(KRX API) → 가격(pykrx) + 보유종목(pykrx)
                          ↓
변경 후:
  ETF목록(pykrx) → 가격+필터링(KRX API) + 보유종목(pykrx)
```

### API Call Optimization

- 변경 전: KRX API 1회 (필터링) + pykrx N회 (가격)
- 변경 후: KRX API 1회 (필터링 + 가격)

## Implementation Plan

### 1. DB Migration
- `etf_prices` 테이블에 새 컬럼 추가 (nullable)
- Alembic 마이그레이션 파일 생성

### 2. KRX API Client
- `airflow/dags/krx_api_client.py` 생성
- 인증, 요청, 에러 핸들링 구현

### 3. ETL Refactoring
- `collect_prices` → `collect_etf_daily_data`로 리팩토링
- pykrx OHLCV 호출 제거
- 필터링 로직 통합 (AUM + 키워드)

### 4. Model Update
- `backend/app/models/etf.py`의 ETFPrice 모델 확장

## Files to Modify

| File | Change |
|------|--------|
| `airflow/dags/etf_daily_etl.py` | ETL 로직 수정 |
| `airflow/dags/krx_api_client.py` | 새 파일 생성 |
| `backend/app/models/etf.py` | ETFPrice 모델 확장 |
| `backend/alembic/versions/xxx_add_krx_fields.py` | 마이그레이션 |

## Authentication

- 환경변수: `KRX_AUTH_KEY` (기존 키 사용)
- 헤더: `AUTH_KEY: {key}`
