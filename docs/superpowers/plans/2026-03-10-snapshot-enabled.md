# Snapshot Enabled Flag Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-portfolio `snapshot_enabled` toggle so users control when snapshot collection begins.

**Architecture:** Add boolean column to portfolios table, update backend model/schema/router to support it with immediate snapshot on toggle-on, filter Airflow DAG by flag, and add toggle switch UI to portfolio cards. Remove backfill endpoint and button.

**Tech Stack:** PostgreSQL, SQLAlchemy, FastAPI, React, TypeScript, shadcn/ui Switch component

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `docker/db/init/01_extensions.sql` | Add `snapshot_enabled` column to portfolios DDL |
| Modify | `backend/app/models/portfolio.py` | Add `snapshot_enabled` field to Portfolio model |
| Modify | `backend/app/schemas/portfolio.py` | Add field to response/update schemas, remove BackfillSnapshotResponse |
| Modify | `backend/app/routers/portfolio.py` | Update PATCH endpoint with snapshot-on-toggle logic, remove backfill endpoint |
| Modify | `airflow/dags/realtime_prices_rdb.py` | Filter by `snapshot_enabled=true` in update_snapshots |
| Modify | `frontend/src/types/api.ts` | Add `snapshot_enabled` to Portfolio type |
| Modify | `frontend/src/lib/api.ts` | Remove backfillSnapshots method |
| Modify | `frontend/src/app/PortfolioPage.tsx` | Remove backfill button, add toggle switch |

---

## Chunk 1: Backend Changes

### Task 1: Database Schema

**Files:**
- Modify: `docker/db/init/01_extensions.sql:58-69`

- [ ] **Step 1: Add snapshot_enabled column to portfolios table DDL**

In `docker/db/init/01_extensions.sql`, add `snapshot_enabled BOOLEAN NOT NULL DEFAULT FALSE` to the portfolios CREATE TABLE statement, after `share_token`:

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
    snapshot_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

- [ ] **Step 2: Add ALTER TABLE migration for existing databases**

At the bottom of `01_extensions.sql` (where other ALTER TABLE statements are), add:

```sql
ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS snapshot_enabled BOOLEAN NOT NULL DEFAULT FALSE;
```

- [ ] **Step 3: Commit**

```bash
git add docker/db/init/01_extensions.sql
git commit -m "feat: add snapshot_enabled column to portfolios table"
```

### Task 2: Backend Model & Schema

**Files:**
- Modify: `backend/app/models/portfolio.py:10-22`
- Modify: `backend/app/schemas/portfolio.py`

- [ ] **Step 1: Add snapshot_enabled to Portfolio model**

In `backend/app/models/portfolio.py`, add after the `share_token` column (line 20):

```python
snapshot_enabled = Column(Boolean, nullable=False, default=False)
```

- [ ] **Step 2: Add snapshot_enabled to PortfolioUpdate schema**

In `backend/app/schemas/portfolio.py`, add to `PortfolioUpdate` class:

```python
class PortfolioUpdate(BaseModel):
    name: Optional[str] = None
    calculation_base: Optional[str] = None
    target_total_amount: Optional[Decimal] = None
    snapshot_enabled: Optional[bool] = None
```

- [ ] **Step 3: Add snapshot_enabled to PortfolioResponse schema**

In `backend/app/schemas/portfolio.py`, add to `PortfolioResponse` class after `investment_return_rate`:

```python
snapshot_enabled: bool = False
```

- [ ] **Step 4: Add snapshot_enabled to PortfolioDetailResponse schema**

In `backend/app/schemas/portfolio.py`, add to `PortfolioDetailResponse` class after `share_token`:

```python
snapshot_enabled: bool = False
```

- [ ] **Step 5: Remove BackfillSnapshotResponse schema**

Delete from `backend/app/schemas/portfolio.py`:

```python
# --- Backfill ---
class BackfillSnapshotResponse(BaseModel):
    created: int
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/portfolio.py backend/app/schemas/portfolio.py
git commit -m "feat: add snapshot_enabled to portfolio model and schemas"
```

### Task 3: Backend Router - Update endpoint & Remove backfill

**Files:**
- Modify: `backend/app/routers/portfolio.py`

- [ ] **Step 1: Remove BackfillSnapshotResponse from imports**

In `backend/app/routers/portfolio.py` line 22, remove `BackfillSnapshotResponse` from the import.

- [ ] **Step 2: Update the PUT /{portfolio_id} endpoint to handle snapshot_enabled toggle**

Replace the `update_portfolio` function (lines 202-218) with:

