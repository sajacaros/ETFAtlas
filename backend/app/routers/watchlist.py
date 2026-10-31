from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from sqlalchemy.orm import Session
from ..database import get_db
from ..schemas.etf import WatchlistItemResponse
from ..services.graph_service import GraphService
from ..utils.session import get_current_user_id

router = APIRouter()


@router.get("/", response_model=List[WatchlistItemResponse])
def get_watches(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    graph = GraphService(db)
    items = graph.get_user_watches(user_id)

    # 첫 번째 태그를 category로
    tags = graph.get_tags_of([item["etf_code"] for item in items])
    tag_map = {code: names[0] for code, names in tags.items() if names}

    return [
        WatchlistItemResponse(
            etf_code=item["etf_code"],
            etf_name=item["etf_name"],
            category=tag_map.get(item["etf_code"]),
        )
        for item in items
    ]


@router.get("/codes", response_model=List[str])
def get_watched_codes(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    graph = GraphService(db)
    return graph.get_watched_codes(user_id)


@router.get("/etfs")
def get_watched_etfs(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """즐겨찾기 ETF 목록 (시총/수익률 포함, ETFListItem 형식)"""
    graph = GraphService(db)
    return graph.get_watched_etfs(user_id)


@router.post("/{etf_code}", response_model=WatchlistItemResponse, status_code=status.HTTP_201_CREATED)
def add_watch(
    etf_code: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    graph = GraphService(db)
    result = graph.add_watch(user_id, etf_code)

    if result.get("error") == "etf_not_found":
        raise HTTPException(status_code=404, detail="ETF not found")
    if result.get("error") == "already_exists":
        raise HTTPException(status_code=400, detail="Already watching this ETF")

    tags = graph.get_tags_by_etf(etf_code)
    return WatchlistItemResponse(
        etf_code=result["etf_code"],
        etf_name=result["etf_name"],
        category=tags[0] if tags else None,
    )


@router.delete("/{etf_code}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watch(
    etf_code: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    graph = GraphService(db)
    deleted = graph.remove_watch(user_id, etf_code)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not watching this ETF")
