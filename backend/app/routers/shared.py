import uuid as uuid_module

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from decimal import Decimal
from datetime import date, timedelta

from ..database import get_db
from ..models.portfolio import Portfolio, TargetAllocation
from ..schemas.portfolio import (
    SharedPortfolioListItem,
    SharedPortfolioDetail,
    SharedAllocationItem,
    SharedReturnsResponse,
    SharedReturnsChartPoint,
    SharedReturnsSummary,
)
from ..services.price_service import PriceService

router = APIRouter()


@router.get("/", response_model=list[SharedPortfolioListItem])
async def list_shared_portfolios(db: Session = Depends(get_db)):
    ticker_count_sub = (
        db.query(
            TargetAllocation.portfolio_id,
            func.count(TargetAllocation.id).label("tickers_count"),
        )
        .group_by(TargetAllocation.portfolio_id)
        .subquery()
    )

    rows = (
        db.query(
            Portfolio,
            func.coalesce(ticker_count_sub.c.tickers_count, 0).label("tickers_count"),
        )
        .outerjoin(ticker_count_sub, Portfolio.id == ticker_count_sub.c.portfolio_id)
        .filter(Portfolio.is_shared.is_(True))
        .order_by(Portfolio.updated_at.desc())
        .all()
    )

    return [
        SharedPortfolioListItem(
            portfolio_name=p.name,
            share_token=str(p.share_token),
            tickers_count=tickers_count,
            updated_at=p.updated_at.isoformat() if p.updated_at else None,
        )
        for p, tickers_count in rows
    ]


def _get_shared_portfolio(db: Session, share_token: str) -> Portfolio:
    try:
        token_uuid = uuid_module.UUID(share_token)
    except ValueError:
        raise HTTPException(status_code=404, detail="Shared portfolio not found")
    portfolio = db.query(Portfolio).filter(
        Portfolio.share_token == token_uuid,
        Portfolio.is_shared.is_(True),
    ).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Shared portfolio not found")
    return portfolio


@router.get("/{share_token}", response_model=SharedPortfolioDetail)
async def get_shared_portfolio(share_token: str, db: Session = Depends(get_db)):
    portfolio = _get_shared_portfolio(db, share_token)

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
        allocations=[
            SharedAllocationItem(
                ticker=a.ticker,
                name=names.get(a.ticker, a.ticker),
                weight=float(a.target_weight),
            )
            for a in allocations
        ],
    )


def _calc_return_rate(
    tickers: list[str],
    weights: dict[str, float],
    price_map: dict[str, dict[date, float]],
    all_dates: set[date],
) -> float | None:
    """공통 날짜 기반 가상 수익률(%) 계산. 데이터 부족 시 None 반환."""
    common_dates = sorted(
        d for d in all_dates
        if all(d in price_map.get(t, {}) for t in tickers)
    )
    if len(common_dates) < 2:
        return None

    total_weight = sum(weights.values())
    if total_weight <= 0:
        return None
    norm = {t: w / total_weight for t, w in weights.items()}

    base = 10_000_000
    start = common_dates[0]
    vq = {}
    for t in tickers:
        sp = price_map[t][start]
        vq[t] = (base * norm.get(t, 0)) / sp if sp > 0 else 0

    end = common_dates[-1]
    end_val = sum(vq[t] * price_map[t][end] for t in tickers)
    return ((end_val - base) / base) * 100


@router.get("/{share_token}/returns-summary", response_model=SharedReturnsSummary)
async def get_shared_returns_summary(
    share_token: str,
    db: Session = Depends(get_db),
):
    portfolio = _get_shared_portfolio(db, share_token)

    allocations = (
        db.query(TargetAllocation)
        .filter(TargetAllocation.portfolio_id == portfolio.id)
        .all()
    )
    tickers = [a.ticker for a in allocations if a.ticker != "CASH"]
    weights = {a.ticker: float(a.target_weight) / 100.0 for a in allocations if a.ticker != "CASH"}

    if not tickers:
        return SharedReturnsSummary()

    today = date.today()
    start_3m = today - timedelta(days=90)

    result = db.execute(
        text("""
            SELECT ticker, date, price
            FROM ticker_prices
            WHERE ticker = ANY(:tickers)
              AND date >= :start_date
            ORDER BY date
        """),
        {"tickers": tickers, "start_date": start_3m},
    )

    price_map: dict[str, dict[date, float]] = {}
    all_dates: set[date] = set()
    for row in result:
        t, d, p = row.ticker, row.date, float(row.price)
        price_map.setdefault(t, {})[d] = p
        all_dates.add(d)

    if not all_dates:
        return SharedReturnsSummary()

    periods = {"1w": 7, "1m": 30, "3m": 90}
    returns: dict[str, float | None] = {}
    for key, days in periods.items():
        cutoff = today - timedelta(days=days)
        filtered = {d for d in all_dates if d >= cutoff}
        returns[key] = _calc_return_rate(tickers, weights, price_map, filtered)

    return SharedReturnsSummary(
        returns_1w=round(returns["1w"], 2) if returns["1w"] is not None else None,
        returns_1m=round(returns["1m"], 2) if returns["1m"] is not None else None,
        returns_3m=round(returns["3m"], 2) if returns["3m"] is not None else None,
    )


@router.get("/{share_token}/returns", response_model=SharedReturnsResponse)
async def get_shared_returns(
    share_token: str,
    period: str = Query(default="1m", pattern="^(1w|1m|3m)$"),
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

    # 비중 정규화 (CASH 제외 후 합이 1이 되도록)
    total_weight = sum(weights.values())
    norm_weights = {t: w / total_weight for t, w in weights.items()} if total_weight > 0 else weights

    # 시작일 종가 기준 가상 매수수량 계산
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
