# Portfolio Sharing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 포트폴리오 공유 기능 — 종목+비중 공개, 1000만원 기준 가상 수익률 차트 제공

**Architecture:** portfolios 테이블에 `is_shared`/`share_token` 컬럼 추가. 공유 토글은 기존 portfolios 라우터에, 공유 조회 API는 별도 `/api/shared` 라우터로 분리 (인증 불필요). 수익률은 `ticker_prices` 테이블의 일별 종가를 이용해 매 요청 시 실시간 계산.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, React, TypeScript, Recharts, TailwindCSS, shadcn/ui

**Design Doc:** `docs/plans/2026-02-24-portfolio-sharing-design.md`

---

### Task 1: Database Schema — portfolios 테이블에 공유 컬럼 추가

**Files:**
- Modify: `docker/db/init/01_extensions.sql` (portfolios CREATE TABLE 및 새 migration 스크립트)

**Step 1: init SQL에 컬럼 추가 (신규 환경용)**

`docker/db/init/01_extensions.sql`의 portfolios 테이블에 컬럼 추가:

```sql
CREATE TABLE IF NOT EXISTS portfolios (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL DEFAULT 'My Portfolio',
    calculation_base VARCHAR(20) NOT NULL DEFAULT 'CURRENT_TOTAL',
    target_total_amount DECIMAL(15, 2),
    display_order INTEGER NOT NULL DEFAULT 0,
    is_shared BOOLEAN NOT NULL DEFAULT FALSE,
    share_token UUID UNIQUE DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Step 2: 기존 환경용 마이그레이션 SQL 작성**

`docker/db/init/02_add_portfolio_sharing.sql` 파일 생성:

```sql
-- Portfolio sharing columns (idempotent)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'portfolios' AND column_name = 'is_shared'
    ) THEN
        ALTER TABLE portfolios ADD COLUMN is_shared BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'portfolios' AND column_name = 'share_token'
    ) THEN
        ALTER TABLE portfolios ADD COLUMN share_token UUID UNIQUE DEFAULT NULL;
    END IF;
END $$;
```

**Step 3: 마이그레이션 적용 확인**

Run: `docker compose exec db psql -U etf_user -d etf_atlas -c "\d portfolios"`
Expected: `is_shared` boolean, `share_token` uuid 컬럼 확인

**Step 4: Commit**

```bash
git add docker/db/init/01_extensions.sql docker/db/init/02_add_portfolio_sharing.sql
git commit -m "feat: add is_shared and share_token columns to portfolios table"
```

---

### Task 2: Backend Model — Portfolio 모델에 공유 필드 추가

**Files:**
- Modify: `backend/app/models/portfolio.py`

**Step 1: Portfolio 모델에 컬럼 추가**

`backend/app/models/portfolio.py`의 Portfolio 클래스에 import 추가 및 컬럼 추가:

```python
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Numeric, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
import uuid
```

Portfolio 클래스의 `display_order` 아래에 추가:

```python
    is_shared = Column(Boolean, nullable=False, default=False)
    share_token = Column(PG_UUID(as_uuid=True), unique=True, nullable=True)
```

**Step 2: Commit**

```bash
git add backend/app/models/portfolio.py
git commit -m "feat: add is_shared and share_token to Portfolio model"
```

---

### Task 3: Backend Schemas — 공유 관련 Pydantic 스키마 추가

**Files:**
- Modify: `backend/app/schemas/portfolio.py`

**Step 1: 공유 관련 스키마 추가**

`backend/app/schemas/portfolio.py` 파일 끝에 추가:

```python
# --- Sharing ---
class ShareToggleRequest(BaseModel):
    is_shared: bool


class ShareToggleResponse(BaseModel):
    is_shared: bool
    share_token: Optional[str] = None
    share_url: Optional[str] = None


class SharedPortfolioListItem(BaseModel):
    portfolio_name: str
    user_name: str
    share_token: str
    tickers_count: int
    updated_at: Optional[str] = None


class SharedAllocationItem(BaseModel):
    ticker: str
    name: str
    weight: float


class SharedPortfolioDetail(BaseModel):
    portfolio_name: str
    user_name: str
    allocations: list[SharedAllocationItem]


