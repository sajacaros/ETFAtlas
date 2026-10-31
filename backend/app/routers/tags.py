from fastapi import APIRouter, Depends
from typing import List
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas.etf import ETFListItem, TagHoldingResponse, TagResponse
from ..services.graph_service import GraphService

router = APIRouter()


@router.get("/", response_model=List[TagResponse])
def get_all_tags(db: Session = Depends(get_db)):
    graph_service = GraphService(db)
    return graph_service.get_all_tags()


@router.get("/{name}/etfs", response_model=List[ETFListItem])
def get_etfs_by_tag(name: str, db: Session = Depends(get_db)):
    graph_service = GraphService(db)
    return graph_service.get_etfs_by_tag(name)


@router.get("/{name}/etfs/{etf_code}/holdings", response_model=List[TagHoldingResponse])
def get_holdings_by_etf(name: str, etf_code: str, db: Session = Depends(get_db)):
    graph_service = GraphService(db)
    return graph_service.get_holdings_by_etf_graph(etf_code)
