import uuid
from fastapi import APIRouter, Depends, HTTPException, Response, status, Query
from typing import List, NamedTuple, Optional
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..database import get_db
from ..models.portfolio import Portfolio, TargetAllocation, Holding, PortfolioSnapshot, SharedPortfolio
from ..models.ticker_price import TickerPrice
from ..utils.session import get_current_user_id
from ..schemas.portfolio import (
    PortfolioCreate, PortfolioUpdate, PortfolioResponse,
    PortfolioReorderRequest,
    TargetAllocationCreate, TargetAllocationUpdate, TargetAllocationResponse,
    HoldingCreate, HoldingUpdate, HoldingResponse,
    CalculationResponse, CalculationRowResponse,
    PortfolioDetailResponse,
    DashboardResponse, DashboardSummary, DashboardSummaryItem, ChartDataPoint,
    TotalHoldingsResponse, TotalHoldingItem,
    PortfolioBatchUpdate,
    ShareCreateResponse,
    RiskAnalysisResponse, RiskChartPoint, DrawdownPoint,
)
from ..domain.portfolio_calculation import (
    CASH_TICKER, calculate_portfolio, TargetInput, HoldingInput,
)
from ..services.price_service import PriceService
from ..domain.periods import period_start
from ..domain.portfolio_metrics import (
    BASE_AMOUNT, common_dates, daily_change, invested_amount, risk_metrics, simulate,
)
from ..utils.time import iso_utc, today_kst, utcnow

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
def get_portfolios(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == user_id).order_by(Portfolio.display_order).all()

    # 각 포트폴리오의 투자금액 계산 (avg_price 기반)
    holdings_by_portfolio: dict[int, list[Holding]] = {}
    for h in db.query(Holding).filter(Holding.portfolio_id.in_([p.id for p in portfolios])):
        holdings_by_portfolio.setdefault(h.portfolio_id, []).append(h)
    invested_map = {pid: invested_amount(hs) for pid, hs in holdings_by_portfolio.items()}

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

    # ticker_prices 테이블에서 가격 최종 수집 시간 조회
    latest_price_updated = db.query(func.max(TickerPrice.updated_at)).scalar()

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
            account_types=p.account_types,
            calculation_base=p.calculation_base,
            target_total_amount=p.target_total_amount,
            snapshot_enabled=p.snapshot_enabled,
            current_value=cur_val,
            current_value_date=value_map[p.id].date.isoformat() if p.id in value_map else None,
            current_value_updated_at=latest_price_updated.isoformat() if latest_price_updated else None,
            daily_change_amount=value_map[p.id].change_amount if p.id in value_map else None,
            daily_change_rate=value_map[p.id].change_rate if p.id in value_map else None,
            invested_amount=inv_amt,
            investment_return_rate=inv_rate,
        ))
    return result


