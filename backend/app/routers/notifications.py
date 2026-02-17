from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from ..database import get_db
from ..models.user import User
from ..models.collection_run import CollectionRun
from ..utils.jwt import get_current_user_id

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
