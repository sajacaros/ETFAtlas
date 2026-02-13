# Portfolio Card Drag & Drop Reorder Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 포트폴리오 카드를 드래그 앤 드롭으로 순서 변경하고 서버에 영구 저장한다.

**Architecture:** DB에 `display_order` 컬럼 추가, 목록 조회 시 정렬 적용, 일괄 순서 변경 API 추가. 프론트엔드에서 `@dnd-kit`으로 드래그 구현, 드래그 완료 시 API 호출.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, React 18, @dnd-kit/core + sortable + utilities, TailwindCSS

---

### Task 1: DB 스키마 + SQLAlchemy 모델에 display_order 추가

**Files:**
- Modify: `docker/db/init/01_extensions.sql:80-88`
- Modify: `backend/app/models/portfolio.py:7-16`

**Step 1: SQL 스키마에 display_order 컬럼 추가**

`docker/db/init/01_extensions.sql:80-88`의 portfolios 테이블 정의를 수정:

```sql
CREATE TABLE IF NOT EXISTS portfolios (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL DEFAULT 'My Portfolio',
    calculation_base VARCHAR(20) NOT NULL DEFAULT 'CURRENT_TOTAL',
    target_total_amount DECIMAL(15, 2),
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Step 2: 실행 중인 DB에 컬럼 추가 (docker exec)**

```bash
docker exec -i etf-atlas-db-1 psql -U postgres -d etf_atlas -c "ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS display_order INTEGER NOT NULL DEFAULT 0;"
```

**Step 3: SQLAlchemy 모델에 display_order 필드 추가**

`backend/app/models/portfolio.py:10`과 `11` 사이에 추가:

```python
class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False, default="My Portfolio")
    calculation_base = Column(String(20), nullable=False, default="CURRENT_TOTAL")
    target_total_amount = Column(Numeric(15, 2), nullable=True)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Step 4: 커밋**

```bash
git add docker/db/init/01_extensions.sql backend/app/models/portfolio.py
git commit -m "feat: portfolios 테이블에 display_order 컬럼 추가"
```

---

### Task 2: 백엔드 API — 목록 정렬 + reorder 엔드포인트

**Files:**
- Modify: `backend/app/schemas/portfolio.py:1-17`
- Modify: `backend/app/routers/portfolio.py:10-18,40-45`

**Step 1: Pydantic 스키마 추가**

`backend/app/schemas/portfolio.py` 상단에 `PortfolioReorderItem`과 `PortfolioReorderRequest` 추가 (`PortfolioUpdate` 클래스 뒤에):

```python
class PortfolioReorderItem(BaseModel):
    id: int
    display_order: int


class PortfolioReorderRequest(BaseModel):
    orders: list[PortfolioReorderItem]
```

**Step 2: 목록 조회에 order_by 적용**

`backend/app/routers/portfolio.py:45`에서:

```python
# Before:
portfolios = db.query(Portfolio).filter(Portfolio.user_id == user_id).all()

# After:
portfolios = db.query(Portfolio).filter(Portfolio.user_id == user_id).order_by(Portfolio.display_order).all()
```

**Step 3: reorder 엔드포인트 추가**

`backend/app/routers/portfolio.py`의 `create_portfolio` 함수(line 109) 바로 위에 추가. 반드시 `/{portfolio_id}` 경로들보다 **앞에** 등록:

```python
@router.put("/reorder")
async def reorder_portfolios(
    request: PortfolioReorderRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolio_ids = [item.id for item in request.orders]
    portfolios = db.query(Portfolio).filter(
        Portfolio.id.in_(portfolio_ids),
        Portfolio.user_id == user_id,
    ).all()
    portfolio_map = {p.id: p for p in portfolios}
    for item in request.orders:
        if item.id in portfolio_map:
            portfolio_map[item.id].display_order = item.display_order
    db.commit()
    return {"ok": True}
```

스키마 import에 `PortfolioReorderRequest` 추가:

```python
from ..schemas.portfolio import (
    PortfolioCreate, PortfolioUpdate, PortfolioResponse,
    PortfolioReorderRequest,
    ...
)
```

**Step 4: 새 포트폴리오 생성 시 display_order 자동 설정**

`backend/app/routers/portfolio.py`의 `create_portfolio` 함수 내에서 max display_order + 1 할당:

