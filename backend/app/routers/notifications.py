import asyncio
import json
from fastapi import APIRouter, Depends, Query as QueryParam
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from ..database import get_db
from ..models.user import User
from ..models.collection_run import CollectionRun
from ..utils.jwt import get_current_user_id, decode_access_token

router = APIRouter()


@router.get("/status")
async def get_notification_status(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """새 알림 유무 확인"""
    user = db.query(User).filter(User.id == user_id).first()
    latest = db.query(CollectionRun).order_by(CollectionRun.created_at.desc()).first()

    if not latest:
        return {"has_new": False, "latest_collected_at": None}

    has_new = (
        user.last_notification_checked_at is None
        or latest.created_at > user.last_notification_checked_at
    )
    return {
        "has_new": has_new,
        "latest_collected_at": latest.collected_at.isoformat(),
    }


@router.post("/check")
async def check_notifications(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """알림 확인 처리 (last_notification_checked_at 갱신)"""
    user = db.query(User).filter(User.id == user_id).first()
    user.last_notification_checked_at = datetime.now(timezone.utc)
    db.commit()
    return {"checked_at": user.last_notification_checked_at.isoformat()}


@router.get("/stream")
async def notification_stream(
    token: str = QueryParam(...),
    db: Session = Depends(get_db),
):
    """SSE 스트림 — 30초마다 새 수집 확인 (query param 토큰 인증)"""
    payload = decode_access_token(token)
    user_id = int(payload.get("sub"))
    user = db.query(User).filter(User.id == user_id).first()

    async def event_generator():
        last_checked = user.last_notification_checked_at
        while True:
            db.expire_all()
            latest = db.query(CollectionRun).order_by(
                CollectionRun.created_at.desc()
            ).first()

            if latest and (last_checked is None or latest.created_at > last_checked):
                data = json.dumps({
                    "type": "new_changes",
                    "collected_at": latest.collected_at.isoformat(),
                })
                yield f"data: {data}\n\n"
                last_checked = latest.created_at

            await asyncio.sleep(30)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
