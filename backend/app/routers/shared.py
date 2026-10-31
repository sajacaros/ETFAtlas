import uuid as uuid_module

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from datetime import date, timedelta

from ..database import get_db
from ..models.portfolio import SharedPortfolio
from ..models.user import User
from ..schemas.portfolio import (
    SharedPortfolioListItem,
    SharedPortfolioDetail,
    SharedAllocationItem,
    SharedReturnsResponse,
    SharedReturnsChartPoint,
    SharedReturnsSummary,
)
from ..domain.portfolio_calculation import CASH_TICKER
from ..domain.portfolio_metrics import (
    BASE_AMOUNT, MIN_PERIOD_COVERAGE, PriceHistory, common_dates, covers_period, simulate, total_return,
)
from ..services.price_service import PriceService
from ..utils.session import get_current_user_id
from ..utils.time import iso_utc, today_kst

router = APIRouter()


def _owner_name(user: User) -> str:
    return user.name or user.username


@router.get("/", response_model=list[SharedPortfolioListItem])
def list_shared_portfolios(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(SharedPortfolio, User)
        .join(User, SharedPortfolio.user_id == User.id)
        .order_by(SharedPortfolio.created_at.desc(), SharedPortfolio.id.desc())
        .all()
    )
    return [
        SharedPortfolioListItem(
            portfolio_name=s.name,
            account_types=s.account_types,
            share_token=str(s.share_token),
            # 현금은 종목 수에 넣지 않는다
            tickers_count=sum(1 for a in s.allocations if a["ticker"] != CASH_TICKER),
            owner_id=owner.id,
            owner_name=_owner_name(owner),
            shared_at=iso_utc(s.created_at),
            is_owner=s.user_id == user_id,
        )
        for s, owner in rows
    ]


def _get_shared_portfolio(db: Session, share_token: str) -> SharedPortfolio:
    try:
        token_uuid = uuid_module.UUID(share_token)
    except ValueError:
        raise HTTPException(status_code=404, detail="Shared portfolio not found")
    shared = db.query(SharedPortfolio).filter(SharedPortfolio.share_token == token_uuid).first()
    if not shared:
        raise HTTPException(status_code=404, detail="Shared portfolio not found")
    return shared


def _etf_weights(shared: SharedPortfolio) -> dict[str, float]:
    """현금을 뺀 종목별 비중(0~1). 수익률은 이 비중을 다시 정규화해 계산한다."""
    return {
        a["ticker"]: float(a["weight"]) / 100.0
        for a in shared.allocations
        if a["ticker"] != CASH_TICKER
    }


@router.get("/{share_token}", response_model=SharedPortfolioDetail)
def get_shared_portfolio(
    share_token: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    shared = _get_shared_portfolio(db, share_token)
    owner = db.get(User, shared.user_id)
    names = PriceService(db).get_etf_names([a["ticker"] for a in shared.allocations])

    return SharedPortfolioDetail(
        portfolio_name=shared.name,
        account_types=shared.account_types,
        allocations=[
            SharedAllocationItem(
                ticker=a["ticker"],
                name=names.get(a["ticker"], a["ticker"]),
                weight=float(a["weight"]),
            )
            for a in shared.allocations
        ],
        owner_name=_owner_name(owner),
        shared_at=iso_utc(shared.created_at),
        is_owner=shared.user_id == user_id,
    )


@router.delete("/{share_token}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shared_portfolio(
    share_token: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    shared = _get_shared_portfolio(db, share_token)
    if shared.user_id != user_id:
        raise HTTPException(status_code=403, detail="공유한 사람만 삭제할 수 있습니다")
    db.delete(shared)
    db.commit()


SHARED_PERIOD_DAYS = {"1w": 7, "1m": 30, "3m": 90}


def _period_return(weights: dict[str, float], prices: PriceHistory, today: date, days: int) -> float | None:
    """최근 days일 가상 수익률(%). 공통 시세가 기간을 충분히 덮지 못하면 None."""
    dates = common_dates(prices, weights, since=today - timedelta(days=days))
    if not covers_period(dates, days):
        return None
    values = simulate(weights, prices, dates)
    return round(total_return(values), 2) if values else None


@router.get("/{share_token}/returns-summary", response_model=SharedReturnsSummary)
def get_shared_returns_summary(
    share_token: str,
    db: Session = Depends(get_db),
):
    shared = _get_shared_portfolio(db, share_token)
    weights = _etf_weights(shared)
    if not weights:
        return SharedReturnsSummary()

    today = today_kst()
    prices = PriceService(db).get_price_history(list(weights), today - timedelta(days=max(SHARED_PERIOD_DAYS.values())))
    if not prices:
        return SharedReturnsSummary()

    returns = {key: _period_return(weights, prices, today, days) for key, days in SHARED_PERIOD_DAYS.items()}
    return SharedReturnsSummary(returns_1w=returns["1w"], returns_1m=returns["1m"], returns_3m=returns["3m"])


@router.get("/{share_token}/returns", response_model=SharedReturnsResponse)
def get_shared_returns(
    share_token: str,
    period: str = Query(default="1m", pattern="^(1w|1m|3m)$"),
    db: Session = Depends(get_db),
):
    shared = _get_shared_portfolio(db, share_token)
    if not shared.allocations:
        raise HTTPException(status_code=404, detail="No allocations found")

    weights = _etf_weights(shared)
    if not weights:
        raise HTTPException(status_code=400, detail="No ETF tickers in portfolio")

    days = SHARED_PERIOD_DAYS[period]
    prices = PriceService(db).get_price_history(list(weights), today_kst() - timedelta(days=days))
    if not prices:
        raise HTTPException(status_code=404, detail="No price data available")

    dates = common_dates(prices, weights)
    if len(dates) < 2:
        raise HTTPException(status_code=404, detail="Insufficient price data")
    if not covers_period(dates, days):
        actual_span = (dates[-1] - dates[0]).days
        raise HTTPException(
            status_code=404,
            detail=f"Insufficient price data: covers {actual_span} days, need at least {int(days * MIN_PERIOD_COVERAGE)} days for {period} period",
        )
    values = simulate(weights, prices, dates)
    if values is None:
        raise HTTPException(status_code=400, detail="No ETF tickers in portfolio")

    return SharedReturnsResponse(
        base_amount=BASE_AMOUNT,
        period=period,
        actual_start_date=dates[0].isoformat(),
        chart_data=[SharedReturnsChartPoint(date=d.isoformat(), value=round(v, 0)) for d, v in values],
    )
