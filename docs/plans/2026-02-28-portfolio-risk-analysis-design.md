# 포트폴리오 리스크 분석 설계

## 개요

개별 포트폴리오의 **현재 target_allocations 기준**으로 가상 시뮬레이션하여 성과/리스크 지표를 제공한다.
기존 스냅샷 기반 대시보드(실제 계좌 변동 추적)는 그대로 유지하며, 현재 포트폴리오 구성이 과거에도 유지되었다고 가정한 가상 성과를 별도로 보여준다.

## 배경

- 기존 스냅샷 대시보드는 현금 추가 등 계좌 변동이 반영되어 MDD 등 리스크 지표가 정확하지 않음
- shared 포트폴리오처럼 현재 구성(target_allocations)을 고정하여 가상 시뮬레이션하면 순수한 포트폴리오 성과 측정 가능

## 리스크 지표

| 지표 | 설명 | 산출 방법 |
|------|------|-----------|
| 수익률 | 기간 내 총 수익률 | `(최종가치 - 초기가치) / 초기가치 × 100` |
| MDD | 최대낙폭 (Maximum Drawdown) | `min((가치 - 고점) / 고점)` |
| 변동성 | 연환산 표준편차 | `일별 수익률 표준편차 × √252` |
| 샤프비율 | 위험조정 수익률 | `(연환산 수익률 - 3.5%) / 변동성` |

## Backend

### 엔드포인트

`GET /api/portfolios/{portfolio_id}/risk-analysis?period=3m`

- `period`: `1m`, `3m`, `6m`, `1y` (기본 `3m`)
- 인증 필요 (JWT)

### 계산 로직

1. 해당 포트폴리오의 target_allocations 조회
2. CASH 제외, 비중 정규화 (합이 1이 되도록)
3. ticker_prices에서 기간 내 일별 종가 조회
4. 모든 티커에 데이터가 있는 공통 날짜만 필터링
5. 가상 매수: 시작일 기준 10,000,000원을 비중별로 배분 → 가상 수량 계산
6. 일별 가상 포트폴리오 가치 계산
7. 일별 가치 시계열에서 리스크 지표 산출

shared.py의 `_calc_return_rate` 및 returns 계산 패턴을 재사용한다.

### 응답 스키마

```python
class RiskChartPoint(BaseModel):
    date: str
    value: float           # 가상 포트폴리오 가치
    return_rate: float     # 누적 수익률 (%)

class DrawdownPoint(BaseModel):
    date: str
    drawdown: float        # 고점 대비 낙폭 (%)

class RiskAnalysisResponse(BaseModel):
    period: str
    actual_start_date: str
    total_return: float          # 기간 수익률 (%)
    mdd: float                   # 최대낙폭 (%)
    volatility: float            # 연환산 변동성 (%)
    sharpe_ratio: float | None   # 샤프비율
    chart_data: list[RiskChartPoint]
    drawdown_data: list[DrawdownPoint]
```

## Frontend

### 대시보드 요약 카드

PortfolioDashboardPage의 개별 포트폴리오 대시보드에 리스크 요약 카드 추가:

```
┌─────────────────────┐
│ 포트폴리오 리스크    │
│ MDD: -8.32%         │
│ 변동성: 12.5%       │
│ [자세히 보기]       │
└─────────────────────┘
```

- 기존 SummaryCard 그리드 아래에 배치
- 페이지 로드 시 기본 3M 기간으로 자동 조회
- "자세히 보기" 클릭 시 Dialog 팝업 오픈

### 팝업 (Dialog)

```
┌──────────────────────────────┐
│ 포트폴리오 성과 분석     [X] │
│ (현재 구성 기준 가상 시뮬)   │
├──────────────────────────────┤
│ 기간: [1M][3M][6M][1Y]      │
│                              │
│ 수익률    MDD    변동성      │
│ +5.23%  -8.32%  12.5%       │
│                              │
│        샤프비율              │
│         0.82                 │
│                              │
│ [가상 수익률 차트]           │
│ [Drawdown 차트]              │
└──────────────────────────────┘
```

- shadcn/ui Dialog 컴포넌트 사용
- 기간 선택 시 API 재호출
- Recharts LineChart (수익률) + AreaChart (Drawdown)

## 적용 범위

- 개별 포트폴리오 대시보드에만 적용
- 통합 대시보드는 대상 아님