```python
@router.put("/{portfolio_id}", response_model=PortfolioResponse)
async def update_portfolio(
    portfolio_id: int,
    request: PortfolioUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)

    # Detect snapshot_enabled toggle: false -> true
    snapshot_just_enabled = (
        request.snapshot_enabled is True and not portfolio.snapshot_enabled
    )

    if request.name is not None:
        portfolio.name = request.name
    if request.calculation_base is not None:
        portfolio.calculation_base = request.calculation_base
    if request.target_total_amount is not None:
        portfolio.target_total_amount = request.target_total_amount
    if request.snapshot_enabled is not None:
        portfolio.snapshot_enabled = request.snapshot_enabled

    db.commit()
    db.refresh(portfolio)

    # On toggle ON: create immediate snapshot from ticker_prices
    if snapshot_just_enabled:
        _try_create_immediate_snapshot(db, portfolio)

    return portfolio
```

- [ ] **Step 3: Add _try_create_immediate_snapshot helper function**

Add before the `update_portfolio` function (around line 200):

```python
def _try_create_immediate_snapshot(db: Session, portfolio: Portfolio):
    """snapshot_enabled 토글 ON 시 ticker_prices 기반으로 즉시 스냅샷 생성 시도."""
    holdings = db.query(Holding).filter(Holding.portfolio_id == portfolio.id).all()
    if not holdings:
        return

    tickers = [h.ticker for h in holdings if h.ticker != 'CASH']
    if not tickers:
        # CASH only portfolio
        total_value = sum(Decimal(str(h.quantity)) for h in holdings if h.ticker == 'CASH')
    else:
        # Get latest prices from ticker_prices table
        from sqlalchemy import func as sa_func
        latest_date = db.query(sa_func.max(TickerPrice.date)).scalar()
        if not latest_date:
            return

        price_rows = db.query(TickerPrice).filter(
            TickerPrice.ticker.in_(tickers),
            TickerPrice.date == latest_date,
        ).all()
        price_map = {r.ticker: Decimal(str(r.price)) for r in price_rows}

        # If any ticker is missing price, skip
        if any(t not in price_map for t in tickers):
            return

        total_value = Decimal('0')
        for h in holdings:
            if h.ticker == 'CASH':
                total_value += Decimal(str(h.quantity))
            else:
                total_value += Decimal(str(h.quantity)) * price_map[h.ticker]

    today = date.today()
    existing = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.portfolio_id == portfolio.id,
        PortfolioSnapshot.date == today,
    ).first()

    if existing:
        existing.total_value = total_value
        existing.updated_at = datetime.utcnow()
    else:
        # Get previous snapshot for change calculation
        prev_snapshot = db.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.portfolio_id == portfolio.id,
            PortfolioSnapshot.date < today,
        ).order_by(PortfolioSnapshot.date.desc()).first()

        prev_value = Decimal(str(prev_snapshot.total_value)) if prev_snapshot else None
        change_amount = total_value - prev_value if prev_value else None
        change_rate = float(change_amount / prev_value * 100) if prev_value and prev_value != 0 else None

        snapshot = PortfolioSnapshot(
            portfolio_id=portfolio.id,
            date=today,
            total_value=total_value,
            prev_value=prev_value,
            change_amount=change_amount,
            change_rate=change_rate,
        )
        db.add(snapshot)

    db.commit()
```

- [ ] **Step 4: Remove the backfill endpoint and helper functions**

Delete the entire section from line 651 to 744:
- Comment `# --- Backfill Snapshots ---`
- Function `_get_latest_trading_date`
- Function `_fetch_prices_by_yfinance`
- Function `backfill_snapshots` (the endpoint)

Also remove the comment `# --- Snapshot Refresh ---` (line 816).

- [ ] **Step 5: Update get_portfolios to include snapshot_enabled in response**

In the `get_portfolios` function (line 105), add `snapshot_enabled` to the PortfolioResponse constructor:

```python
result.append(PortfolioResponse(
    id=p.id,
    name=p.name,
    calculation_base=p.calculation_base,
    target_total_amount=p.target_total_amount,
    snapshot_enabled=p.snapshot_enabled,
    current_value=cur_val,
    ...
))
```

- [ ] **Step 6: Update get_portfolio detail to include snapshot_enabled**

In the `get_portfolio` function (line 190), add `snapshot_enabled` to PortfolioDetailResponse:

```python
return PortfolioDetailResponse(
    id=portfolio.id,
    name=portfolio.name,
    calculation_base=portfolio.calculation_base,
    target_total_amount=portfolio.target_total_amount,
    snapshot_enabled=portfolio.snapshot_enabled,
    is_shared=portfolio.is_shared,
    ...
)
```

