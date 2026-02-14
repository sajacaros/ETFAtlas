from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.graph_service import GraphService

router = APIRouter()


class TagResponse(BaseModel):
    name: str
    etf_count: int


class TagETFResponse(BaseModel):
    code: str
    name: str
    net_assets: Optional[int] = None
    return_1d: Optional[float] = None
    return_1w: Optional[float] = None
    return_1m: Optional[float] = None
    market_cap_change_1w: Optional[float] = None


class TagHoldingResponse(BaseModel):
    stock_code: str
    stock_name: str
    weight: float


@router.get("/", response_model=List[TagResponse])
async def get_all_tags(db: Session = Depends(get_db)):
    graph_service = GraphService(db)
    return graph_service.get_all_tags()


@router.get("/{name}/etfs", response_model=List[TagETFResponse])
async def get_etfs_by_tag(name: str, db: Session = Depends(get_db)):
    graph_service = GraphService(db)
    return graph_service.get_etfs_by_tag(name)


@router.get("/{name}/etfs/{etf_code}/holdings", response_model=List[TagHoldingResponse])
async def get_holdings_by_etf(name: str, etf_code: str, db: Session = Depends(get_db)):
    graph_service = GraphService(db)
    return graph_service.get_holdings_by_etf_graph(etf_code)
