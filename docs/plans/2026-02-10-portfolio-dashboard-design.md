# 포트폴리오 대시보드 설계

## 개요

포트폴리오별/통합 전일대비 증감률·증감액을 저장하고, 대시보드에서 평가금액 추이와 누적 수익률을 차트로 확인하는 기능.

## 데이터 모델

### 새 테이블: `portfolio_snapshots`

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | Integer PK | auto increment |
| portfolio_id | FK → portfolios | 포트폴리오 ID |
| date | Date | 스냅샷 날짜 |
| total_value | Decimal | 평가금액 Σ(수량×종가) + 현금 |
| prev_value | Decimal, nullable | 전일 평가금액 |
| change_amount | Decimal, nullable | 전일대비 증감액 |
| change_rate | Float, nullable | 전일대비 증감률 (%) |
| created_at | DateTime | 생성일시 |

- UNIQUE 제약: `(portfolio_id, date)`
- 통합 포트폴리오는 별도 테이블 없이 같은 날짜의 모든 스냅샷 합산

## Airflow DAG

기존 `etf_daily_etl` DAG에 `snapshot_portfolios` 태스크 추가:
- `collect_prices` 완료 후 실행
- 모든 포트폴리오 순회
- `holdings` 수량 × `etf_prices` 종가 + CASH 수량으로 total_value 계산
- 전일 스냅샷 조회하여 change_amount, change_rate 계산
- INSERT ON CONFLICT UPDATE

## Backend API

### GET /api/portfolios/{id}/dashboard

개별 포트폴리오 대시보드 데이터.

Response:
```json
{
  "summary": {
    "current_value": 11200000,
    "cumulative": {"amount": 1200000, "rate": 12.0, "base_value": 10000000},
    "daily": {"amount": 150000, "rate": 1.5},
    "monthly": {"amount": 520000, "rate": 5.2},
    "yearly": {"amount": 1200000, "rate": 12.0},
    "ytd": {"amount": 800000, "rate": 7.7}
  },
  "chart_data": [
    {"date": "2025-01-02", "total_value": 10000000, "cumulative_rate": 0.0},
    {"date": "2025-01-03", "total_value": 10150000, "cumulative_rate": 1.5}
  ]
}
```

### GET /api/portfolios/dashboard/total

통합 포트폴리오 대시보드 데이터. 같은 날짜의 모든 포트폴리오 합산. Response 형태 동일.

### 상단 요약 계산

| 항목 | 계산 |
|------|------|
| 현재 평가금액 | 최근 스냅샷의 total_value |
| 누적 수익률/금액 | 최초 스냅샷 대비 |
| 전일대비 | 최근 vs 직전 스냅샷 |
| 전달대비 | 최근 vs 전달 마지막 거래일 |
| 전년대비 | 최근 vs 전년 마지막 거래일 |
| 올해 수익률 | 최근 vs 전년 마지막 거래일 (= YTD) |

## Frontend

### 진입점
- 포트폴리오 카드에 "대시보드" 버튼 추가
- "포트폴리오" 제목 옆에 "통합 대시보드" 링크 추가

### 대시보드 레이아웃
1. 상단 요약 카드 4개: 전일대비, 전달대비, 전년대비, 올해수익률
   - 각 카드에 증감액 + 증감률 표시
   - 양수: 빨간색, 음수: 파란색 (한국 주식 관행)
2. 누적 정보: 최초 평가액 → 현재 평가액 (증감액/수익률)
3. 평가금액 라인 차트: 전체 기간 일별 평가금액 추이
4. 누적 수익률 라인 차트: 최초 대비 수익률(%) 추이

### 차트 라이브러리
- Recharts
