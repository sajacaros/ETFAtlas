import asyncio
import json
import select
import psycopg2
import psycopg2.extensions
from fastapi import APIRouter, Depends, Query as QueryParam
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from ..database import get_db
from ..config import get_settings
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
):
    """SSE 스트림 — pg_notify LISTEN으로 새 수집 즉시 감지 (query param 토큰 인증)"""
    payload = decode_access_token(token)
    user_id = int(payload.get("sub"))

    async def event_generator():
        settings = get_settings()
        conn = psycopg2.connect(settings.database_url)
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute("LISTEN new_collection;")

        try:
            loop = asyncio.get_event_loop()
            while True:
                # select를 executor에서 실행하여 async 블로킹 방지 (5초 타임아웃)
                ready = await loop.run_in_executor(
                    None, lambda: select.select([conn], [], [], 5.0)
                )
                if ready[0]:
                    conn.poll()
                    while conn.notifies:
                        notify = conn.notifies.pop(0)
                        data = json.dumps({
                            "type": "new_changes",
                            "collected_at": notify.payload,
                        })
                        yield f"data: {data}\n\n"
        finally:
            cur.close()
            conn.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