```python
@router.post("/", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    request: PortfolioCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    max_order = db.query(func.max(Portfolio.display_order)).filter(
        Portfolio.user_id == user_id
    ).scalar() or 0
    portfolio = Portfolio(
        user_id=user_id,
        name=request.name,
        calculation_base=request.calculation_base,
        target_total_amount=request.target_total_amount,
        display_order=max_order + 1,
    )
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio
```

**Step 5: 백엔드 컨테이너 리빌드 + 동작 확인**

```bash
docker compose up -d --build backend
```

**Step 6: 커밋**

```bash
git add backend/app/schemas/portfolio.py backend/app/routers/portfolio.py
git commit -m "feat: 포트폴리오 목록 정렬 및 reorder API 추가"
```

---

### Task 3: 프론트엔드 — @dnd-kit 설치 + API 클라이언트

**Files:**
- Modify: `frontend/package.json` (via npm install)
- Modify: `frontend/src/lib/api.ts:111-173`
- Modify: `frontend/src/types/api.ts:63-74`

**Step 1: @dnd-kit 패키지 설치**

```bash
cd frontend && npm install @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities
```

**Step 2: Portfolio 타입에 display_order 추가**

`frontend/src/types/api.ts`의 Portfolio 인터페이스에 필드 추가:

```typescript
export interface Portfolio {
  id: number
  name: string
  calculation_base: CalculationBase
  target_total_amount: number | null
  display_order: number
  current_value: number | null
  current_value_date: string | null
  daily_change_amount: number | null
  daily_change_rate: number | null
  invested_amount: number | null
  investment_return_rate: number | null
}
```

**Step 3: portfolioApi에 reorder 함수 추가**

`frontend/src/lib/api.ts`의 `portfolioApi` 객체 내, `delete` 메서드 뒤에 추가:

```typescript
reorder: async (orders: { id: number; display_order: number }[]) => {
  await api.put('/portfolios/reorder', { orders })
},
```

**Step 4: 커밋**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/types/api.ts frontend/src/lib/api.ts
git commit -m "feat: @dnd-kit 설치 및 reorder API 클라이언트 추가"
```

---

### Task 4: 프론트엔드 — PortfolioPage에 드래그 앤 드롭 적용

**Files:**
- Modify: `frontend/src/app/PortfolioPage.tsx:1-23,34,645-733`

**Step 1: import 추가**

`PortfolioPage.tsx` 상단에 dnd-kit 관련 import 추가:

```typescript
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  rectSortingStrategy,
  useSortable,
  arrayMove,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical } from 'lucide-react'