@router.put("/reorder")
def reorder_portfolios(
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
def create_portfolio(
    request: PortfolioCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    tickers = [t.ticker for t in request.targets]
    if len(set(tickers)) != len(tickers):
        raise HTTPException(status_code=400, detail="같은 종목이 두 번 들어 있습니다")
    max_order = db.query(func.max(Portfolio.display_order)).filter(
        Portfolio.user_id == user_id
    ).scalar() or 0
    targets = [TargetAllocation(ticker=t.ticker, target_weight=t.target_weight) for t in request.targets]
    # 현금은 기본으로 0% 넣어 둔다 (새 포트폴리오, 구성종목 분석에서 저장 모두)
    if not any(t.ticker.upper() == CASH_TICKER for t in request.targets):
        targets.append(TargetAllocation(ticker=CASH_TICKER, target_weight=Decimal("0")))
    portfolio = Portfolio(
        user_id=user_id,
        name=request.name,
        account_types=request.account_types,
        calculation_base=request.calculation_base,
        target_total_amount=request.target_total_amount,
        display_order=max_order + 1,
        target_allocations=targets,
    )
    db.add(portfolio)
    db.commit()
    db.refresh(portfolio)
    return portfolio


@router.post("/{portfolio_id}/duplicate", response_model=PortfolioResponse, status_code=status.HTTP_201_CREATED)
def duplicate_portfolio(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    """목표 비중·보유 종목까지 복사한 새 포트폴리오 생성. 스냅샷·공유 설정은 복사하지 않음."""
    source = _get_portfolio_or_404(db, portfolio_id, user_id)
    max_order = db.query(func.max(Portfolio.display_order)).filter(
        Portfolio.user_id == user_id
    ).scalar() or 0
    suffix = " (사본)"
    copy = Portfolio(
        user_id=user_id,
        name=source.name[:255 - len(suffix)] + suffix,
        account_types=list(source.account_types),
        calculation_base=source.calculation_base,
        target_total_amount=source.target_total_amount,
        display_order=max_order + 1,
        target_allocations=[
            TargetAllocation(ticker=t.ticker, target_weight=t.target_weight)
            for t in source.target_allocations
        ],
        holdings=[
            Holding(ticker=h.ticker, quantity=h.quantity, avg_price=h.avg_price)
            for h in source.holdings
        ],
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return copy


def _is_same_snapshot(name: str, account_types: list[str], allocations: list[dict], shared: SharedPortfolio) -> bool:
    """이름·계좌 유형·종목별 비중이 모두 같으면 같은 공유본이다. 종목 순서는 보지 않는다."""
    def weights(items: list[dict]) -> dict[str, float]:
        return {a["ticker"]: float(a["weight"]) for a in items}
    return (
        shared.name == name
        and set(shared.account_types) == set(account_types)
        and weights(shared.allocations) == weights(allocations)
    )


@router.post("/{portfolio_id}/share", response_model=ShareCreateResponse)
def share_portfolio(
    portfolio_id: int,
    response: Response,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """지금의 이름·계좌 유형·목표 비중을 스냅샷으로 공유한다. 이후 포트폴리오를 고쳐도 공유본은 그대로다.

    이 포트폴리오에서 똑같은 구성으로 공유한 것이 이미 있으면 새로 만들지 않고 그것을 돌려준다.
    """
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    if not portfolio.target_allocations:
        raise HTTPException(status_code=400, detail="목표 비중이 없는 포트폴리오는 공유할 수 없습니다")
    allocations = [
        {"ticker": t.ticker, "weight": float(t.target_weight)}
        for t in sorted(portfolio.target_allocations, key=lambda t: t.id)
    ]

    existing = db.query(SharedPortfolio).filter(
        SharedPortfolio.portfolio_id == portfolio.id,
        SharedPortfolio.user_id == user_id,
    ).order_by(SharedPortfolio.created_at.desc()).all()
    shared = next((s for s in existing if _is_same_snapshot(portfolio.name, portfolio.account_types, allocations, s)), None)
    created = shared is None
    if created:
        shared = SharedPortfolio(
            share_token=uuid.uuid4(),
            user_id=user_id,
            portfolio_id=portfolio.id,
            name=portfolio.name,
            account_types=list(portfolio.account_types),
            allocations=allocations,
        )
        db.add(shared)
        db.commit()
        response.status_code = status.HTTP_201_CREATED

    token_str = str(shared.share_token)
    return ShareCreateResponse(share_token=token_str, share_url=f"/shared/{token_str}", created=created)


@router.get("/{portfolio_id}", response_model=PortfolioDetailResponse)
def get_portfolio(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    return PortfolioDetailResponse(
        id=portfolio.id,
        name=portfolio.name,
        account_types=portfolio.account_types,
        calculation_base=portfolio.calculation_base,
        target_total_amount=portfolio.target_total_amount,
        snapshot_enabled=portfolio.snapshot_enabled,
        target_allocations=[TargetAllocationResponse.model_validate(t) for t in portfolio.target_allocations],
        holdings=[HoldingResponse.model_validate(h) for h in portfolio.holdings],
    )


def _try_create_immediate_snapshot(db: Session, portfolio: Portfolio):
    """snapshot_enabled 토글 ON 시 ticker_prices 기반으로 즉시 스냅샷 생성 시도. 커밋은 호출 측이 한다."""
    holdings = db.query(Holding).filter(Holding.portfolio_id == portfolio.id).all()
    if not holdings:
        return

    tickers = [h.ticker for h in holdings if h.ticker != CASH_TICKER]
    if not tickers:
        total_value = sum(Decimal(str(h.quantity)) for h in holdings if h.ticker == CASH_TICKER)
    else:
        latest_date = db.query(func.max(TickerPrice.date)).scalar()
        if not latest_date:
            return

        price_rows = db.query(TickerPrice).filter(
            TickerPrice.ticker.in_(tickers),
            TickerPrice.date == latest_date,
        ).all()
        price_map = {r.ticker: Decimal(str(r.price)) for r in price_rows}

        if any(t not in price_map for t in tickers):
            return

        total_value = Decimal('0')
        for h in holdings:
            if h.ticker == CASH_TICKER:
                total_value += Decimal(str(h.quantity))
            else:
                total_value += Decimal(str(h.quantity)) * price_map[h.ticker]

    today = today_kst()
    existing = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.portfolio_id == portfolio.id,
        PortfolioSnapshot.date == today,
    ).first()

    if existing:
        # 전일 값은 그대로 두고 오늘 값이 바뀐 만큼 변화량도 다시 계산한다
        prev_value = Decimal(str(existing.prev_value)) if existing.prev_value is not None else None
        existing.total_value = total_value
        existing.change_amount, existing.change_rate = daily_change(total_value, prev_value)
        existing.updated_at = utcnow()
    else:
        prev_snapshot = db.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.portfolio_id == portfolio.id,
            PortfolioSnapshot.date < today,
        ).order_by(PortfolioSnapshot.date.desc()).first()

        prev_value = Decimal(str(prev_snapshot.total_value)) if prev_snapshot else None
        change_amount, change_rate = daily_change(total_value, prev_value)

        snapshot = PortfolioSnapshot(
            portfolio_id=portfolio.id,
            date=today,
            total_value=total_value,
            prev_value=prev_value,
            change_amount=change_amount,
            change_rate=change_rate,
        )
        db.add(snapshot)


@router.put("/{portfolio_id}", response_model=PortfolioResponse)
def update_portfolio(
    portfolio_id: int,
    request: PortfolioUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)

    snapshot_just_enabled = (
        request.snapshot_enabled is True and not portfolio.snapshot_enabled
    )
    snapshot_just_disabled = (
        request.snapshot_enabled is False and portfolio.snapshot_enabled
    )

    if request.name is not None:
        portfolio.name = request.name
    if request.account_types is not None:
        portfolio.account_types = request.account_types
    if request.calculation_base is not None:
        portfolio.calculation_base = request.calculation_base
    if request.target_total_amount is not None:
        portfolio.target_total_amount = request.target_total_amount
    if request.snapshot_enabled is not None:
        portfolio.snapshot_enabled = request.snapshot_enabled
    if snapshot_just_disabled:
        # 끄면 쌓인 기록을 모두 지운다. 다시 켜면 그날부터 새로 쌓는다 (화면에서 경고 후 끈다)
        db.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.portfolio_id == portfolio.id,
        ).delete(synchronize_session=False)

    if snapshot_just_enabled:
        db.flush()
        _try_create_immediate_snapshot(db, portfolio)

    # 설정 변경과 즉시 스냅샷을 한 번에 커밋한다
    db.commit()
    db.refresh(portfolio)
    return portfolio


@router.put("/{portfolio_id}/batch", response_model=PortfolioDetailResponse)
def batch_update_portfolio(
    portfolio_id: int,
    request: PortfolioBatchUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)

    # Update settings
    if request.name is not None:
        portfolio.name = request.name
    if request.account_types is not None:
        portfolio.account_types = request.account_types
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
        account_types=portfolio.account_types,
        calculation_base=portfolio.calculation_base,
        target_total_amount=portfolio.target_total_amount,
        snapshot_enabled=portfolio.snapshot_enabled,
        target_allocations=[TargetAllocationResponse.model_validate(t) for t in portfolio.target_allocations],
        holdings=[HoldingResponse.model_validate(h) for h in portfolio.holdings],
    )


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio(
    portfolio_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    portfolio = _get_portfolio_or_404(db, portfolio_id, user_id)
    db.delete(portfolio)
    db.commit()


# --- Dashboard ---

class SnapshotRow(NamedTuple):
    """여러 포트폴리오 스냅샷을 날짜별로 합친 행 (_build_dashboard_response 입력)"""
    date: date
    total_value: Decimal
    updated_at: Optional[datetime] = None


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
            updated_at=iso_utc(last_updated_at),
        ),
        chart_data=chart_data,
    )


@router.get("/dashboard/total", response_model=DashboardResponse)
def get_total_dashboard(
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

    snapshots = [
        SnapshotRow(d, agg['total_value'], agg['updated_at'])
        for d, agg in sorted(date_agg.items())
    ]
    return _build_dashboard_response(snapshots)


@router.get("/dashboard/total/holdings", response_model=TotalHoldingsResponse)
def get_total_holdings(
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
        if ticker == CASH_TICKER:
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
        if ticker == CASH_TICKER:
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


@router.get("/{portfolio_id}/risk-analysis", response_model=RiskAnalysisResponse)
def get_risk_analysis(
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
    weights = {a.ticker: float(a.target_weight) for a in allocations if a.ticker != CASH_TICKER}
    if not weights:
        raise HTTPException(status_code=400, detail="No ETF tickers in portfolio")

    since = period_start(period, today_kst())
    prices = PriceService(db).get_price_history(list(weights), since)
    values = simulate(weights, prices, common_dates(prices, weights))
    if values is None:
        raise HTTPException(status_code=404, detail="Insufficient price data")
    metrics = risk_metrics(values)

    return RiskAnalysisResponse(
        period=period,
        actual_start_date=values[0][0].isoformat(),
        total_return=round(metrics.total_return, 2),
        mdd=round(metrics.mdd, 2),
        volatility=round(metrics.volatility, 2),
        sharpe_ratio=metrics.sharpe_ratio,
        chart_data=[
            RiskChartPoint(date=d.isoformat(), value=round(v, 0), return_rate=round((v - BASE_AMOUNT) / BASE_AMOUNT * 100, 2))
            for d, v in values
        ],
        drawdown_data=[DrawdownPoint(date=d.isoformat(), drawdown=round(dd, 2)) for d, dd in metrics.drawdowns],
    )


@router.get("/{portfolio_id}/dashboard", response_model=DashboardResponse)
def get_portfolio_dashboard(
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
    invested = invested_amount(db.query(Holding).filter(Holding.portfolio_id == portfolio.id))
    if invested:
        response.summary.invested_amount = invested
        current_value = response.summary.current_value
        return_amount = current_value - invested
        return_rate = float(return_amount / invested * 100)
        response.summary.investment_return = DashboardSummaryItem(
            amount=return_amount, rate=round(return_rate, 2),
        )

    return response


# --- Target Allocations ---

@router.post("/{portfolio_id}/targets", response_model=TargetAllocationResponse, status_code=status.HTTP_201_CREATED)
def add_target(
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
def update_target(
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
def delete_target(
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
def add_holding(
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
def update_holding(
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
def delete_holding(
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
def calculate(
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
