from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.etf import ETF
from ..services.graph_service import GraphService

router = APIRouter()


class TagResponse(BaseModel):
    name: str
    etf_count: int


class TagETFResponse(BaseModel):
    code: str
    name: str
    net_assets: Optional[int] = None


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
    graph_etfs = graph_service.get_etfs_by_tag(name)
    codes = [e["code"] for e in graph_etfs]
    if not codes:
        return []
    # RDB에서 순자산 조회
    rdb_rows = db.query(ETF.code, ETF.name, ETF.net_assets).filter(ETF.code.in_(codes)).all()
    rdb_map = {r.code: r for r in rdb_rows}
    results = []
    for e in graph_etfs:
        rdb = rdb_map.get(e["code"])
        results.append({
            "code": e["code"],
            "name": rdb.name if rdb else e["name"],
            "net_assets": rdb.net_assets if rdb else None,
        })
    results.sort(key=lambda x: x["net_assets"] or 0, reverse=True)
    return results


@router.get("/{name}/etfs/{etf_code}/holdings", response_model=List[TagHoldingResponse])
async def get_holdings_by_etf(name: str, etf_code: str, db: Session = Depends(get_db)):
    graph_service = GraphService(db)
    return graph_service.get_holdings_by_etf_graph(etf_code)
