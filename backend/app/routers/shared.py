import uuid as uuid_module

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import UTC, date, datetime, timedelta

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
from ..services.price_service import PriceService
from ..utils.session import get_current_user_id

router = APIRouter()


def _owner_name(user: User) -> str:
    return user.name or user.username


def _iso_utc(dt: datetime | None) -> str | None:
    # DB에는 시간대 없는 UTC로 저장돼 있어 브라우저가 현지 시각으로 읽도록 시간대를 붙인다
    return dt.replace(tzinfo=UTC).isoformat() if dt else None


@router.get("/", response_model=list[SharedPortfolioListItem])
async def list_shared_portfolios(
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
            account_type=s.account_type,
            share_token=str(s.share_token),
            # 현금은 종목 수에 넣지 않는다
            tickers_count=sum(1 for a in s.allocations if a["ticker"] != "CASH"),
            owner_id=owner.id,
            owner_name=_owner_name(owner),
            shared_at=_iso_utc(s.created_at),
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
        if a["ticker"] != "CASH"
    }


@router.get("/{share_token}", response_model=SharedPortfolioDetail)
async def get_shared_portfolio(
    share_token: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    shared = _get_shared_portfolio(db, share_token)
    owner = db.get(User, shared.user_id)
    names = PriceService(db).get_etf_names([a["ticker"] for a in shared.allocations])

    return SharedPortfolioDetail(
        portfolio_name=shared.name,
        account_type=shared.account_type,
        allocations=[
            SharedAllocationItem(
                ticker=a["ticker"],
                name=names.get(a["ticker"], a["ticker"]),
                weight=float(a["weight"]),
            )
            for a in shared.allocations
        ],
        owner_name=_owner_name(owner),
        shared_at=_iso_utc(shared.created_at),
        is_owner=shared.user_id == user_id,
    )


@router.delete("/{share_token}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shared_portfolio(
    share_token: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    shared = _get_shared_portfolio(db, share_token)
    if shared.user_id != user_id:
        raise HTTPException(status_code=403, detail="공유한 사람만 삭제할 수 있습니다")
    db.delete(shared)
    db.commit()


def _calc_return_rate(
    tickers: list[str],
    weights: dict[str, float],
    price_map: dict[str, dict[date, float]],
    all_dates: set[date],
    period_days: int = 0,
) -> float | None:
    """공통 날짜 기반 가상 수익률(%) 계산. 데이터 부족 시 None 반환.

    period_days > 0이면 common_dates의 실제 범위가 요청 기간의 70% 미만일 때 None 반환.
    (상장한 지 얼마 안 된 종목이 포함된 경우 왜곡 방지)
    """
    common_dates = sorted(
        d for d in all_dates
        if all(d in price_map.get(t, {}) for t in tickers)
    )
    if len(common_dates) < 2:
        return None

    if period_days > 0:
        actual_span = (common_dates[-1] - common_dates[0]).days
        if actual_span < period_days * 0.7:
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
    shared = _get_shared_portfolio(db, share_token)
    weights = _etf_weights(shared)
    tickers = list(weights)

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
        returns[key] = _calc_return_rate(tickers, weights, price_map, filtered, period_days=days)

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
    shared = _get_shared_portfolio(db, share_token)
    if not shared.allocations:
        raise HTTPException(status_code=404, detail="No allocations found")

    weights = _etf_weights(shared)
    tickers = list(weights)

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

    p_days = period_days[period]
    actual_span = (common_dates[-1] - common_dates[0]).days
    if actual_span < p_days * 0.7:
        raise HTTPException(
            status_code=404,
            detail=f"Insufficient price data: covers {actual_span} days, need at least {int(p_days * 0.7)} days for {period} period",
        )

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
