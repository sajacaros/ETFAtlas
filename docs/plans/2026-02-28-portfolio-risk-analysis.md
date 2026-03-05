# Portfolio Risk Analysis Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add risk metrics (MDD, volatility, Sharpe ratio) to individual portfolio dashboards, calculated from current target allocations via virtual simulation (not snapshots).

**Architecture:** New backend endpoint `GET /api/portfolios/{id}/risk-analysis?period=3m` calculates virtual portfolio value timeseries from target_allocations + ticker_prices, then derives risk metrics. Frontend shows a summary card on the dashboard page with a dialog popup for detailed charts.

**Tech Stack:** FastAPI, SQLAlchemy, ticker_prices table, React, Recharts, shadcn/ui Dialog

---

### Task 1: Backend — Risk analysis schemas

**Files:**
- Modify: `backend/app/schemas/portfolio.py` (append at end)

**Step 1: Add risk analysis response schemas**

Append these schemas to the end of `backend/app/schemas/portfolio.py`:

```python
# --- Risk Analysis ---
class RiskChartPoint(BaseModel):
    date: str
    value: float
    return_rate: float


class DrawdownPoint(BaseModel):
    date: str
    drawdown: float


class RiskAnalysisResponse(BaseModel):
    period: str
    actual_start_date: str
    total_return: float
    mdd: float
    volatility: float
    sharpe_ratio: Optional[float] = None
    chart_data: list[RiskChartPoint]
    drawdown_data: list[DrawdownPoint]
```

**Step 2: Commit**

```bash
git add backend/app/schemas/portfolio.py
git commit -m "feat: add risk analysis response schemas"
```

---

### Task 2: Backend — Risk analysis endpoint

**Files:**
- Modify: `backend/app/routers/portfolio.py`

**Step 1: Add import for risk analysis schema**

Add `RiskAnalysisResponse, RiskChartPoint, DrawdownPoint` to the import from `..schemas.portfolio`.

Also add `import math` at the top and `from fastapi import Query` (Query is already imported via `from fastapi import APIRouter, Depends, HTTPException, status` — add Query to that import).

**Step 2: Add the risk-analysis endpoint**

Add this endpoint in `portfolio.py`. It must be placed BEFORE the `/{portfolio_id}` GET route (line ~179) to avoid route conflicts. Place it after the `/dashboard/total/holdings` endpoint (after line ~501) is NOT safe because `{portfolio_id}` route would match first. Instead, place it right after the `POST /refresh-snapshots` endpoint (around line 403) and before `GET /dashboard/total`.

Actually, looking at the route patterns more carefully:
- `GET /{portfolio_id}/risk-analysis` won't conflict with `GET /{portfolio_id}` because they have different paths.
- FastAPI matches routes in order, and `/{portfolio_id}/risk-analysis` is more specific than `/{portfolio_id}`.

So place it right before `GET /{portfolio_id}/dashboard` (around line 517):

