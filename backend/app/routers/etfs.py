from fastapi import APIRouter, Depends, Query, HTTPException
from typing import List
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.graph_service import GraphService
from ..services.etf_service import ETFService
from ..services.weight_changes import (
    get_alert_thresholds, get_significant_changes, is_significant, resolve_change_date,
)
from ..models.etf import ETF
from ..schemas.etf import (
    ActiveChangeResponse,
    ActiveChangesResponse,
    CompositionETF,
    CompositionRequest,
    CompositionResponse,
    CompositionStock,
    ETFHoldingResponse,
    ETFListItem,
    ETFResponse,
    ETFSearchResponse,
    HoldingChangeResponse,
    PriceResponse,
    SimilarETFResponse,
)
from ..domain.composition import ETFAllocation, aggregate_composition
from ..domain.portfolio_calculation import CASH_TICKER

router = APIRouter()


COMPOSITION_TOP_N = 30


@router.get("/latest-date")
def get_latest_date(db: Session = Depends(get_db)):
    """최신 가격 데이터 기준일 조회"""
    graph = GraphService(db)
    date = graph.get_latest_price_date()
    return {"date": date}


@router.get("/top", response_model=List[ETFListItem])
def get_top_etfs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query("market_cap", pattern="^(market_cap|market_cap_change_1w|return_1d|return_1w)$"),
    active: bool | None = Query(None, description="true: 액티브만, false: 패시브만"),
    db: Session = Depends(get_db),
):
    """ETF 목록 (정렬: market_cap, market_cap_change_1w, return_1w)"""
    graph = GraphService(db)
    return graph.get_top_etfs(limit, sort, offset, active)


@router.get("/search/universe", response_model=List[ETFListItem])
def search_etfs_universe(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """AGE Universe 내 ETF 검색 (시가총액순)"""
    graph = GraphService(db)
    return graph.search_etfs_in_universe(q, limit, offset)


@router.get("/search", response_model=List[ETFSearchResponse])
def search_etfs(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """ETF 검색 (RDB 기반, 전체 ETF 대상)"""
    service = ETFService(db)
    return service.search_etfs(q, limit)


@router.post("/composition", response_model=CompositionResponse)
def get_composition(request: CompositionRequest, db: Session = Depends(get_db)):
    """ETF 투자 비중으로 구성종목 비중 계산. ETF 비중은 100%로 환산하고 겹치는 종목은 합산해 상위 30개"""
    # 현금은 구성종목이 없으므로 환산에서도 뺀다
    items = [i for i in request.items if i.code.upper() != CASH_TICKER]
    codes = list(dict.fromkeys(i.code for i in items))
    if len(codes) != len(items):
        raise HTTPException(status_code=400, detail="같은 ETF가 두 번 들어 있습니다")
    names = {e.code: e.name for e in db.query(ETF).filter(ETF.code.in_(codes)).all()}

    holdings_of = GraphService(db).get_holdings_of([i.code for i in items if i.weight > 0])
    allocations = []
    as_of = None
    for item in items:
        holdings = holdings_of.get(item.code, []) if item.weight > 0 else []
        for h in holdings:
            if h.get("recorded_at") and (as_of is None or h["recorded_at"] > as_of):
                as_of = h["recorded_at"]
        allocations.append(ETFAllocation(item.code, names.get(item.code, item.code), item.weight, holdings))

    stocks = aggregate_composition(allocations)
    return CompositionResponse(
        stocks=[
            CompositionStock(
                rank=i + 1,
                stock_code=s.stock_code,
                stock_name=s.stock_name,
                weight=s.weight,
                etfs=[CompositionETF(code=e.code, name=e.name, weight=e.weight) for e in s.etfs],
            )
            for i, s in enumerate(stocks[:COMPOSITION_TOP_N])
        ],
        total_stocks=len(stocks),
        as_of=as_of,
    )


@router.get("/active/changes", response_model=ActiveChangesResponse)
def get_active_changes(
    base_date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    period: str = Query("1d", pattern="^(1d|1w|1m)$"),
    db: Session = Depends(get_db),
):
    """액티브 ETF 전체의 비중 변화 (기준값 초과만). 모든 회원이 같은 목록을 본다.

    1d는 Airflow가 계산해 둔 weight_changes(직전 공시일 대비)를 읽는다 — 디스코드 알림과 같은 데이터.
    1w/1m은 7일/30일 전(그날 이하 마지막 공시일)의 HOLDS와 바로 비교한다.
    base_date를 주면 그날 이전에 계산된 가장 최근 날짜를 쓴다.
    """
    threshold, added_threshold = get_alert_thresholds(db)
    current_date = resolve_change_date(db, base_date)
    if not current_date:
        return ActiveChangesResponse(threshold=threshold, added_threshold=added_threshold, changes=[])
    if period == "1d":
        changes = get_significant_changes(db, current_date, threshold, added_threshold)
        previous_date = max((c.prev_date for c in changes), default=None)
    else:
        all_changes, previous_date = GraphService(db).get_active_period_changes(
            current_date, 7 if period == "1w" else 30
        )
        changes = sorted(
            (c for c in all_changes
             if is_significant(c["change_type"], c["weight_change"], threshold, added_threshold)),
            key=lambda c: (-abs(c["weight_change"]), c["etf_code"], c["stock_code"]),
        )
    return ActiveChangesResponse(
        current_date=current_date,
        previous_date=previous_date,
        threshold=threshold,
        added_threshold=added_threshold,
        changes=[
            ActiveChangeResponse.model_validate(c, from_attributes=not isinstance(c, dict)) for c in changes
        ],
    )


@router.get("/{code}", response_model=ETFResponse)
def get_etf(code: str, db: Session = Depends(get_db)):
    graph = GraphService(db)
    etf = graph.get_etf_detail(code)
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")
    return etf


@router.get("/{code}/holdings", response_model=List[ETFHoldingResponse])
def get_etf_holdings(
    code: str,
    db: Session = Depends(get_db)
):
    graph_service = GraphService(db)
    holdings = graph_service.get_etf_holdings_full(code)
    return holdings


@router.get("/{code}/changes", response_model=List[HoldingChangeResponse])
def get_holdings_changes(
    code: str,
    period: str = Query("1d", pattern="^(1d|1w|1m)$"),
    db: Session = Depends(get_db)
):
    graph_service = GraphService(db)
    changes, _, _ = graph_service.get_etf_holdings_changes(code, period)
    return changes


@router.get("/{code}/prices", response_model=List[PriceResponse])
def get_etf_prices(
    code: str,
    days: int = Query(365, ge=1, le=1825),
    db: Session = Depends(get_db)
):
    graph_service = GraphService(db)
    prices = graph_service.get_etf_prices(code, days)
    if not prices:
        raise HTTPException(status_code=404, detail="ETF not found")
    return prices


@router.get("/{code}/tags", response_model=List[str])
def get_etf_tags(
    code: str,
    db: Session = Depends(get_db)
):
    graph_service = GraphService(db)
    return graph_service.get_tags_by_etf(code)


@router.get("/{code}/similar", response_model=List[SimilarETFResponse])
def get_similar_etfs(
    code: str,
    min_overlap: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db)
):
    graph_service = GraphService(db)
    similar = graph_service.find_similar_etfs(code, min_overlap)
    return similar
