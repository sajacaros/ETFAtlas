from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from datetime import date
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.etf_service import ETFService
from ..services.graph_service import GraphService

router = APIRouter()


class ETFResponse(BaseModel):
    id: int
    code: str
    name: str
    issuer: str | None
    category: str | None
    net_assets: int | None
    expense_ratio: float | None
    inception_date: date | None

    class Config:
        from_attributes = True


class HoldingResponse(BaseModel):
    stock_code: str
    stock_name: str
    sector: str | None
    weight: float
    shares: int | None
    recorded_at: date


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


class SimilarETFResponse(BaseModel):
    etf_code: str
    overlap: int


@router.get("/search", response_model=List[ETFResponse])
async def search_etfs(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    etf_service = ETFService(db)
    etfs = etf_service.search_etfs(q, limit)
    return etfs


@router.get("/{code}", response_model=ETFResponse)
async def get_etf(code: str, db: Session = Depends(get_db)):
    etf_service = ETFService(db)
    etf = etf_service.get_etf_by_code(code)
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")
    return etf


@router.get("/{code}/holdings", response_model=List[HoldingResponse])
async def get_etf_holdings(
    code: str,
    date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    etf_service = ETFService(db)
    etf = etf_service.get_etf_by_code(code)
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")
    holdings = etf_service.get_etf_holdings(etf.id, date)
    return holdings


@router.get("/{code}/changes", response_model=List[HoldingChangeResponse])
async def get_holdings_changes(
    code: str,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db)
):
    etf_service = ETFService(db)
    etf = etf_service.get_etf_by_code(code)
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")
    changes = etf_service.get_holdings_changes(etf.id, days)
    return changes


@router.get("/{code}/prices", response_model=List[PriceResponse])
async def get_etf_prices(
    code: str,
    days: int = Query(365, ge=1, le=1825),
    db: Session = Depends(get_db)
):
    etf_service = ETFService(db)
    etf = etf_service.get_etf_by_code(code)
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")
    prices = etf_service.get_etf_prices(etf.code, days)
    return prices


@router.get("/{code}/similar", response_model=List[SimilarETFResponse])
async def get_similar_etfs(
    code: str,
    min_overlap: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db)
):
    graph_service = GraphService(db)
    similar = graph_service.find_similar_etfs(code, min_overlap)
    return similar
