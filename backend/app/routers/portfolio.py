from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from decimal import Decimal
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models.portfolio import Portfolio, TargetAllocation, Holding, PortfolioSnapshot
from ..models.etf import ETFPrice
from ..utils.jwt import get_current_user_id
from ..schemas.portfolio import (
    PortfolioCreate, PortfolioUpdate, PortfolioResponse,
    TargetAllocationCreate, TargetAllocationUpdate, TargetAllocationResponse,
    HoldingCreate, HoldingUpdate, HoldingResponse,
    CalculationResponse, CalculationRowResponse,
    PortfolioDetailResponse,
    DashboardResponse, DashboardSummary, DashboardSummaryItem, ChartDataPoint,
    TotalHoldingsResponse, TotalHoldingItem,
    BackfillSnapshotResponse,
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
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == user_id).all()

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
    ).join(
        latest_sub,
        (PortfolioSnapshot.portfolio_id == latest_sub.c.portfolio_id) &
        (PortfolioSnapshot.date == latest_sub.c.max_date),
    ).all()

    value_map = {row.portfolio_id: row for row in latest_values}

    return [
        PortfolioResponse(
            id=p.id,
            name=p.name,
            calculation_base=p.calculation_base,
            target_total_amount=p.target_total_amount,
            current_value=value_map[p.id].total_value if p.id in value_map else None,
            current_value_date=value_map[p.id].date.isoformat() if p.id in value_map else None,
            daily_change_amount=value_map[p.id].change_amount if p.id in value_map else None,
            daily_change_rate=value_map[p.id].change_rate if p.id in value_map else None,
        )
        for p in portfolios
    ]


@router.post("/", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
async def create_portfolio(
    request: PortfolioCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = Portfolio(
        user_id=user_id,
        name=request.name,
        calculation_base=request.calculation_base,
        target_total_amount=request.target_total_amount,
    )
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


@router.get("/{portfolio_id}", response_model=PortfolioDetailResponse)
async def get_portfolio(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    return portfolio


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

    return DashboardResponse(
        summary=DashboardSummary(
            current_value=current_value,
            cumulative=DashboardSummaryItem(amount=cum_amount, rate=round(cum_rate, 2)),
            daily=daily,
            monthly=monthly,
            yearly=yearly,
            ytd=ytd,
        ),
        chart_data=chart_data,
    )


@router.get("/dashboard/total", response_model=DashboardResponse)
async def get_total_dashboard(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolio_ids = [p.id for p in db.query(Portfolio).filter(Portfolio.user_id == user_id).all()]
    if not portfolio_ids:
        return _build_dashboard_response([])

    results = db.query(
        PortfolioSnapshot.date,
        func.sum(PortfolioSnapshot.total_value).label('total_value'),
    ).filter(
        PortfolioSnapshot.portfolio_id.in_(portfolio_ids),
    ).group_by(PortfolioSnapshot.date).order_by(PortfolioSnapshot.date.asc()).all()

    # Convert Row objects to simple namespace for _build_dashboard_response
    class SnapshotRow:
        def __init__(self, d, tv):
            self.date = d
            self.total_value = tv

    snapshots = [SnapshotRow(r.date, r.total_value) for r in results]
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


@router.get("/{portfolio_id}/dashboard", response_model=DashboardResponse)
async def get_portfolio_dashboard(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _get_portfolio_or_404(db, portfolio_id, user_id)
    snapshots = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.portfolio_id == portfolio_id,
    ).order_by(PortfolioSnapshot.date.asc()).all()

    return _build_dashboard_response(snapshots)


# --- Backfill Snapshots ---

def _get_latest_trading_date(db: Session) -> date | None:
    """etf_prices 테이블에서 최신 거래일을 조회한다 (주말 제외)."""
    from sqlalchemy import extract
    row = db.query(func.max(ETFPrice.date)).filter(
        ETFPrice.close_price.isnot(None),
        ETFPrice.close_price > 0,
        extract('dow', ETFPrice.date).notin_([0, 6]),  # 일=0, 토=6
    ).scalar()
    return row


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
        db.commit()
        db.refresh(existing)
        return existing

    holding = Holding(
        portfolio_id=portfolio.id,
        ticker=request.ticker,
        quantity=request.quantity,
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

    holding.quantity = request.quantity
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
        HoldingInput(ticker=h.ticker, quantity=Decimal(str(h.quantity)))
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
    etf_names = price_service.get_etf_names(all_tickers)

    # Calculate
    result = calculate_portfolio(
        targets=targets,
        holdings=holding_inputs,
        prices=prices,
        etf_names=etf_names,
        calculation_base=portfolio.calculation_base,
        target_total_amount=Decimal(str(portfolio.target_total_amount)) if portfolio.target_total_amount else None,
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
            )
            for row in result.rows
        ],
        base_amount=result.base_amount,
        total_weight=result.total_weight,
        total_holding_amount=result.total_holding_amount,
        total_adjustment_amount=result.total_adjustment_amount,
        weight_warning=result.weight_warning,
    )