```

**Step 2: SortablePortfolioCard 컴포넌트 추출**

PortfolioPage 컴포넌트 바로 위에 새 컴포넌트 정의. 기존 카드 JSX(line 647-731)를 그대로 이동하되, `useSortable` 훅으로 감싸기:

```tsx
function SortablePortfolioCard({
  portfolio: p,
  onSelect,
  onDelete,
  onBackfill,
  backfillLoading,
  onDashboard,
  amountVisible,
  formatMaskedNumber: fmn,
}: {
  portfolio: Portfolio
  onSelect: (id: number) => void
  onDelete: (id: number) => void
  onBackfill: (id: number) => void
  backfillLoading: number | null
  onDashboard: (id: number) => void
  amountVisible: boolean
  formatMaskedNumber: (v: number, visible: boolean) => string
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: p.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <Card
      ref={setNodeRef}
      style={style}
      className="cursor-pointer hover:shadow-md transition-shadow"
      onClick={() => onSelect(p.id)}
    >
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <div className="flex items-center gap-1">
          <button
            className="cursor-grab active:cursor-grabbing touch-none p-1 -ml-1 text-muted-foreground hover:text-foreground"
            {...attributes}
            {...listeners}
            onClick={(e) => e.stopPropagation()}
          >
            <GripVertical className="w-4 h-4" />
          </button>
          <CardTitle className="text-lg">{p.name}</CardTitle>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive hover:text-destructive"
          onClick={(e) => {
            e.stopPropagation()
            onDelete(p.id)
          }}
        >
          <Trash2 className="w-4 h-4" />
        </Button>
      </CardHeader>
      <CardContent>
        {/* 기존 CardContent 내용 그대로 — p, amountVisible, fmn, backfillLoading, onBackfill, onDashboard 사용 */}
        <div>
          {p.current_value != null && p.current_value_date ? (
            <>
              <p className="text-lg font-bold font-mono">
                <span className="text-sm font-normal text-muted-foreground">
                  {p.current_value_date.slice(2).replace(/-/g, '/')}:
                </span>{' '}
                {fmn(p.current_value, amountVisible)}{amountVisible && '원'}
              </p>
              <p className={`text-sm font-mono ${(p.daily_change_rate ?? 0) >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
                {amountVisible ? (
                  <>
                    <span className="font-normal text-muted-foreground">전일대비</span>{' '}
                    {(p.daily_change_amount ?? 0) >= 0 ? '+' : ''}{formatNumber(p.daily_change_amount ?? 0)}원
                    ({(p.daily_change_rate ?? 0) >= 0 ? '+' : ''}{(p.daily_change_rate ?? 0).toFixed(2)}%)
                  </>
                ) : (
                  '••••••'
                )}
              </p>
              {p.investment_return_rate != null && (
                <p className={`text-xs font-mono mt-1 ${p.investment_return_rate >= 0 ? 'text-red-500' : 'text-blue-500'}`}>
                  {amountVisible ? (
                    <>
                      투자금액 {formatNumber(p.invested_amount ?? 0)}원 / 수익률 {p.investment_return_rate >= 0 ? '+' : ''}{p.investment_return_rate.toFixed(2)}%
                    </>
                  ) : (
                    '투자수익률 ••••••'
                  )}
                </p>
              )}
            </>
          ) : (
            <div>
              <p className="text-sm text-muted-foreground">평가금액 없음</p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                disabled={backfillLoading === p.id}
                onClick={(e) => {
                  e.stopPropagation()
                  onBackfill(p.id)
                }}
              >
                <RefreshCw className={`w-3 h-3 mr-1 ${backfillLoading === p.id ? 'animate-spin' : ''}`} />
                {backfillLoading === p.id ? '생성 중...' : '스냅샷 생성'}
              </Button>
            </div>
          )}
        </div>
        <Button
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={(e) => {
            e.stopPropagation()
            onDashboard(p.id)
          }}
        >
          <BarChart3 className="w-4 h-4 mr-1" />
          대시보드
        </Button>
      </CardContent>
    </Card>
  )
}
```

**Step 3: PortfolioPage에 DndContext + SortableContext 적용**

컴포넌트 내에 sensor와 handleDragEnd 추가:

```tsx
// PortfolioPage 내부, 기존 state 선언 아래에 추가:
const sensors = useSensors(
  useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
)

const handleDragEnd = async (event: DragEndEvent) => {
  const { active, over } = event
  if (!over || active.id === over.id) return

  const oldIndex = portfolios.findIndex((p) => p.id === active.id)
  const newIndex = portfolios.findIndex((p) => p.id === over.id)
  const reordered = arrayMove(portfolios, oldIndex, newIndex)
  setPortfolios(reordered)

  const orders = reordered.map((p, i) => ({ id: p.id, display_order: i }))
  try {
    await portfolioApi.reorder(orders)
  } catch {
    // 실패 시 원복
    setPortfolios(portfolios)
    toast({ title: '순서 변경 실패', variant: 'destructive' })
  }
}
```

기존 카드 그리드(line 645-733)를 DndContext로 감싸기:

```tsx
<DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
  <SortableContext items={portfolios.map((p) => p.id)} strategy={rectSortingStrategy}>
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {portfolios.map((p) => (
        <SortablePortfolioCard
          key={p.id}
          portfolio={p}
          onSelect={selectPortfolio}
          onDelete={handleDelete}
          onBackfill={handleBackfill}
          backfillLoading={backfillLoading}
          onDashboard={(id) => navigate(`/portfolio/${id}/dashboard`)}
          amountVisible={amountVisible}
          formatMaskedNumber={formatMaskedNumber}
        />
      ))}
    </div>
  </SortableContext>
</DndContext>
```

**Step 4: 프론트엔드 컨테이너 리빌드 + 브라우저에서 동작 확인**

```bash
docker compose up -d --build frontend
```

드래그 핸들(⠿ 아이콘)이 보이는지, 드래그로 카드 순서가 바뀌는지, 새로고침 후에도 순서가 유지되는지 확인.

**Step 5: 커밋**

```bash
git add frontend/src/app/PortfolioPage.tsx
git commit -m "feat: 포트폴리오 카드 드래그&드롭 순서 변경 구현"
```
