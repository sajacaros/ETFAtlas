from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.etf import Stock
from ..services.etf_service import ETFService

router = APIRouter()


class StockResponse(BaseModel):
    code: str
    name: str
    sector: str | None

    class Config:
        from_attributes = True


class ETFByStockResponse(BaseModel):
    etf_code: str
    etf_name: str
    issuer: str | None
    category: str | None
    weight: float


@router.get("/search", response_model=List[StockResponse])
async def search_stocks(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    stocks = db.query(Stock).filter(
        (Stock.code.ilike(f"%{q}%")) | (Stock.name.ilike(f"%{q}%"))
    ).limit(limit).all()
    return stocks


@router.get("/{code}/etfs", response_model=List[ETFByStockResponse])
async def get_etfs_by_stock(
    code: str,
    db: Session = Depends(get_db)
):
    """특정 종목을 보유한 ETF 목록 조회 (역추적)"""
    etf_service = ETFService(db)
    etfs = etf_service.find_etfs_by_stock(code)
    return etfs