```python
@router.get("/{portfolio_id}/risk-analysis", response_model=RiskAnalysisResponse)
async def get_risk_analysis(
    portfolio_id: int,
    period: str = Query(default="3m", pattern="^(1m|3m|6m|1y)$"),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)

    allocations = (
        db.query(TargetAllocation)
        .filter(TargetAllocation.portfolio_id == portfolio.id)
        .all()
    )
    tickers = [a.ticker for a in allocations if a.ticker != "CASH"]
    weights = {a.ticker: float(a.target_weight) / 100.0 for a in allocations if a.ticker != "CASH"}

    if not tickers:
        raise HTTPException(status_code=400, detail="No ETF tickers in portfolio")

    # Period to days
    period_days = {"1m": 30, "3m": 90, "6m": 180, "1y": 365}
    today = date.today()
    start_date = today - timedelta(days=period_days[period])

    from sqlalchemy import text as sa_text

    result = db.execute(
        sa_text("""
            SELECT ticker, date, price
            FROM ticker_prices
            WHERE ticker = ANY(:tickers)
              AND date >= :start_date
            ORDER BY date
        """),
        {"tickers": tickers, "start_date": start_date},
    )

    price_map: dict[date, dict[str, float]] = {}  # date -> {ticker: price}
    all_dates: set[date] = set()
    for row in result:
        t, d, p = row.ticker, row.date, float(row.price)
        price_map.setdefault(d, {})[t] = p
        all_dates.add(d)

    # Filter to common dates (all tickers have data)
    common_dates = sorted(
        d for d in all_dates
        if all(t in price_map.get(d, {}) for t in tickers)
    )

    if len(common_dates) < 2:
        raise HTTPException(status_code=404, detail="Insufficient price data")

    # Normalize weights
    total_weight = sum(weights.values())
    norm_weights = {t: w / total_weight for t, w in weights.items()} if total_weight > 0 else weights

    # Virtual buy at start date
    base_amount = 10_000_000
    start = common_dates[0]
    virtual_quantities: dict[str, float] = {}
    for t in tickers:
        allocated = base_amount * norm_weights.get(t, 0)
        start_price = price_map[start][t]
        virtual_quantities[t] = allocated / start_price if start_price > 0 else 0

    # Daily portfolio values
    daily_values: list[tuple[date, float]] = []
    for d in common_dates:
        value = sum(virtual_quantities[t] * price_map[d][t] for t in tickers)
        daily_values.append((d, value))

    # Calculate metrics
    # 1. Total return
    total_return = ((daily_values[-1][1] - base_amount) / base_amount) * 100

    # 2. MDD & drawdown series
    peak = daily_values[0][1]
    mdd = 0.0
    drawdown_data = []
    for d, v in daily_values:
        if v > peak:
            peak = v
        dd = ((v - peak) / peak) * 100 if peak > 0 else 0.0
        if dd < mdd:
            mdd = dd
        drawdown_data.append(DrawdownPoint(date=d.isoformat(), drawdown=round(dd, 2)))

    # 3. Daily returns for volatility & Sharpe
    daily_returns: list[float] = []
    for i in range(1, len(daily_values)):
        prev_val = daily_values[i - 1][1]
        curr_val = daily_values[i][1]
        daily_returns.append((curr_val - prev_val) / prev_val if prev_val > 0 else 0.0)

    # Volatility (annualized)
    if len(daily_returns) >= 2:
        import math
        mean_r = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        daily_vol = math.sqrt(variance)
        volatility = daily_vol * math.sqrt(252) * 100  # annualized %
    else:
        volatility = 0.0

    # Sharpe ratio (risk-free rate 3.5%)
    sharpe_ratio = None
    if volatility > 0:
        trading_days = len(daily_returns)
        annualized_return = ((daily_values[-1][1] / base_amount) ** (252 / trading_days) - 1) * 100 if trading_days > 0 else 0.0
        sharpe_ratio = round((annualized_return - 3.5) / volatility, 2)

    # Chart data
    chart_data = []
    for d, v in daily_values:
        ret = ((v - base_amount) / base_amount) * 100
        chart_data.append(RiskChartPoint(
            date=d.isoformat(),
            value=round(v, 0),
            return_rate=round(ret, 2),
        ))

    return RiskAnalysisResponse(
        period=period,
        actual_start_date=common_dates[0].isoformat(),
        total_return=round(total_return, 2),
        mdd=round(mdd, 2),
        volatility=round(volatility, 2),
        sharpe_ratio=sharpe_ratio,
        chart_data=chart_data,
        drawdown_data=drawdown_data,
    )
```

**Step 3: Add missing imports**

Add `from datetime import timedelta` to the existing datetime import line. Also add `from fastapi import Query` to the existing fastapi import (if not already there).

Check the existing imports — the file already has:
- `from datetime import date, datetime` → change to `from datetime import date, datetime, timedelta`
- `from fastapi import APIRouter, Depends, HTTPException, status` → add `Query`: `from fastapi import APIRouter, Depends, HTTPException, status, Query`

Also add `import math` at the top of the file.

**Step 4: Verify the backend builds**

Run: `cd backend && docker compose up -d --build backend` or verify syntax with `python -c "from app.routers.portfolio import router"`

**Step 5: Commit**

```bash
git add backend/app/routers/portfolio.py
git commit -m "feat: add portfolio risk-analysis endpoint"
```

---

### Task 3: Frontend — API client and types

**Files:**
- Modify: `frontend/src/types/api.ts` (append types)
- Modify: `frontend/src/lib/api.ts` (add API method)

**Step 1: Add TypeScript types**

Append to `frontend/src/types/api.ts`:

```typescript
// Risk Analysis types
export interface RiskChartPoint {
  date: string
  value: number
  return_rate: number
}

export interface DrawdownPoint {
  date: string
  drawdown: number
}

export interface RiskAnalysisResponse {
  period: string
  actual_start_date: string
  total_return: number
  mdd: number
  volatility: number
  sharpe_ratio: number | null
  chart_data: RiskChartPoint[]
  drawdown_data: DrawdownPoint[]
}
```

