from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.graph_service import GraphService

router = APIRouter()


class ETFResponse(BaseModel):
    code: str
    name: str
    issuer: str | None = None
    net_assets: int | None = None
    expense_ratio: float | None = None


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


@router.get("/top", response_model=List[UniverseETFResponse])
async def get_top_etfs(
    limit: int = Query(20, ge=1, le=100),
    sort: str = Query("market_cap", regex="^(market_cap|market_cap_change_1w|return_1w)$"),
    db: Session = Depends(get_db),
):
    """ETF 목록 (정렬: market_cap, market_cap_change_1w, return_1w)"""
    graph = GraphService(db)
    return graph.get_top_etfs(limit, sort)


@router.get("/search/universe", response_model=List[UniverseETFResponse])
async def search_etfs_universe(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """AGE Universe 내 ETF 검색 (시가총액순)"""
    graph = GraphService(db)
    return graph.search_etfs_in_universe(q, limit)


@router.get("/search", response_model=List[UniverseETFResponse])
async def search_etfs(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """ETF 검색 (AGE 기반, 시가총액순)"""
    graph = GraphService(db)
    return graph.search_etfs_in_universe(q, limit)


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
    period: str = Query("1d", regex="^(1d|1w|1m)$"),
    db: Session = Depends(get_db)
):
    graph_service = GraphService(db)
    changes = graph_service.get_etf_holdings_changes(code, period)
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
