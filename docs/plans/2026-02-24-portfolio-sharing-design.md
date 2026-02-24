# Portfolio Sharing Feature Design

## Overview

사용자가 포트폴리오를 공유하면, 종목과 비중만 공개하고 보유수량/금액은 숨긴다.
1000만원 기준 가상 수익률 차트도 함께 제공한다.

## Requirements

### 공유 활성화
- 포트폴리오 상세(편집) 페이지에 공유 토글 스위치 추가
- 토글 ON 시 UUID 기반 `share_token` 생성, 공유 링크 표시
- 토글 OFF 시 공유 비활성화 (share_token 유지, is_shared=FALSE)

### 공유 포트폴리오 접근
- **공개 링크**: `/shared/{share_token}` — 비로그인 접근 가능
- **Shared 메뉴**: 네비게이션에 "Shared" 메뉴 추가 (로그인 불필요)
- 공유를 켜면 모든 사용자의 Shared 목록에 표시됨 (공개 갤러리 방식)

### 표시 정보
- **보여줌**: 포트폴리오명, 사용자명, 종목 목록, 비중(현재 기준)
- **숨김**: 보유수량, 보유금액, 평균단가, 실제 포트폴리오 가치

### 가상 수익률 차트
- 현재 비중으로 1000만원을 배분했다고 가정
- ETF 종가 기준으로 일별 가상 포트폴리오 가치 계산
- 기간 선택: 1주 / 1개월 / 3개월
- 데이터 부족 시: 모든 종목의 가격 데이터가 존재하는 가장 이른 날짜부터 계산

### 변경 반영
- 포트폴리오 종목/비중 변경 시 공유 페이지에 실시간 반영
- 수익률도 항상 현재 비중 기준으로 재계산

## Database Changes

### portfolios 테이블 수정

```sql
ALTER TABLE portfolios
  ADD COLUMN is_shared BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN share_token UUID UNIQUE DEFAULT NULL;
```

- `is_shared`: 공유 활성화 여부
- `share_token`: 공유 링크용 UUID (공유 최초 활성화 시 생성, 이후 유지)

## API Design

### Backend Endpoints

```
PUT  /api/portfolios/{id}/share          → 공유 토글 (인증 필요, 본인 포트폴리오)
  Request:  { "is_shared": true }
  Response: { "is_shared": true, "share_token": "uuid-string", "share_url": "/shared/uuid-string" }

GET  /api/shared                         → 공유 포트폴리오 목록 (비인증)
  Response: [{ portfolio_name, user_name, share_token, tickers_count, updated_at }]

GET  /api/shared/{share_token}           → 공유 포트폴리오 상세 (비인증)
  Response: { portfolio_name, user_name, allocations: [{ ticker, name, weight }] }

GET  /api/shared/{share_token}/returns   → 가상 수익률 차트 (비인증)
  Query:    ?period=1w|1m|3m
  Response: { base_amount: 10000000, period, actual_start_date, chart_data: [{ date, value }] }
```

### 수익률 계산 로직

1. target_allocations에서 현재 비중 조회
2. 1000만원을 비중대로 배분 (예: ETF_A 40% → 400만원)
3. 기간 시작일의 종가로 가상 매수수량 계산 (400만원 / 시작일종가)
4. 각 날짜의 종가 × 가상수량 = 일별 종목 평가액
5. 전체 종목 합산 = 일별 가상 포트폴리오 가치
6. 데이터 부족 시: 모든 종목에 가격 데이터가 있는 가장 이른 날짜를 actual_start_date로 반환

## Frontend Design

### 네비게이션
- "Shared" 메뉴 아이템 추가 (항상 표시)
- 클릭 시 `/shared` 페이지로 이동

### 공유 포트폴리오 목록 페이지 (`/shared`)
- 공유된 포트폴리오 카드 목록
- 카드: 포트폴리오명, 사용자명, 종목 수, 마지막 업데이트
- 클릭 시 `/shared/{share_token}`으로 이동

### 공유 포트폴리오 상세 페이지 (`/shared/{share_token}`)
- 포트폴리오명, 사용자명 표시
- 종목 + 비중 테이블 (파이차트 또는 테이블)
- 1000만원 기준 가상 수익률 차트
- 기간 선택 버튼: 1주 | 1개월 | 3개월

### 포트폴리오 상세 페이지 (기존)
- 공유 토글 스위치 추가
- 공유 활성화 시 공유 링크 표시 + 복사 버튼

## Architecture Notes

- 공유 API는 별도 라우터(`/api/shared`)로 분리 — 인증 불필요
- 공유 토글은 기존 portfolios 라우터에 추가 — 인증 필요
- 수익률 계산은 PriceService의 기존 AGE 가격 조회 활용 (60초 캐시)
- 매 요청 시 실시간 계산 (캐싱은 향후 필요 시 추가)
