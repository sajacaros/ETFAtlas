# Portfolio Card Drag & Drop Reorder

## Summary
포트폴리오 카드의 순서를 드래그 앤 드롭으로 변경하고 서버(DB)에 저장하여 영구 유지한다.

## Library Choice
`@dnd-kit/core` + `@dnd-kit/sortable` + `@dnd-kit/utilities`
- React 18 호환, 그리드 레이아웃 정렬 지원, 접근성 내장, 활발히 유지보수 중

## Backend Changes

### DB Schema
`portfolios` 테이블에 `display_order INTEGER DEFAULT 0` 컬럼 추가.

### SQLAlchemy Model
`Portfolio` 모델에 `display_order = Column(Integer, default=0)` 추가.

### API
- `GET /api/portfolios/` — `order_by(Portfolio.display_order)` 적용
- `PUT /api/portfolios/reorder` — body: `{"orders": [{"id": 1, "display_order": 0}, ...]}` 일괄 순서 변경

### Schema
- `PortfolioReorderItem`: `id: int, display_order: int`
- `PortfolioReorderRequest`: `orders: list[PortfolioReorderItem]`

## Frontend Changes

### Dependencies
`@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities` 설치

### PortfolioPage.tsx
1. 카드 그리드를 `DndContext` + `SortableContext` 로 감싸기
2. 각 Card를 `SortablePortfolioCard` 컴포넌트로 추출, `useSortable` 훅 적용
3. `DragOverlay`로 드래그 중 시각적 피드백 제공
4. `onDragEnd`에서 `arrayMove`로 로컬 상태 업데이트 후 reorder API 호출

### API Client
`portfolioApi.reorder(orders)` 함수 추가

## Route Ordering Note
`/reorder`는 `/{portfolio_id}` 보다 먼저 등록해야 경로 충돌 방지.
