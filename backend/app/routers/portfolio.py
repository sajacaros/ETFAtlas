import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models.portfolio import Portfolio, TargetAllocation, Holding, PortfolioSnapshot
from ..utils.jwt import get_current_user_id
from ..schemas.portfolio import (
    PortfolioCreate, PortfolioUpdate, PortfolioResponse,
    PortfolioReorderRequest,
    TargetAllocationCreate, TargetAllocationUpdate, TargetAllocationResponse,
    HoldingCreate, HoldingUpdate, HoldingResponse,
    CalculationResponse, CalculationRowResponse,
    PortfolioDetailResponse,
    DashboardResponse, DashboardSummary, DashboardSummaryItem, ChartDataPoint,
    TotalHoldingsResponse, TotalHoldingItem,
    BackfillSnapshotResponse,
    RefreshSnapshotResponse,
    RefreshAllSnapshotsResponse,
    PortfolioBatchUpdate,
    ShareToggleRequest, ShareToggleResponse,
)
from ..domain.portfolio_calculation import (
    calculate_portfolio, TargetInput, HoldingInput,
)
from ..services.price_service import PriceService

router = APIRouter()


def _get_portfolio_or_404(db: Session, portfolio_id: int, user_id: int) -> Portfolio:
    portfolio = db.query(Portfolio).filter(
        Portfolio.id == portfolio_id,
        Portfolio.user_id == user_id
    ).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


# --- Portfolio CRUD ---

@router.get("/", response_model=List[PortfolioResponse])
async def get_portfolios(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == user_id).order_by(Portfolio.display_order).all()

    # 각 포트폴리오의 투자금액 계산 (avg_price 기반)
    all_holdings = db.query(Holding).filter(
        Holding.portfolio_id.in_([p.id for p in portfolios]),
    ).all()
    invested_map: dict[int, Decimal] = {}
    cash_map: dict[int, Decimal] = {}
    has_avg_price_set: set[int] = set()
    for h in all_holdings:
        if h.ticker == 'CASH' and h.quantity:
            cash_map[h.portfolio_id] = Decimal(str(h.quantity))
        elif h.avg_price is not None and h.quantity:
            has_avg_price_set.add(h.portfolio_id)
            invested_map[h.portfolio_id] = invested_map.get(h.portfolio_id, Decimal('0')) + Decimal(str(h.quantity)) * Decimal(str(h.avg_price))
    # CASH는 ETF avg_price가 하나라도 있는 포트폴리오에만 합산
    for pid in has_avg_price_set:
        if pid in cash_map:
            invested_map[pid] = invested_map.get(pid, Decimal('0')) + cash_map[pid]

    # 각 포트폴리오의 최신 스냅샷에서 current_value 가져오기
    latest_sub = db.query(
        PortfolioSnapshot.portfolio_id,
        func.max(PortfolioSnapshot.date).label('max_date'),
    ).filter(
        PortfolioSnapshot.portfolio_id.in_([p.id for p in portfolios]),
    ).group_by(PortfolioSnapshot.portfolio_id).subquery()

    latest_values = db.query(
        PortfolioSnapshot.portfolio_id,
        PortfolioSnapshot.total_value,
        PortfolioSnapshot.date,
        PortfolioSnapshot.change_amount,
        PortfolioSnapshot.change_rate,
        PortfolioSnapshot.updated_at,
    ).join(
        latest_sub,
        (PortfolioSnapshot.portfolio_id == latest_sub.c.portfolio_id) &
        (PortfolioSnapshot.date == latest_sub.c.max_date),
    ).all()

    value_map = {row.portfolio_id: row for row in latest_values}

    result = []
    for p in portfolios:
        cur_val = Decimal(str(value_map[p.id].total_value)) if p.id in value_map else None
        inv_amt = invested_map.get(p.id)
        inv_rate = None
        if inv_amt and cur_val and inv_amt > 0:
            inv_rate = round(float((cur_val - inv_amt) / inv_amt * 100), 2)
        result.append(PortfolioResponse(
            id=p.id,
            name=p.name,
            calculation_base=p.calculation_base,
            target_total_amount=p.target_total_amount,
            current_value=cur_val,
            current_value_date=value_map[p.id].date.isoformat() if p.id in value_map else None,
            current_value_updated_at=value_map[p.id].updated_at.isoformat() if p.id in value_map and value_map[p.id].updated_at else None,
            daily_change_amount=value_map[p.id].change_amount if p.id in value_map else None,
            daily_change_rate=value_map[p.id].change_rate if p.id in value_map else None,
            invested_amount=inv_amt,
            investment_return_rate=inv_rate,
        ))
    return result


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