Also update `batch_update_portfolio` (line 285) similarly.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/portfolio.py
git commit -m "feat: add snapshot toggle logic to update endpoint, remove backfill"
```

### Task 4: Airflow DAG

**Files:**
- Modify: `airflow/dags/realtime_prices_rdb.py:226-228`

- [ ] **Step 1: Filter by snapshot_enabled in update_snapshots**

In `airflow/dags/realtime_prices_rdb.py`, replace the portfolio query (line 227):

```python
# Before:
cur.execute("SELECT DISTINCT portfolio_id FROM holdings")

# After:
cur.execute("""
    SELECT DISTINCT h.portfolio_id
    FROM holdings h
    JOIN portfolios p ON p.id = h.portfolio_id
    WHERE p.snapshot_enabled = true
""")
```

- [ ] **Step 2: Commit**

```bash
git add airflow/dags/realtime_prices_rdb.py
git commit -m "feat: filter snapshot updates by snapshot_enabled flag"
```

---

## Chunk 2: Frontend Changes

### Task 5: Frontend Types & API

**Files:**
- Modify: `frontend/src/types/api.ts:88-101`
- Modify: `frontend/src/lib/api.ts:195-198`

- [ ] **Step 1: Add snapshot_enabled to Portfolio type**

In `frontend/src/types/api.ts`, add to `Portfolio` interface after `investment_return_rate`:

```typescript
export interface Portfolio {
  id: number
  name: string
  calculation_base: CalculationBase
  target_total_amount: number | null
  display_order: number
  current_value: number | null
  current_value_date: string | null
  current_value_updated_at: string | null
  daily_change_amount: number | null
  daily_change_rate: number | null
  invested_amount: number | null
  investment_return_rate: number | null
  snapshot_enabled: boolean
}
```

- [ ] **Step 2: Add snapshot_enabled to PortfolioDetail type**

In `frontend/src/types/api.ts`, add to `PortfolioDetail` interface after `share_token`:

```typescript
export interface PortfolioDetail {
  id: number
  name: string
  calculation_base: CalculationBase
  target_total_amount: number | null
  is_shared: boolean
  share_token: string | null
  snapshot_enabled: boolean
  target_allocations: TargetAllocationItem[]
  holdings: HoldingItem[]
}
```

- [ ] **Step 3: Remove backfillSnapshots from API client**

In `frontend/src/lib/api.ts`, delete lines 195-198:

```typescript
// DELETE THIS:
backfillSnapshots: async (portfolioId: number) => {
  const { data } = await api.post<{ created: number }>(`/portfolios/${portfolioId}/backfill-snapshots`)
  return data
},
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/api.ts frontend/src/lib/api.ts
git commit -m "feat: add snapshot_enabled to frontend types, remove backfill API"
```

### Task 6: Portfolio Card UI

**Files:**
- Modify: `frontend/src/app/PortfolioPage.tsx`

- [ ] **Step 1: Add Switch import and remove backfill-related imports**

Update imports at the top of `PortfolioPage.tsx`:

```typescript
// Add Switch import:
import { Switch } from '@/components/ui/switch'