class SharedReturnsChartPoint(BaseModel):
    date: str
    value: float


class SharedReturnsResponse(BaseModel):
    base_amount: int = 10_000_000
    period: str
    actual_start_date: str
    chart_data: list[SharedReturnsChartPoint]
```

**Step 2: Commit**

```bash
git add backend/app/schemas/portfolio.py
git commit -m "feat: add sharing-related Pydantic schemas"
```

---

### Task 4: Backend API — 공유 토글 엔드포인트 (기존 portfolios 라우터)

**Files:**
- Modify: `backend/app/routers/portfolio.py`

**Step 1: 공유 토글 엔드포인트 추가**

`backend/app/routers/portfolio.py`에 import 추가:

```python
import uuid
from ..schemas.portfolio import ShareToggleRequest, ShareToggleResponse
```

라우터 파일의 적절한 위치 (CRUD 섹션 근처)에 엔드포인트 추가:

```python
@router.put("/{portfolio_id}/share", response_model=ShareToggleResponse)
async def toggle_share(
    portfolio_id: int,
    body: ShareToggleRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    portfolio.is_shared = body.is_shared
    if body.is_shared and not portfolio.share_token:
        portfolio.share_token = uuid.uuid4()
    db.commit()
    db.refresh(portfolio)
    token_str = str(portfolio.share_token) if portfolio.share_token else None
    return ShareToggleResponse(
        is_shared=portfolio.is_shared,
        share_token=token_str,
        share_url=f"/shared/{token_str}" if portfolio.is_shared and token_str else None,
    )
```

**Step 2: PortfolioDetailResponse에 공유 정보 추가**

`backend/app/schemas/portfolio.py`의 `PortfolioDetailResponse`에 필드 추가:

```python
class PortfolioDetailResponse(BaseModel):
    id: int
    name: str
    calculation_base: str
    target_total_amount: Optional[Decimal] = None
    is_shared: bool = False
    share_token: Optional[str] = None
    target_allocations: list[TargetAllocationResponse] = []
    holdings: list[HoldingResponse] = []

    class Config:
        from_attributes = True
```

기존 `GET /{portfolio_id}` 엔드포인트에서 share_token을 str로 변환하는 처리 추가 (이미 from_attributes=True이므로 모델 필드가 자동 매핑됨. 단, UUID → str 변환 필요):

portfolio 라우터의 `get_portfolio` 엔드포인트 응답에서 share_token 처리:

```python
@router.get("/{portfolio_id}", response_model=PortfolioDetailResponse)
async def get_portfolio(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    return PortfolioDetailResponse(
        id=portfolio.id,
        name=portfolio.name,
        calculation_base=portfolio.calculation_base,
        target_total_amount=portfolio.target_total_amount,
        is_shared=portfolio.is_shared,
        share_token=str(portfolio.share_token) if portfolio.share_token else None,
        target_allocations=[TargetAllocationResponse.model_validate(t) for t in portfolio.target_allocations],
        holdings=[HoldingResponse.model_validate(h) for h in portfolio.holdings],
    )
```

**Step 3: 동작 확인**

Run: `docker compose up -d --build backend`
Run: 기존 포트폴리오 상세 API 호출 시 `is_shared`, `share_token` 필드 확인

**Step 4: Commit**

```bash
git add backend/app/routers/portfolio.py backend/app/schemas/portfolio.py
git commit -m "feat: add share toggle endpoint and sharing fields to portfolio detail"
```

---

### Task 5: Backend API — 공유 조회 라우터 (shared.py)

**Files:**
- Create: `backend/app/routers/shared.py`
- Modify: `backend/app/main.py`

**Step 1: shared 라우터 생성**

`backend/app/routers/shared.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models.portfolio import Portfolio, TargetAllocation
from ..models.user import User
from ..schemas.portfolio import (
    SharedPortfolioListItem,
    SharedPortfolioDetail,
    SharedAllocationItem,
    SharedReturnsResponse,
    SharedReturnsChartPoint,
)
from ..services.price_service import PriceService
from decimal import Decimal
from datetime import date, timedelta

router = APIRouter()


@router.get("/", response_model=list[SharedPortfolioListItem])
async def list_shared_portfolios(db: Session = Depends(get_db)):
    portfolios = (
        db.query(Portfolio, User.name.label("user_name"))
        .join(User, Portfolio.user_id == User.id)
        .filter(Portfolio.is_shared == True)
        .order_by(Portfolio.updated_at.desc())
        .all()
    )
    result = []
    for p, user_name in portfolios:
        tickers_count = (
            db.query(func.count(TargetAllocation.id))
            .filter(TargetAllocation.portfolio_id == p.id)
            .scalar()
        )
        result.append(SharedPortfolioListItem(
            portfolio_name=p.name,
            user_name=user_name or "익명",
            share_token=str(p.share_token),
            tickers_count=tickers_count,
            updated_at=p.updated_at.isoformat() if p.updated_at else None,
        ))
    return result


def _get_shared_portfolio(db: Session, share_token: str) -> Portfolio:
    portfolio = db.query(Portfolio).filter(
        Portfolio.share_token == share_token,
        Portfolio.is_shared == True,
    ).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Shared portfolio not found")
    return portfolio


@router.get("/{share_token}", response_model=SharedPortfolioDetail)
async def get_shared_portfolio(share_token: str, db: Session = Depends(get_db)):
    portfolio = _get_shared_portfolio(db, share_token)
    user = db.query(User).filter(User.id == portfolio.user_id).first()

    allocations = (
        db.query(TargetAllocation)
        .filter(TargetAllocation.portfolio_id == portfolio.id)
        .all()
    )

    price_service = PriceService(db)
    tickers = [a.ticker for a in allocations]
    names = price_service.get_etf_names(tickers)

    return SharedPortfolioDetail(
        portfolio_name=portfolio.name,
        user_name=user.name if user else "익명",
        allocations=[
            SharedAllocationItem(
                ticker=a.ticker,
                name=names.get(a.ticker, a.ticker),
                weight=float(a.target_weight),
            )
            for a in allocations
        ],
    )


@router.get("/{share_token}/returns", response_model=SharedReturnsResponse)
async def get_shared_returns(
    share_token: str,
    period: str = Query(default="1m", regex="^(1w|1m|3m)$"),
    db: Session = Depends(get_db),
):
    portfolio = _get_shared_portfolio(db, share_token)

    allocations = (
        db.query(TargetAllocation)
        .filter(TargetAllocation.portfolio_id == portfolio.id)
        .all()
    )
    if not allocations:
        raise HTTPException(status_code=404, detail="No allocations found")

    tickers = [a.ticker for a in allocations if a.ticker != "CASH"]
    weights = {a.ticker: float(a.target_weight) / 100.0 for a in allocations if a.ticker != "CASH"}

    if not tickers:
        raise HTTPException(status_code=400, detail="No ETF tickers in portfolio")

    # 기간 계산
    today = date.today()
    period_days = {"1w": 7, "1m": 30, "3m": 90}
    start_date = today - timedelta(days=period_days[period])

    # ticker_prices에서 기간 내 일별 종가 조회
    from sqlalchemy import text
    result = db.execute(
        text("""
            SELECT ticker, date, price
            FROM ticker_prices
            WHERE ticker = ANY(:tickers)
              AND date >= :start_date
            ORDER BY date
        """),
        {"tickers": tickers, "start_date": start_date},
    )

    # ticker별 날짜->가격 매핑
    price_map: dict[str, dict[date, float]] = {}
    all_dates: set[date] = set()
    for row in result:
        t, d, p = row.ticker, row.date, float(row.price)
        price_map.setdefault(t, {})[d] = p
        all_dates.add(d)

    if not all_dates:
        raise HTTPException(status_code=404, detail="No price data available")

    # 모든 티커에 데이터가 있는 날짜만 필터
    common_dates = sorted(all_dates)
    common_dates = [
        d for d in common_dates
        if all(d in price_map.get(t, {}) for t in tickers)
    ]

    if len(common_dates) < 2:
        raise HTTPException(status_code=404, detail="Insufficient price data")

    actual_start_date = common_dates[0]
    base_amount = 10_000_000

    # 시작일 종가 기준 가상 매수수량 계산
    # 비중 정규화 (CASH 제외 후 합이 1이 되도록)
    total_weight = sum(weights.values())
    norm_weights = {t: w / total_weight for t, w in weights.items()} if total_weight > 0 else weights

    virtual_quantities: dict[str, float] = {}
    for t in tickers:
        allocated = base_amount * norm_weights.get(t, 0)
        start_price = price_map[t][actual_start_date]
        virtual_quantities[t] = allocated / start_price if start_price > 0 else 0

    # 일별 가상 포트폴리오 가치 계산
    chart_data = []
    for d in common_dates:
        daily_value = sum(
            virtual_quantities[t] * price_map[t][d]
            for t in tickers
        )
        chart_data.append(SharedReturnsChartPoint(
            date=d.isoformat(),
            value=round(daily_value, 0),
        ))

    return SharedReturnsResponse(
        base_amount=base_amount,
        period=period,
        actual_start_date=actual_start_date.isoformat(),
        chart_data=chart_data,
    )
```

**Step 2: main.py에 shared 라우터 등록**

`backend/app/main.py`에 import 추가:

```python
from .routers import auth, etfs, watchlist, portfolio, tags, chat, notifications, admin, shared
```

라우터 등록 (portfolio 라우터 아래에):

```python
app.include_router(shared.router, prefix="/api/shared", tags=["Shared"])
```

**Step 3: 빌드 및 동작 확인**

Run: `docker compose up -d --build backend`

**Step 4: Commit**

```bash
git add backend/app/routers/shared.py backend/app/main.py
git commit -m "feat: add shared portfolios router with list, detail, and returns endpoints"
```

---

### Task 6: Frontend Types — 공유 관련 TypeScript 타입 추가

**Files:**
- Modify: `frontend/src/types/api.ts`

**Step 1: 공유 관련 타입 추가**

`frontend/src/types/api.ts` 파일 끝에 추가:

```typescript
// Shared Portfolio types
export interface SharedPortfolioListItem {
  portfolio_name: string
  user_name: string
  share_token: string
  tickers_count: number
  updated_at: string | null
}

export interface SharedAllocationItem {
  ticker: string
  name: string
  weight: number
}

export interface SharedPortfolioDetail {
  portfolio_name: string
  user_name: string
  allocations: SharedAllocationItem[]
}

export interface SharedReturnsChartPoint {
  date: string
  value: number
}

export interface SharedReturnsResponse {
  base_amount: number
  period: string
  actual_start_date: string
  chart_data: SharedReturnsChartPoint[]
}

export interface ShareToggleResponse {
  is_shared: boolean
  share_token: string | null
  share_url: string | null
}
```

`PortfolioDetail` 인터페이스에 공유 필드 추가:

```typescript
export interface PortfolioDetail {
  id: number
  name: string
  calculation_base: CalculationBase
  target_total_amount: number | null
  is_shared: boolean
  share_token: string | null
  target_allocations: TargetAllocationItem[]
  holdings: HoldingItem[]
}
```

**Step 2: Commit**

```bash
git add frontend/src/types/api.ts
git commit -m "feat: add shared portfolio TypeScript types"
```

---

### Task 7: Frontend API — 공유 관련 API 클라이언트

**Files:**
- Modify: `frontend/src/lib/api.ts`

**Step 1: sharedApi 객체 추가**

`frontend/src/lib/api.ts`에 import 추가 (기존 import에 새 타입 추가):

```typescript
import type {
  // ... 기존 imports ...
  SharedPortfolioListItem,
  SharedPortfolioDetail,
  SharedReturnsResponse,
  ShareToggleResponse,
} from '@/types/api'
```

portfolioApi 객체에 share 토글 메서드 추가:

```typescript
  toggleShare: async (portfolioId: number, isShared: boolean) => {
    const { data } = await api.put<ShareToggleResponse>(`/portfolios/${portfolioId}/share`, { is_shared: isShared })
    return data
  },
```

파일 끝에 sharedApi 객체 추가:

```typescript
// Shared Portfolios
export const sharedApi = {
  getAll: async () => {
    const { data } = await api.get<SharedPortfolioListItem[]>('/shared/')
    return data
  },
  get: async (shareToken: string) => {
    const { data } = await api.get<SharedPortfolioDetail>(`/shared/${shareToken}`)
    return data
  },
  getReturns: async (shareToken: string, period: string = '1m') => {
    const { data } = await api.get<SharedReturnsResponse>(`/shared/${shareToken}/returns`, { params: { period } })
    return data
  },
}
```

**Step 2: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat: add shared portfolio API client"
```

---

### Task 8: Frontend — 공유 포트폴리오 목록 페이지

**Files:**
- Create: `frontend/src/app/SharedPortfoliosPage.tsx`

**Step 1: 목록 페이지 컴포넌트 작성**

```tsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { sharedApi } from '@/lib/api'
import type { SharedPortfolioListItem } from '@/types/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Users } from 'lucide-react'

export default function SharedPortfoliosPage() {
  const navigate = useNavigate()
  const [portfolios, setPortfolios] = useState<SharedPortfolioListItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    sharedApi.getAll()
      .then(setPortfolios)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-center py-12 text-muted-foreground">로딩 중...</div>

  if (portfolios.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Users className="w-12 h-12 mx-auto mb-4 opacity-50" />
        <p>공유된 포트폴리오가 없습니다</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">공유 포트폴리오</h1>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {portfolios.map((p) => (
          <Card
            key={p.share_token}
            className="cursor-pointer hover:shadow-md transition-shadow"
            onClick={() => navigate(`/shared/${p.share_token}`)}
          >
            <CardHeader className="pb-2">
              <CardTitle className="text-lg">{p.portfolio_name}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-sm text-muted-foreground space-y-1">
                <p>{p.user_name}</p>
                <p>종목 {p.tickers_count}개</p>
                {p.updated_at && (
                  <p className="text-xs">
                    {new Date(p.updated_at).toLocaleDateString('ko-KR')}
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
```

**Step 2: Commit**

```bash
git add frontend/src/app/SharedPortfoliosPage.tsx
git commit -m "feat: add shared portfolios list page"
```

---

### Task 9: Frontend — 공유 포트폴리오 상세 페이지

**Files:**
- Create: `frontend/src/app/SharedPortfolioDetailPage.tsx`

**Step 1: 상세 페이지 컴포넌트 작성**

```tsx
import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { sharedApi } from '@/lib/api'
import type { SharedPortfolioDetail, SharedReturnsResponse } from '@/types/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { ArrowLeft } from 'lucide-react'
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts'

const PERIODS = [
  { key: '1w', label: '1주' },
  { key: '1m', label: '1개월' },
  { key: '3m', label: '3개월' },
] as const

export default function SharedPortfolioDetailPage() {
  const { shareToken } = useParams<{ shareToken: string }>()
  const [detail, setDetail] = useState<SharedPortfolioDetail | null>(null)
  const [returns, setReturns] = useState<SharedReturnsResponse | null>(null)
  const [period, setPeriod] = useState('1m')
  const [loading, setLoading] = useState(true)
  const [returnsError, setReturnsError] = useState<string | null>(null)

  useEffect(() => {
    if (!shareToken) return
    sharedApi.get(shareToken)
      .then(setDetail)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [shareToken])

  useEffect(() => {
    if (!shareToken) return
    setReturnsError(null)
    sharedApi.getReturns(shareToken, period)
      .then(setReturns)
      .catch(() => setReturnsError('수익률 데이터를 불러올 수 없습니다'))
  }, [shareToken, period])

  if (loading) return <div className="text-center py-12 text-muted-foreground">로딩 중...</div>
  if (!detail) return <div className="text-center py-12 text-muted-foreground">포트폴리오를 찾을 수 없습니다</div>

  const totalWeight = detail.allocations.reduce((sum, a) => sum + a.weight, 0)

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Link to="/shared">
          <Button variant="ghost" size="sm"><ArrowLeft className="w-4 h-4 mr-1" />목록</Button>
        </Link>
        <div>
          <h1 className="text-2xl font-bold">{detail.portfolio_name}</h1>
          <p className="text-sm text-muted-foreground">{detail.user_name}</p>
        </div>
      </div>

      {/* 종목 비중 테이블 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">종목 비중</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="text-left py-2">종목</th>
                <th className="text-left py-2">티커</th>
                <th className="text-right py-2">비중</th>
              </tr>
            </thead>
            <tbody>
              {detail.allocations.map((a) => (
                <tr key={a.ticker} className="border-b">
                  <td className="py-2">{a.name}</td>
                  <td className="py-2 text-muted-foreground">{a.ticker}</td>
                  <td className="py-2 text-right font-medium">{a.weight.toFixed(1)}%</td>
                </tr>
              ))}
              <tr className="font-semibold">
                <td className="py-2" colSpan={2}>합계</td>
                <td className="py-2 text-right">{totalWeight.toFixed(1)}%</td>
              </tr>
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* 가상 수익률 차트 */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg">
              가상 수익률 (1,000만원 기준)
            </CardTitle>
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
          </div>
        </CardHeader>
        <CardContent>
          {returnsError ? (
            <p className="text-center text-sm text-muted-foreground py-8">{returnsError}</p>
          ) : !returns ? (
            <p className="text-center text-sm text-muted-foreground py-8">로딩 중...</p>
          ) : (
            <>
              {returns.actual_start_date !== returns.chart_data[0]?.date && (
                <p className="text-xs text-muted-foreground mb-2">
                  * 데이터 시작일: {returns.actual_start_date}
                </p>
              )}
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={returns.chart_data}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={(v: string) => v.slice(5)}
                      tick={{ fontSize: 12 }}
                    />
                    <YAxis
                      tickFormatter={(v: number) => `${(v / 10000).toFixed(0)}만`}
                      tick={{ fontSize: 12 }}
                    />
                    <Tooltip
                      formatter={(v: number) => [`${v.toLocaleString()}원`, '평가금액']}
                      labelFormatter={(l: string) => l}
                    />
                    <Line
                      type="monotone"
                      dataKey="value"
                      stroke="#2563eb"
                      strokeWidth={2}
                      dot={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              {returns.chart_data.length > 0 && (
                <div className="mt-4 flex gap-4 text-sm">
                  <span>시작: {returns.chart_data[0].value.toLocaleString()}원</span>
                  <span>현재: {returns.chart_data[returns.chart_data.length - 1].value.toLocaleString()}원</span>
                  <span className={
                    returns.chart_data[returns.chart_data.length - 1].value >= returns.chart_data[0].value
                      ? 'text-green-600' : 'text-red-600'
                  }>
                    수익률: {(
                      ((returns.chart_data[returns.chart_data.length - 1].value - returns.chart_data[0].value) /
                        returns.chart_data[0].value) * 100
                    ).toFixed(2)}%
                  </span>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
```

**Step 2: Commit**

```bash
git add frontend/src/app/SharedPortfolioDetailPage.tsx
git commit -m "feat: add shared portfolio detail page with returns chart"
```

---

### Task 10: Frontend — 라우팅 및 네비게이션 추가

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Header.tsx`

**Step 1: App.tsx에 라우트 추가**

import 추가:

```typescript
import SharedPortfoliosPage from '@/app/SharedPortfoliosPage'
import SharedPortfolioDetailPage from '@/app/SharedPortfolioDetailPage'
```

Routes 내에 추가 (`/chat` 라우트 위에):

```tsx
<Route path="/shared" element={<SharedPortfoliosPage />} />
<Route path="/shared/:shareToken" element={<SharedPortfolioDetailPage />} />
```

**Step 2: Header.tsx에 Shared 네비게이션 추가**

import에 `Share2` 아이콘 추가:

```typescript
import { Search, PieChart, User, LogOut, MessageCircle, Bell, BookOpen, Shield, Share2 } from 'lucide-react'
```

포트폴리오 Link 바로 아래에 (line 43 근처, `</Link>` 뒤에) 추가:

```tsx
            <Link
              to="/shared"
              className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
            >
              <Share2 className="w-4 h-4" />
              Shared
            </Link>
```

**Step 3: 동작 확인**

Run: `docker compose up -d --build frontend`
Expected: 네비게이션에 "Shared" 메뉴 표시, `/shared` 페이지 접근 가능

**Step 4: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/Header.tsx
git commit -m "feat: add shared portfolio routes and navigation menu"
```

---

### Task 11: Frontend — 포트폴리오 상세에 공유 토글 추가

**Files:**
- Modify: `frontend/src/app/PortfolioPage.tsx`

**Step 1: 공유 토글 UI 추가**

포트폴리오 상세 영역 (종목 편집 영역 상단)에 공유 토글 스위치를 추가.

필요한 import 추가:

```typescript
import { portfolioApi } from '@/lib/api'
import { Switch } from '@/components/ui/switch'
import { Share2, Copy, Check } from 'lucide-react'
```

포트폴리오 상세 섹션에 공유 토글 UI 추가:

```tsx
{/* 공유 설정 */}
{detail && (
  <div className="flex items-center gap-4 p-4 bg-muted/50 rounded-lg">
    <Share2 className="w-5 h-5 text-muted-foreground" />
    <div className="flex-1">
      <span className="text-sm font-medium">포트폴리오 공유</span>
      {detail.is_shared && detail.share_token && (
        <div className="flex items-center gap-2 mt-1">
          <code className="text-xs bg-background px-2 py-1 rounded">
            {window.location.origin}/shared/{detail.share_token}
          </code>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              navigator.clipboard.writeText(
                `${window.location.origin}/shared/${detail.share_token}`
              )
              // 복사 피드백은 toast 또는 아이콘 변경으로
            }}
          >
            <Copy className="w-3 h-3" />
          </Button>
        </div>
      )}
    </div>
    <Switch
      checked={detail.is_shared}
      onCheckedChange={async (checked) => {
        const res = await portfolioApi.toggleShare(detail.id, checked)
        setDetail({ ...detail, is_shared: res.is_shared, share_token: res.share_token })
      }}
    />
  </div>
)}
```

**Step 2: PortfolioDetail 상태에 공유 필드 포함 확인**

기존 detail 상태가 `PortfolioDetail` 타입을 사용하고 있으므로, Task 6에서 이미 `is_shared`와 `share_token`을 추가했기 때문에 자동으로 포함됨.

**Step 3: 동작 확인**

Run: `docker compose up -d --build frontend`
Expected: 포트폴리오 상세에서 공유 토글 표시, ON 시 공유 링크 표시

**Step 4: Commit**

```bash
git add frontend/src/app/PortfolioPage.tsx
git commit -m "feat: add share toggle switch to portfolio detail page"
```

---

### Task 12: 빌드, 마이그레이션, 통합 테스트

**Step 1: DB 마이그레이션 적용**

```bash
docker compose exec db psql -U etf_user -d etf_atlas -f /docker-entrypoint-initdb.d/02_add_portfolio_sharing.sql
```

또는 직접 실행:

```bash
docker compose exec db psql -U etf_user -d etf_atlas -c "
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='portfolios' AND column_name='is_shared') THEN
        ALTER TABLE portfolios ADD COLUMN is_shared BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='portfolios' AND column_name='share_token') THEN
        ALTER TABLE portfolios ADD COLUMN share_token UUID UNIQUE DEFAULT NULL;
    END IF;
END \$\$;
"
```

**Step 2: 전체 빌드**

```bash
docker compose up -d --build backend frontend
```

**Step 3: 통합 테스트 — API 확인**

```bash
# 1. 공유 토글 (인증 필요)
curl -X PUT http://localhost:8000/api/portfolios/{ID}/share \
  -H "Authorization: Bearer {TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"is_shared": true}'

# 2. 공유 목록 (비인증)
curl http://localhost:8000/api/shared/

# 3. 공유 상세 (비인증)
curl http://localhost:8000/api/shared/{SHARE_TOKEN}

# 4. 가상 수익률 (비인증)
curl "http://localhost:8000/api/shared/{SHARE_TOKEN}/returns?period=1m"
```

**Step 4: 프론트엔드 수동 테스트**

1. 포트폴리오 상세 → 공유 토글 ON → 링크 생성 확인
2. Shared 메뉴 클릭 → 공유 포트폴리오 목록 표시
3. 카드 클릭 → 상세 페이지 (종목+비중 테이블 + 수익률 차트)
4. 기간 선택 (1주/1개월/3개월) → 차트 변경 확인
5. 비로그인 상태에서 공유 링크 접근 가능 확인

**Step 5: 최종 Commit**

```bash
git add -A
git commit -m "feat: complete portfolio sharing feature integration"
```