**Step 2: Add API method**

In `frontend/src/lib/api.ts`, add `RiskAnalysisResponse` to the import from `@/types/api`:

```typescript
import type {
  // ... existing imports ...
  RiskAnalysisResponse,
} from '@/types/api'
```

Add this method to the `portfolioApi` object (after `toggleShare`):

```typescript
  getRiskAnalysis: async (portfolioId: number, period: string = '3m') => {
    const { data } = await api.get<RiskAnalysisResponse>(`/portfolios/${portfolioId}/risk-analysis`, { params: { period } })
    return data
  },
```

**Step 3: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/lib/api.ts
git commit -m "feat: add risk analysis API client and types"
```

---

### Task 4: Frontend — Risk analysis dialog component

**Files:**
- Create: `frontend/src/components/RiskAnalysisDialog.tsx`

**Step 1: Create the dialog component**

```tsx
import { useEffect, useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { portfolioApi } from '@/lib/api'
import type { RiskAnalysisResponse } from '@/types/api'
import {
  ResponsiveContainer,
  LineChart,
  AreaChart,
  Area,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts'

const PERIODS = [
  { key: '1m', label: '1M' },
  { key: '3m', label: '3M' },
  { key: '6m', label: '6M' },
  { key: '1y', label: '1Y' },
] as const

function MetricCard({ label, value, suffix = '%', colorBySign = false }: {
  label: string
  value: number | null
  suffix?: string
  colorBySign?: boolean
}) {
  if (value === null) return (
    <div className="rounded-lg border p-3 text-center">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <p className="text-lg font-semibold text-muted-foreground">-</p>
    </div>
  )
  let colorClass = ''
  if (colorBySign) {
    colorClass = value >= 0 ? 'text-red-500' : 'text-blue-500'
  }
  const sign = colorBySign && value >= 0 ? '+' : ''
  return (
    <div className="rounded-lg border p-3 text-center">
      <p className="text-xs text-muted-foreground mb-1">{label}</p>
      <p className={`text-lg font-semibold ${colorClass}`}>
        {sign}{value.toFixed(2)}{suffix}
      </p>
    </div>
  )
}

export default function RiskAnalysisDialog({
  open,
  onOpenChange,
  portfolioId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  portfolioId: number
}) {
  const [data, setData] = useState<RiskAnalysisResponse | null>(null)
  const [period, setPeriod] = useState('3m')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    setError(null)
    portfolioApi.getRiskAnalysis(portfolioId, period)
      .then(setData)
      .catch(() => setError('리스크 데이터를 불러올 수 없습니다'))
      .finally(() => setLoading(false))
  }, [open, portfolioId, period])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>포트폴리오 성과 분석</DialogTitle>
          <p className="text-sm text-muted-foreground">현재 구성 기준 가상 시뮬레이션</p>
        </DialogHeader>

        {/* Period selector */}
        <div className="flex gap-1">
          {PERIODS.map((p) => (
            <Button
              key={p.key}
              variant={period === p.key ? 'default' : 'outline'}
              size="sm"
              onClick={() => setPeriod(p.key)}
            >
              {p.label}
            </Button>
          ))}
        </div>

        {loading && <p className="text-center py-8 text-muted-foreground">로딩 중...</p>}
        {error && <p className="text-center py-8 text-muted-foreground">{error}</p>}

        {data && !loading && (
          <div className="space-y-4">
            {/* Metrics grid */}
            <div className="grid grid-cols-2 gap-3">
              <MetricCard label="수익률" value={data.total_return} colorBySign />
              <MetricCard label="MDD" value={data.mdd} />
              <MetricCard label="변동성 (연환산)" value={data.volatility} />
              <MetricCard label="샤프비율" value={data.sharpe_ratio} suffix="" />
            </div>

            {/* Returns chart */}
            <div>
              <p className="text-sm font-medium mb-2">가상 수익률 추이</p>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data.chart_data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(v: string) => v.slice(5)}
                      tick={{ fontSize: 11 }}
                    />
                    <YAxis
                      tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                      tick={{ fontSize: 11 }}
                    />
                    <Tooltip
                      formatter={(v: number) => [`${v.toFixed(2)}%`, '수익률']}
                      labelFormatter={(l: string) => l}
                    />
                    <Line
                      type="monotone"
                      dataKey="return_rate"
                      stroke="#6366f1"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Drawdown chart */}
            <div>
              <p className="text-sm font-medium mb-2">Drawdown</p>
              <div className="h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={data.drawdown_data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(v: string) => v.slice(5)}
                      tick={{ fontSize: 11 }}
                    />
                    <YAxis
                      tickFormatter={(v: number) => `${v.toFixed(1)}%`}
                      tick={{ fontSize: 11 }}
                    />
                    <Tooltip
                      formatter={(v: number) => [`${v.toFixed(2)}%`, 'Drawdown']}
                      labelFormatter={(l: string) => l}
                    />
                    <Area
                      type="monotone"
                      dataKey="drawdown"
                      stroke="#ef4444"
                      fill="#ef444420"
                      strokeWidth={1.5}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            <p className="text-xs text-muted-foreground text-right">
              데이터 시작일: {data.actual_start_date}
            </p>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/RiskAnalysisDialog.tsx
git commit -m "feat: add RiskAnalysisDialog component"
```

---

### Task 5: Frontend — Integrate into dashboard page

**Files:**
- Modify: `frontend/src/app/PortfolioDashboardPage.tsx`

**Step 1: Add risk summary card to individual portfolio dashboard**

Add imports at the top of the file:

```typescript
import { useState as useStateImport } from 'react'  // already imported
import { portfolioApi } from '@/lib/api'  // already imported
import type { RiskAnalysisResponse } from '@/types/api'
import RiskAnalysisDialog from '@/components/RiskAnalysisDialog'
```

Actually, `useState` and `portfolioApi` are already imported. Just add:

```typescript
import type { RiskAnalysisResponse } from '@/types/api'
import RiskAnalysisDialog from '@/components/RiskAnalysisDialog'
```

**Step 2: Add state and fetch logic in the component**

Inside `PortfolioDashboardPage`, after the existing state declarations (around line 93-95), add:

```typescript
const [riskData, setRiskData] = useState<RiskAnalysisResponse | null>(null)
const [riskDialogOpen, setRiskDialogOpen] = useState(false)
```

Add a useEffect to fetch risk data for individual portfolios (after the existing dashboard useEffect, around line 113):

```typescript
useEffect(() => {
  if (!isAuthenticated || isTotal || !id) return
  portfolioApi.getRiskAnalysis(Number(id), '3m')
    .then(setRiskData)
    .catch(() => {})
}, [isAuthenticated, id, isTotal])
```

**Step 3: Add risk summary card in the JSX**

After the SummaryCards grid (after the closing `</div>` of the `grid gap-4 grid-cols-2 lg:grid-cols-4` div, around line 267), add:

```tsx
{/* Risk Summary Card (individual portfolio only) */}
{!isTotal && riskData && (
  <>
    <Card className="cursor-pointer hover:shadow-md transition-shadow" onClick={() => setRiskDialogOpen(true)}>
      <CardHeader className="px-4 py-2 pb-1">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          포트폴리오 리스크 (현재 구성 기준)
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4 pb-3 pt-0">
        <div className="flex items-center gap-6">
          <div>
            <p className="text-xs text-muted-foreground">MDD</p>
            <p className="text-lg font-bold text-blue-500">{riskData.mdd.toFixed(2)}%</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">변동성</p>
            <p className="text-lg font-bold">{riskData.volatility.toFixed(2)}%</p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">샤프비율</p>
            <p className="text-lg font-bold">{riskData.sharpe_ratio?.toFixed(2) ?? '-'}</p>
          </div>
          <Button variant="ghost" size="sm" className="ml-auto text-xs text-muted-foreground">
            자세히 보기 →
          </Button>
        </div>
      </CardContent>
    </Card>
    <RiskAnalysisDialog
      open={riskDialogOpen}
      onOpenChange={setRiskDialogOpen}
      portfolioId={Number(id)}
    />
  </>
)}
```

**Step 4: Commit**

```bash
git add frontend/src/app/PortfolioDashboardPage.tsx
git commit -m "feat: integrate risk analysis card and dialog into dashboard"
```

---

### Task 6: Build and verify

**Step 1: Build backend**

```bash
cd /home/sajacaros/workspace/etf-atlas && docker compose up -d --build backend
```

Verify no errors in logs: `docker compose logs backend --tail=20`

**Step 2: Build frontend**

```bash
cd /home/sajacaros/workspace/etf-atlas/frontend && npm run build
```

Verify no TypeScript errors.

**Step 3: Final commit (if any fixes needed)**

If any fixes were needed, commit them:
```bash
git add -A && git commit -m "fix: resolve build issues for risk analysis feature"
```