@router.put("/{portfolio_id}", response_model=PortfolioResponse)
async def update_portfolio(
    portfolio_id: int,
    request: PortfolioUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    if request.name is not None:
        portfolio.name = request.name
    if request.calculation_base is not None:
        portfolio.calculation_base = request.calculation_base
    if request.target_total_amount is not None:
        portfolio.target_total_amount = request.target_total_amount
    db.commit()
    db.refresh(portfolio)
    return portfolio


@router.put("/{portfolio_id}/batch", response_model=PortfolioDetailResponse)
async def batch_update_portfolio(
    portfolio_id: int,
    request: PortfolioBatchUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)

    # Update settings
    if request.name is not None:
        portfolio.name = request.name
    if request.calculation_base is not None:
        portfolio.calculation_base = request.calculation_base
    if request.target_total_amount is not None:
        portfolio.target_total_amount = request.target_total_amount

    # Sync targets: desired state approach
    existing_targets = db.query(TargetAllocation).filter(
        TargetAllocation.portfolio_id == portfolio.id
    ).all()
    existing_target_map = {t.ticker: t for t in existing_targets}
    new_target_tickers = {t.ticker for t in request.targets}

    for t in existing_targets:
        if t.ticker not in new_target_tickers:
            db.delete(t)

    for t in request.targets:
        if t.ticker in existing_target_map:
            existing_target_map[t.ticker].target_weight = t.target_weight
        else:
            db.add(TargetAllocation(
                portfolio_id=portfolio.id,
                ticker=t.ticker,
                target_weight=t.target_weight,
            ))

    # Sync holdings: desired state approach
    existing_holdings = db.query(Holding).filter(
        Holding.portfolio_id == portfolio.id
    ).all()
    existing_holding_map = {h.ticker: h for h in existing_holdings}
    new_holding_tickers = {h.ticker for h in request.holdings}

    for h in existing_holdings:
        if h.ticker not in new_holding_tickers:
            db.delete(h)

    for h in request.holdings:
        if h.ticker in existing_holding_map:
            existing_holding_map[h.ticker].quantity = h.quantity
            if h.avg_price is not None:
                existing_holding_map[h.ticker].avg_price = h.avg_price
        else:
            db.add(Holding(
                portfolio_id=portfolio.id,
                ticker=h.ticker,
                quantity=h.quantity,
                avg_price=h.avg_price,
            ))

    db.commit()
    db.refresh(portfolio)
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


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_portfolio(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    db.delete(portfolio)
    db.commit()


# --- Dashboard ---

def _build_dashboard_response(snapshots: list) -> DashboardResponse:
    """스냅샷 리스트로부터 대시보드 응답 생성.
    snapshots: list of objects with .date and .total_value attributes (sorted by date asc)
    """
    if not snapshots:
        return DashboardResponse(
            summary=DashboardSummary(
                current_value=Decimal('0'),
                cumulative=DashboardSummaryItem(amount=Decimal('0'), rate=0.0),
            ),
            chart_data=[],
        )

    first = snapshots[0]
    last = snapshots[-1]
    first_value = Decimal(str(first.total_value))
    current_value = Decimal(str(last.total_value))

    # cumulative
    cum_amount = current_value - first_value
    cum_rate = float(cum_amount / first_value * 100) if first_value else 0.0

    # daily: last vs second-to-last
    daily = None
    if len(snapshots) >= 2:
        prev = snapshots[-2]
        prev_val = Decimal(str(prev.total_value))
        if prev_val:
            d_amount = current_value - prev_val
            daily = DashboardSummaryItem(amount=d_amount, rate=float(d_amount / prev_val * 100))

    # monthly: find last snapshot of previous month
    monthly = None
    last_date = last.date
    for s in reversed(snapshots):
        if s.date.year < last_date.year or (s.date.year == last_date.year and s.date.month < last_date.month):
            ref_val = Decimal(str(s.total_value))
            if ref_val:
                m_amount = current_value - ref_val
                monthly = DashboardSummaryItem(amount=m_amount, rate=float(m_amount / ref_val * 100))
            break

    # yearly: find last snapshot of previous year
    yearly = None
    for s in reversed(snapshots):
        if s.date.year < last_date.year:
            ref_val = Decimal(str(s.total_value))
            if ref_val:
                y_amount = current_value - ref_val
                yearly = DashboardSummaryItem(amount=y_amount, rate=float(y_amount / ref_val * 100))
            break

    # ytd: find last snapshot of Dec of previous year (same as yearly reference)
    ytd = yearly

    # chart_data
    chart_data = []
    for s in snapshots:
        s_val = Decimal(str(s.total_value))
        c_rate = float((s_val - first_value) / first_value * 100) if first_value else 0.0
        chart_data.append(ChartDataPoint(
            date=s.date.isoformat(),
            total_value=s_val,
            cumulative_rate=round(c_rate, 2),
        ))

    last_updated_at = getattr(last, 'updated_at', None) if snapshots else None

    return DashboardResponse(
        summary=DashboardSummary(
            current_value=current_value,
            cumulative=DashboardSummaryItem(amount=cum_amount, rate=round(cum_rate, 2)),
            daily=daily,
            monthly=monthly,
            yearly=yearly,
            ytd=ytd,
            snapshot_date=last.date.isoformat() if snapshots else None,
            updated_at=last_updated_at.isoformat() if last_updated_at else None,
        ),
        chart_data=chart_data,
    )


@router.post("/refresh-snapshots", response_model=RefreshAllSnapshotsResponse)
async def refresh_all_snapshots(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == user_id).all()
    refreshed = 0
    skipped = 0
    for p in portfolios:
        result = _refresh_snapshot(db, p.id)
        if result is not None:
            refreshed += 1
        else:
            skipped += 1
    return RefreshAllSnapshotsResponse(refreshed=refreshed, skipped=skipped)


@router.get("/dashboard/total", response_model=DashboardResponse)
async def get_total_dashboard(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolio_ids = [p.id for p in db.query(Portfolio).filter(Portfolio.user_id == user_id).all()]
    if not portfolio_ids:
        return _build_dashboard_response([])

    # Fetch all snapshots for user's portfolios (encrypted columns need app-level aggregation)
    all_snapshots = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.portfolio_id.in_(portfolio_ids),
    ).order_by(PortfolioSnapshot.date.asc()).all()

    # Group by date and sum total_value in Python
    date_agg: dict = {}
    for s in all_snapshots:
        key = s.date
        if key not in date_agg:
            date_agg[key] = {'total_value': Decimal('0'), 'updated_at': s.updated_at}
        date_agg[key]['total_value'] += Decimal(str(s.total_value))
        if s.updated_at and (date_agg[key]['updated_at'] is None or s.updated_at > date_agg[key]['updated_at']):
            date_agg[key]['updated_at'] = s.updated_at

    class SnapshotRow:
        def __init__(self, d, tv, ua=None):
            self.date = d
            self.total_value = tv
            self.updated_at = ua

    snapshots = [
        SnapshotRow(d, agg['total_value'], agg['updated_at'])
        for d, agg in sorted(date_agg.items())
    ]
    return _build_dashboard_response(snapshots)


@router.get("/dashboard/total/holdings", response_model=TotalHoldingsResponse)
async def get_total_holdings(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == user_id).all()
    if not portfolios:
        return TotalHoldingsResponse(holdings=[], total_value=Decimal('0'))

    # 모든 포트폴리오의 보유종목을 ticker별로 합산
    all_holdings = db.query(Holding).filter(
        Holding.portfolio_id.in_([p.id for p in portfolios]),
    ).all()

    ticker_qty: dict[str, Decimal] = {}
    for h in all_holdings:
        ticker_qty[h.ticker] = ticker_qty.get(h.ticker, Decimal('0')) + Decimal(str(h.quantity))

    if not ticker_qty:
        return TotalHoldingsResponse(holdings=[], total_value=Decimal('0'))

    all_tickers = list(ticker_qty.keys())
    price_service = PriceService(db)
    prices = price_service.get_prices(all_tickers)
    etf_names = price_service.get_etf_names(all_tickers)

    # 평가금액 계산
    items: list[tuple[str, Decimal]] = []
    grand_total = Decimal('0')
    for ticker, qty in ticker_qty.items():
        if ticker == 'CASH':
            value = qty
        else:
            price = prices.get(ticker, Decimal('0'))
            value = qty * price
        items.append((ticker, value))
        grand_total += value

    # 비중 계산 및 정렬
    holdings_out = []
    for ticker, value in items:
        qty = ticker_qty[ticker]
        if ticker == 'CASH':
            price = Decimal('1')
        else:
            price = prices.get(ticker, Decimal('0'))
        weight = float(value / grand_total * 100) if grand_total else 0.0
        holdings_out.append(TotalHoldingItem(
            ticker=ticker,
            name=etf_names.get(ticker, ticker),
            quantity=qty,
            current_price=price,
            value=value,
            weight=round(weight, 2),
        ))

    holdings_out.sort(key=lambda x: x.weight, reverse=True)

    return TotalHoldingsResponse(holdings=holdings_out, total_value=grand_total)


@router.post("/{portfolio_id}/refresh-snapshot", response_model=RefreshSnapshotResponse)
async def refresh_snapshot(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    result = _refresh_snapshot(db, portfolio.id)
    if result is None:
        raise HTTPException(status_code=400, detail="가격 데이터가 없습니다. DAG 실행 후 다시 시도하세요.")
    return RefreshSnapshotResponse(**result)


@router.get("/{portfolio_id}/dashboard", response_model=DashboardResponse)
async def get_portfolio_dashboard(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    snapshots = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.portfolio_id == portfolio_id,
    ).order_by(PortfolioSnapshot.date.asc()).all()

    response = _build_dashboard_response(snapshots)

    # 투자금액 대비 수익률 계산
    holdings = db.query(Holding).filter(Holding.portfolio_id == portfolio.id).all()
    invested_amount = Decimal('0')
    cash_amount = Decimal('0')
    has_avg_price = False
    for h in holdings:
        if h.ticker == 'CASH' and h.quantity:
            cash_amount = Decimal(str(h.quantity))
        elif h.avg_price is not None and h.quantity:
            invested_amount += Decimal(str(h.quantity)) * Decimal(str(h.avg_price))
            has_avg_price = True
    if has_avg_price:
        invested_amount += cash_amount

    if has_avg_price and invested_amount > 0:
        response.summary.invested_amount = invested_amount
        current_value = response.summary.current_value
        return_amount = current_value - invested_amount
        return_rate = float(return_amount / invested_amount * 100)
        response.summary.investment_return = DashboardSummaryItem(
            amount=return_amount, rate=round(return_rate, 2),
        )

    return response


# --- Backfill Snapshots ---

def _get_latest_trading_date(db: Session) -> date | None:
    """AGE Price 노드에서 최신 거래일을 조회한다."""
    from ..services.graph_service import GraphService
    graph_service = GraphService(db)
    query = """
    MATCH (e:ETF)-[:HAS_PRICE]->(p:Price)
    RETURN {date: p.date}
    ORDER BY p.date DESC
    LIMIT 1
    """
    rows = graph_service.execute_cypher(query)
    if rows:
        parsed = GraphService.parse_agtype(rows[0]["result"])
        date_str = parsed.get("date")
        if date_str:
            from datetime import date as dt_date
            return dt_date.fromisoformat(date_str)
    return None


def _fetch_prices_by_yfinance(tickers: list[str], trading_date: date) -> dict[str, Decimal]:
    """yfinance로 특정 거래일의 종가를 조회한다."""
    import yfinance as yf
    from datetime import timedelta

    prices: dict[str, Decimal] = {}
    # yfinance history는 end를 exclusive로 처리하므로 +1일
    start = trading_date.isoformat()
    end = (trading_date + timedelta(days=1)).isoformat()

    for ticker in tickers:
        try:
            yf_ticker = f"{ticker}.KS"
            hist = yf.Ticker(yf_ticker).history(start=start, end=end)
            if not hist.empty and hist['Close'].iloc[0] > 0:
                prices[ticker] = Decimal(str(int(hist['Close'].iloc[0])))
        except Exception:
            pass

    return prices


@router.post("/{portfolio_id}/backfill-snapshots", response_model=BackfillSnapshotResponse)
async def backfill_snapshots(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)

    # 기존 스냅샷 존재 시 409
    existing = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.portfolio_id == portfolio_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Snapshots already exist for this portfolio")

    # 보유 종목 조회
    holdings = db.query(Holding).filter(Holding.portfolio_id == portfolio.id).all()
    if not holdings:
        raise HTTPException(status_code=400, detail="No holdings in this portfolio")

    # 최신 거래일 조회
    trading_date = _get_latest_trading_date(db)
    if not trading_date:
        raise HTTPException(status_code=400, detail="No trading date found")

    # ETF 종목의 종가를 yfinance로 조회
    tickers = [h.ticker for h in holdings if h.ticker != 'CASH']
    prices = _fetch_prices_by_yfinance(tickers, trading_date) if tickers else {}

    missing = [t for t in tickers if t not in prices]
    if missing:
        raise HTTPException(status_code=400, detail=f"Price not found for: {', '.join(missing)}")

    # 평가금액 계산
    total_value = Decimal('0')
    for h in holdings:
        if h.ticker == 'CASH':
            total_value += Decimal(str(h.quantity))
        else:
            total_value += Decimal(str(h.quantity)) * prices[h.ticker]

    snapshot = PortfolioSnapshot(
        portfolio_id=portfolio.id,
        date=trading_date,
        total_value=total_value,
    )
    db.add(snapshot)
    db.commit()

    return BackfillSnapshotResponse(created=1)


# --- Target Allocations ---

@router.post("/{portfolio_id}/targets", response_model=TargetAllocationResponse, status_code=status.HTTP_201_CREATED)
async def add_target(
    portfolio_id: int,
    request: TargetAllocationCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    existing = db.query(TargetAllocation).filter(
        TargetAllocation.portfolio_id == portfolio.id,
        TargetAllocation.ticker == request.ticker
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Target allocation already exists for this ticker")

    allocation = TargetAllocation(
        portfolio_id=portfolio.id,
        ticker=request.ticker,
        target_weight=request.target_weight,
    )
    db.add(allocation)
    db.commit()
    db.refresh(allocation)
    return allocation


@router.put("/{portfolio_id}/targets/{target_id}", response_model=TargetAllocationResponse)
async def update_target(
    portfolio_id: int,
    target_id: int,
    request: TargetAllocationUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    allocation = db.query(TargetAllocation).filter(
        TargetAllocation.id == target_id,
        TargetAllocation.portfolio_id == portfolio.id
    ).first()
    if not allocation:
        raise HTTPException(status_code=404, detail="Target allocation not found")

    allocation.target_weight = request.target_weight
    db.commit()
    db.refresh(allocation)
    return allocation


@router.delete("/{portfolio_id}/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_target(
    portfolio_id: int,
    target_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    allocation = db.query(TargetAllocation).filter(
        TargetAllocation.id == target_id,
        TargetAllocation.portfolio_id == portfolio.id
    ).first()
    if not allocation:
        raise HTTPException(status_code=404, detail="Target allocation not found")

    db.delete(allocation)
    db.commit()


# --- Snapshot Refresh ---

def _refresh_snapshot(db: Session, portfolio_id: int) -> dict | None:
    """최근 거래일 기준으로 스냅샷을 갱신(UPSERT)한다.

    Returns:
        dict with date, total_value, change_amount, change_rate or None if impossible.
    """
    price_service = PriceService(db)
    snapshot_date = price_service.get_latest_price_date()
    if not snapshot_date:
        return None

    holdings = db.query(Holding).filter(Holding.portfolio_id == portfolio_id).all()
    if not holdings:
        return None

    tickers = [h.ticker for h in holdings if h.ticker != 'CASH']
    prices = price_service.get_prices(tickers) if tickers else {}

    total_value = Decimal('0')
    for h in holdings:
        if h.ticker == 'CASH':
            total_value += Decimal(str(h.quantity))
        elif h.ticker in prices:
            total_value += Decimal(str(h.quantity)) * prices[h.ticker]

    prev = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.portfolio_id == portfolio_id,
        PortfolioSnapshot.date < snapshot_date,
    ).order_by(PortfolioSnapshot.date.desc()).first()

    prev_value = Decimal(str(prev.total_value)) if prev else None
    change_amount = total_value - prev_value if prev_value is not None else None
    change_rate = float(change_amount / prev_value * 100) if prev_value and prev_value != 0 else None

    existing = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.portfolio_id == portfolio_id,
        PortfolioSnapshot.date == snapshot_date,
    ).first()

    now = datetime.utcnow()
    if existing:
        existing.total_value = total_value
        existing.prev_value = prev_value
        existing.change_amount = change_amount
        existing.change_rate = change_rate
        existing.updated_at = now
    else:
        db.add(PortfolioSnapshot(
            portfolio_id=portfolio_id, date=snapshot_date,
            total_value=total_value, prev_value=prev_value,
            change_amount=change_amount, change_rate=change_rate,
            updated_at=now,
        ))
    db.commit()

    return {
        "date": snapshot_date.isoformat(),
        "total_value": total_value,
        "change_amount": change_amount,
        "change_rate": change_rate,
    }


# --- Holdings ---

@router.post("/{portfolio_id}/holdings", response_model=HoldingResponse, status_code=status.HTTP_201_CREATED)
async def add_holding(
    portfolio_id: int,
    request: HoldingCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    existing = db.query(Holding).filter(
        Holding.portfolio_id == portfolio.id,
        Holding.ticker == request.ticker
    ).first()
    if existing:
        existing.quantity = request.quantity
        if request.avg_price is not None:
            existing.avg_price = request.avg_price
        db.commit()
        db.refresh(existing)
        return existing

    holding = Holding(
        portfolio_id=portfolio.id,
        ticker=request.ticker,
        quantity=request.quantity,
        avg_price=request.avg_price,
    )
    db.add(holding)
    db.commit()
    db.refresh(holding)
    return holding


@router.put("/{portfolio_id}/holdings/{holding_id}", response_model=HoldingResponse)
async def update_holding(
    portfolio_id: int,
    holding_id: int,
    request: HoldingUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    holding = db.query(Holding).filter(
        Holding.id == holding_id,
        Holding.portfolio_id == portfolio.id
    ).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    if request.quantity is not None:
        holding.quantity = request.quantity
    if request.avg_price is not None:
        holding.avg_price = request.avg_price
    db.commit()
    db.refresh(holding)
    return holding


@router.delete("/{portfolio_id}/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(
    portfolio_id: int,
    holding_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    holding = db.query(Holding).filter(
        Holding.id == holding_id,
        Holding.portfolio_id == portfolio.id
    ).first()
    if not holding:
        raise HTTPException(status_code=404, detail="Holding not found")

    db.delete(holding)
    db.commit()


# --- Calculation ---

@router.get("/{portfolio_id}/calculate", response_model=CalculationResponse)
async def calculate(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)

    # Gather data
    target_allocations = db.query(TargetAllocation).filter(
        TargetAllocation.portfolio_id == portfolio.id
    ).all()
    holdings = db.query(Holding).filter(
        Holding.portfolio_id == portfolio.id
    ).all()

    # Build inputs
    targets = [
        TargetInput(ticker=ta.ticker, target_weight=Decimal(str(ta.target_weight)))
        for ta in target_allocations
    ]
    holding_inputs = [
        HoldingInput(
            ticker=h.ticker,
            quantity=Decimal(str(h.quantity)),
            avg_price=Decimal(str(h.avg_price)) if h.avg_price is not None else None,
        )
        for h in holdings
    ]

    # All tickers
    all_tickers = list(set(
        [ta.ticker for ta in target_allocations] +
        [h.ticker for h in holdings]
    ))

    # Get prices and names
    price_service = PriceService(db)
    prices = price_service.get_prices(all_tickers)
    prev_prices = price_service.get_prev_prices(all_tickers)
    etf_names = price_service.get_etf_names(all_tickers)

    # Calculate
    result = calculate_portfolio(
        targets=targets,
        holdings=holding_inputs,
        prices=prices,
        etf_names=etf_names,
        calculation_base=portfolio.calculation_base,
        target_total_amount=Decimal(str(portfolio.target_total_amount)) if portfolio.target_total_amount else None,
        prev_prices=prev_prices,
    )

    # Convert to response
    return CalculationResponse(
        rows=[
            CalculationRowResponse(
                ticker=row.ticker,
                name=row.name,
                target_weight=row.target_weight,
                current_price=row.current_price,
                target_amount=row.target_amount,
                target_quantity=row.target_quantity,
                holding_quantity=row.holding_quantity,
                holding_amount=row.holding_amount,
                required_quantity=row.required_quantity,
                adjustment_amount=row.adjustment_amount,
                status=row.status,
                avg_price=row.avg_price,
                profit_loss_rate=row.profit_loss_rate,
                profit_loss_amount=row.profit_loss_amount,
                price_change_rate=row.price_change_rate,
            )
            for row in result.rows
        ],
        base_amount=result.base_amount,
        total_weight=result.total_weight,
        total_holding_amount=result.total_holding_amount,
        total_adjustment_amount=result.total_adjustment_amount,
        total_profit_loss_amount=result.total_profit_loss_amount,
        weight_warning=result.weight_warning,
    )