// Remove RefreshCw from lucide-react imports (line 4) - but keep it since it's used elsewhere (detail view refresh button)
// Actually RefreshCw is still used on line 763, so keep it
```

- [ ] **Step 2: Update SortablePortfolioCard props - remove backfill, add snapshot toggle**

Remove `onBackfill` and `backfillLoading` props, add `onToggleSnapshot`:

```typescript
function SortablePortfolioCard({
  portfolio: p,
  onSelect,
  onDelete,
  onToggleSnapshot,
  onDashboard,
  amountVisible,
  formatMaskedNumber: fmn,
}: {
  portfolio: Portfolio
  onSelect: (id: number) => void
  onDelete: (id: number) => void
  onToggleSnapshot: (id: number, enabled: boolean) => void
  onDashboard: (id: number) => void
  amountVisible: boolean
  formatMaskedNumber: (v: number, visible: boolean) => string
}) {
```

- [ ] **Step 3: Replace card content - remove backfill button, add toggle and states**

Replace the CardContent section (lines 124-211) with:

```tsx
<CardContent>
  {p.snapshot_enabled && p.current_value != null && p.current_value_date ? (
    <div className="space-y-2">
      {/* 평가금액 */}
      <div>
        <p className="text-xs text-muted-foreground">평가금액</p>
        <p className="text-xl font-bold font-mono">
          {fmn(p.current_value, amountVisible)}{amountVisible && '원'}
        </p>
      </div>

      {/* 투자원금 / 수익금 */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="text-xs text-muted-foreground">투자원금</p>
          <p className="text-sm font-mono">
            {p.invested_amount == null ? '-' : !amountVisible ? '••••••' : `${formatNumber(p.invested_amount)}원`}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">수익금</p>
          {p.invested_amount == null ? (
            <p className="text-sm font-mono">-</p>
          ) : (() => {
            const profit = p.current_value! - p.invested_amount!
            return (
              <p className={`text-sm font-mono ${profit >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
                {amountVisible ? `${profit >= 0 ? '+' : ''}${formatNumber(profit)}원` : '••••••'}
              </p>
            )
          })()}
        </div>
      </div>

      {/* 수익률 / 전일대비 */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="text-xs text-muted-foreground">수익률</p>
          <p className={`text-sm font-mono font-semibold ${p.investment_return_rate != null ? (p.investment_return_rate >= 0 ? 'text-red-500' : 'text-blue-500') : ''}`}>
            {p.investment_return_rate == null ? '-' : amountVisible ? `${p.investment_return_rate >= 0 ? '+' : ''}${p.investment_return_rate.toFixed(2)}%` : '••••••'}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">전일대비</p>
          <p className={`text-sm font-mono font-semibold ${(p.daily_change_rate ?? 0) >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
            {amountVisible ? (
              <>
                {(p.daily_change_amount ?? 0) >= 0 ? '+' : ''}{formatNumber(p.daily_change_amount ?? 0)}원
                <span className="font-normal text-xs ml-0.5">
                  ({(p.daily_change_rate ?? 0) >= 0 ? '+' : ''}{(p.daily_change_rate ?? 0).toFixed(2)}%)
                </span>
              </>
            ) : '••••••'}
          </p>
        </div>
      </div>
    </div>
  ) : p.snapshot_enabled ? (
    <p className="text-sm text-muted-foreground">스냅샷 대기 중</p>
  ) : (
    <p className="text-sm text-muted-foreground">스냅샷 비활성</p>
  )}

  <div className="flex items-center justify-between mt-3">
    <div className="flex items-center gap-2">
      <Switch
        checked={p.snapshot_enabled}
        onCheckedChange={(checked) => {
          onToggleSnapshot(p.id, checked)
        }}
        onClick={(e) => e.stopPropagation()}
      />
      <span className="text-xs text-muted-foreground">
        {p.snapshot_enabled ? '스냅샷 활성' : '스냅샷 비활성'}
      </span>
    </div>
    <Button
      variant="outline"
      size="sm"
      onClick={(e) => {
        e.stopPropagation()
        onDashboard(p.id)
      }}
    >
      <BarChart3 className="w-4 h-4 mr-1" />
      대시보드
    </Button>
  </div>
</CardContent>
```

- [ ] **Step 4: Remove backfill state and handler from PortfolioPage component**

In the `PortfolioPage` component, remove:

```typescript
// Remove this state (line 231):
const [backfillLoading, setBackfillLoading] = useState<number | null>(null)

// Remove this handler (lines 404-417):
const handleBackfill = async (id: number) => { ... }
```

- [ ] **Step 5: Add handleToggleSnapshot handler**

Add after the existing handlers:

```typescript
const handleToggleSnapshot = async (id: number, enabled: boolean) => {
  try {
    await portfolioApi.update(id, { snapshot_enabled: enabled })
    const data = await portfolioApi.getAll()
    setPortfolios(data)
    toast({ title: enabled ? '스냅샷이 활성화되었습니다' : '스냅샷이 비활성화되었습니다' })
  } catch {
    toast({ title: '스냅샷 설정 변경 실패', variant: 'destructive' })
  }
}
```

- [ ] **Step 6: Update SortablePortfolioCard usage in render**

Replace the props passed to `SortablePortfolioCard` (lines 1059-1069):

```tsx
<SortablePortfolioCard
  key={p.id}
  portfolio={p}
  onSelect={selectPortfolio}
  onDelete={handleDelete}
  onToggleSnapshot={handleToggleSnapshot}
  onDashboard={(id) => navigate(`/portfolio/${id}/dashboard`)}
  amountVisible={amountVisible}
  formatMaskedNumber={formatMaskedNumber}
/>
```

- [ ] **Step 7: Commit**

```bash
git add frontend/src/app/PortfolioPage.tsx
git commit -m "feat: replace backfill button with snapshot toggle switch"
```

### Task 7: Verify & Rebuild

- [ ] **Step 1: Build frontend to check for type errors**

```bash
cd frontend && npm run build
```

Expected: Build succeeds with no errors.

- [ ] **Step 2: Rebuild backend container**

```bash
docker compose up -d --build backend
```

- [ ] **Step 3: Apply DB migration**

Connect to the database and run:

```bash
docker compose exec db psql -U postgres -d etf_atlas -c "ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS snapshot_enabled BOOLEAN NOT NULL DEFAULT FALSE;"
```

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git add -A && git commit -m "fix: address build issues from snapshot_enabled feature"
```
