from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.graph_service import GraphService
from ..utils.jwt import get_current_user_id

router = APIRouter()


class WatchlistItemResponse(BaseModel):
    etf_code: str
    etf_name: str
    category: str | None = None


@router.get("/", response_model=List[WatchlistItemResponse])
async def get_watches(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    graph = GraphService(db)
    items = graph.get_user_watches(user_id)

    # AGE에서 태그 조회하여 category로 사용
    codes = [item["etf_code"] for item in items]
    tag_map = {}
    for code in codes:
        tags = graph.get_tags_by_etf(code)
        if tags:
            tag_map[code] = tags[0]  # 첫 번째 태그를 category로

    return [
        WatchlistItemResponse(
            etf_code=item["etf_code"],
            etf_name=item["etf_name"],
            category=tag_map.get(item["etf_code"]),
        )
        for item in items
    ]


class WatchlistChangeItem(BaseModel):
    etf_code: str
    etf_name: str
    stock_code: str
    stock_name: str
    change_type: str
    current_weight: float
    previous_weight: float
    weight_change: float


class WatchlistChangesResponse(BaseModel):
    current_date: str | None = None
    previous_date: str | None = None
    changes: List[WatchlistChangeItem]


@router.get("/changes", response_model=WatchlistChangesResponse)
async def get_watchlist_changes(
    period: str = Query("1d", pattern="^(1d|1w|1m)$"),
    base_date: str = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """즐겨찾기 ETF들의 보유종목 비중 변화 조회 (unchanged 및 |변화량| <= 3%p 제외)"""
    graph = GraphService(db)
    watched = graph.get_user_watches(user_id)

    results = []
    current_date = None
    previous_date = None
    for item in watched:
        etf_code = item["etf_code"]
        etf_name = item["etf_name"]
        changes, cur_d, prev_d = graph.get_etf_holdings_changes(etf_code, period, base_date)
        if cur_d and not current_date:
            current_date = cur_d
            previous_date = prev_d
        for c in changes:
            if c["change_type"] == "unchanged":
                continue
            if abs(c["weight_change"]) <= 3:
                continue
            results.append(WatchlistChangeItem(
                etf_code=etf_code,
                etf_name=etf_name,
                stock_code=c["stock_code"],
                stock_name=c["stock_name"],
                change_type=c["change_type"],
                current_weight=c["current_weight"],
                previous_weight=c["previous_weight"],
                weight_change=c["weight_change"],
            ))

    results.sort(key=lambda x: abs(x.weight_change), reverse=True)
    return WatchlistChangesResponse(
        current_date=current_date,
        previous_date=previous_date,
        changes=results,
    )


@router.get("/codes", response_model=List[str])
async def get_watched_codes(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    graph = GraphService(db)
    return graph.get_watched_codes(user_id)


@router.get("/etfs")
async def get_watched_etfs(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """즐겨찾기 ETF 목록 (시총/수익률 포함, UniverseETFResponse 형식)"""
    graph = GraphService(db)
    return graph.get_watched_etfs(user_id)


@router.post("/{etf_code}", response_model=WatchlistItemResponse, status_code=status.HTTP_201_CREATED)
async def add_watch(
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
async def remove_watch(
    etf_code: str,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    graph = GraphService(db)
    deleted = graph.remove_watch(user_id, etf_code)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not watching this ETF")
