from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.graph_service import GraphService
from ..services.etf_service import ETFService
from ..models.etf import ETF
from ..domain.composition import ETFAllocation, aggregate_composition

router = APIRouter()


class ETFResponse(BaseModel):
    code: str
    name: str
    issuer: str | None = None
    net_assets: int | None = None
    expense_ratio: float | None = None
    description: str | None = None
    base_index: str | None = None
    listed_date: str | None = None
    dividend_cycle: int | None = None


class HoldingResponse(BaseModel):
    stock_code: str
    stock_name: str
    sector: str | None = None
    weight: float
    shares: int | None = None
    recorded_at: str | None = None


class HoldingChangeResponse(BaseModel):
    stock_code: str
    stock_name: str
    change_type: str
    current_weight: float
    previous_weight: float
    weight_change: float


class PriceResponse(BaseModel):
    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    market_cap: int | None = None
    net_assets: int | None = None


class SimilarETFResponse(BaseModel):
    etf_code: str
    name: str
    overlap: int
    similarity: float


class UniverseETFResponse(BaseModel):
    code: str
    name: str
    net_assets: int | None = None
    return_1d: float | None = None
    return_1w: float | None = None
    return_1m: float | None = None
    market_cap_change_1w: float | None = None


class ETFSearchResponse(BaseModel):
    code: str
    name: str


class CompositionItem(BaseModel):
    code: str
    weight: float = Field(ge=0)


class CompositionRequest(BaseModel):
    items: List[CompositionItem] = Field(max_length=50)


class CompositionETF(BaseModel):
    code: str
    name: str
    weight: float


class CompositionStock(BaseModel):
    rank: int
    stock_code: str
    stock_name: str
    weight: float
    etfs: List[CompositionETF]


class CompositionResponse(BaseModel):
    stocks: List[CompositionStock]
    total_stocks: int
    as_of: str | None = None


COMPOSITION_TOP_N = 30


@router.get("/latest-date")
async def get_latest_date(db: Session = Depends(get_db)):
    """최신 가격 데이터 기준일 조회"""
    graph = GraphService(db)
    date = graph.get_latest_price_date()
    return {"date": date}


@router.get("/top", response_model=List[UniverseETFResponse])
async def get_top_etfs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query("market_cap", pattern="^(market_cap|market_cap_change_1w|return_1d|return_1w)$"),
    db: Session = Depends(get_db),
):
    """ETF 목록 (정렬: market_cap, market_cap_change_1w, return_1w)"""
    graph = GraphService(db)
    return graph.get_top_etfs(limit, sort, offset)


@router.get("/search/universe", response_model=List[UniverseETFResponse])
async def search_etfs_universe(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """AGE Universe 내 ETF 검색 (시가총액순)"""
    graph = GraphService(db)
    return graph.search_etfs_in_universe(q, limit, offset)


@router.get("/search", response_model=List[ETFSearchResponse])
async def search_etfs(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """ETF 검색 (RDB 기반, 전체 ETF 대상)"""
    service = ETFService(db)
    return service.search_etfs(q, limit)


@router.post("/composition", response_model=CompositionResponse)
async def get_composition(request: CompositionRequest, db: Session = Depends(get_db)):
    """ETF 투자 비중으로 구성종목 비중 계산. ETF 비중은 100%로 환산하고 겹치는 종목은 합산해 상위 30개"""
    # 현금은 구성종목이 없으므로 환산에서도 뺀다
    items = [i for i in request.items if i.code.upper() != "CASH"]
    codes = list(dict.fromkeys(i.code for i in items))
    if len(codes) != len(items):
        raise HTTPException(status_code=400, detail="같은 ETF가 두 번 들어 있습니다")
    names = {e.code: e.name for e in db.query(ETF).filter(ETF.code.in_(codes)).all()}

    graph = GraphService(db)
    allocations = []
    as_of = None
    for item in items:
        holdings = graph.get_etf_holdings_full(item.code) if item.weight > 0 else []
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


@router.get("/{code}", response_model=ETFResponse)
async def get_etf(code: str, db: Session = Depends(get_db)):
    graph = GraphService(db)
    etf = graph.get_etf_detail(code)
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")
    return etf


@router.get("/{code}/holdings", response_model=List[HoldingResponse])
async def get_etf_holdings(
    code: str,
    db: Session = Depends(get_db)
):
    graph_service = GraphService(db)
    holdings = graph_service.get_etf_holdings_full(code)
    return holdings


@router.get("/{code}/changes", response_model=List[HoldingChangeResponse])
async def get_holdings_changes(
    code: str,
    period: str = Query("1d", pattern="^(1d|1w|1m)$"),
    db: Session = Depends(get_db)
):
    graph_service = GraphService(db)
    changes, _, _ = graph_service.get_etf_holdings_changes(code, period)
    return changes


@router.get("/{code}/prices", response_model=List[PriceResponse])
async def get_etf_prices(
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
async def get_etf_tags(
    code: str,
    db: Session = Depends(get_db)
):
    graph_service = GraphService(db)
    return graph_service.get_tags_by_etf(code)


@router.get("/{code}/similar", response_model=List[SimilarETFResponse])
async def get_similar_etfs(
    code: str,
    min_overlap: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db)
):
    graph_service = GraphService(db)
    similar = graph_service.find_similar_etfs(code, min_overlap)
    return similar
