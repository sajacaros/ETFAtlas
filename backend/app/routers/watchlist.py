from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.watchlist import Watchlist, WatchlistItem
from ..models.etf import ETF
from ..utils.jwt import get_current_user_id

router = APIRouter()


class WatchlistCreate(BaseModel):
    name: str = "My Watchlist"


class WatchlistResponse(BaseModel):
    id: int
    name: str
    items: List["WatchlistItemResponse"] = []

    class Config:
        from_attributes = True


class WatchlistItemResponse(BaseModel):
    id: int
    etf_code: str
    etf_name: str
    category: str | None

    class Config:
        from_attributes = True


class AddETFRequest(BaseModel):
    etf_code: str


@router.get("/", response_model=List[WatchlistResponse])
async def get_watchlists(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    watchlists = db.query(Watchlist).filter(Watchlist.user_id == user_id).all()

    result = []
    for wl in watchlists:
        items = []
        for item in wl.items:
            etf = db.query(ETF).filter(ETF.id == item.etf_id).first()
            if etf:
                items.append(WatchlistItemResponse(
                    id=item.id,
                    etf_code=etf.code,
                    etf_name=etf.name,
                    category=etf.category
                ))
        result.append(WatchlistResponse(
            id=wl.id,
            name=wl.name,
            items=items
        ))
    return result


@router.post("/", response_model=WatchlistResponse, status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    request: WatchlistCreate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    watchlist = Watchlist(user_id=user_id, name=request.name)
    db.add(watchlist)
    db.commit()
    db.refresh(watchlist)
    return WatchlistResponse(id=watchlist.id, name=watchlist.name, items=[])


@router.post("/{watchlist_id}/items", response_model=WatchlistItemResponse)
async def add_etf_to_watchlist(
    watchlist_id: int,
    request: AddETFRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    watchlist = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id,
        Watchlist.user_id == user_id
    ).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    etf = db.query(ETF).filter(ETF.code == request.etf_code).first()
    if not etf:
        raise HTTPException(status_code=404, detail="ETF not found")

    existing = db.query(WatchlistItem).filter(
        WatchlistItem.watchlist_id == watchlist_id,
        WatchlistItem.etf_id == etf.id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="ETF already in watchlist")

    item = WatchlistItem(watchlist_id=watchlist_id, etf_id=etf.id)
    db.add(item)
    db.commit()
    db.refresh(item)

    return WatchlistItemResponse(
        id=item.id,
        etf_code=etf.code,
        etf_name=etf.name,
        category=etf.category
    )


@router.delete("/{watchlist_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_etf_from_watchlist(
    watchlist_id: int,
    item_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    watchlist = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id,
        Watchlist.user_id == user_id
    ).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    item = db.query(WatchlistItem).filter(
        WatchlistItem.id == item_id,
        WatchlistItem.watchlist_id == watchlist_id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    db.delete(item)
    db.commit()


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(
    watchlist_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    watchlist = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id,
        Watchlist.user_id == user_id
    ).first()
    if not watchlist:
        raise HTTPException(status_code=404, detail="Watchlist not found")

    db.delete(watchlist)
    db.commit()
