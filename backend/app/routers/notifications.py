import asyncio
import select
import psycopg2
import psycopg2.extensions
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from ..database import SessionLocal, get_db
from ..config import get_settings
from ..models.user import User
from ..models.collection_run import CollectionRun
from ..utils.session import SESSION_COOKIE, get_current_user_id, resolve_user_id
from ..utils.sse import sse_event
from ..utils.time import iso_utc, utcnow

router = APIRouter()


@router.get("/status")
def get_notification_status(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """새 알림 유무 확인 — 마지막 확인 이후 새 수집이 있고, 그 수집에서 액티브 ETF에 기준값 초과 변화가 있을 때 true"""
    user = db.query(User).filter(User.id == user_id).first()
    latest = db.query(CollectionRun).order_by(CollectionRun.created_at.desc()).first()

    if not latest:
        return {"has_new": False, "latest_collected_at": None}

    has_new = (
        user.last_notification_checked_at is None
        or latest.created_at > user.last_notification_checked_at
    )

    # 액티브 ETF에 실제 기준값 초과 비중 변화(이전 공시일 대비)가 있을 때만 빨간 점 표시
    if has_new:
        from ..services.weight_changes import get_alert_thresholds, get_significant_changes, resolve_change_date
        change_date = resolve_change_date(db)
        has_new = bool(change_date) and bool(get_significant_changes(db, change_date, *get_alert_thresholds(db)))

    return {
        "has_new": has_new,
        "latest_collected_at": latest.collected_at.isoformat(),
    }


@router.post("/check")
def check_notifications(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """알림 확인 처리 (last_notification_checked_at 갱신)"""
    user = db.query(User).filter(User.id == user_id).first()
    user.last_notification_checked_at = utcnow()
    db.commit()
    return {"checked_at": iso_utc(user.last_notification_checked_at)}


@router.get("/stream")
def notification_stream(request: Request):
    """SSE 스트림 — pg_notify LISTEN으로 새 수집 즉시 감지 (세션 쿠키 인증)"""
    # 스트림이 열려 있는 동안 커넥션 풀을 붙잡지 않도록 get_db 대신 인증 때만 세션을 연다
    with SessionLocal() as db:
        if resolve_user_id(db, request.cookies.get(SESSION_COOKIE)) is None:
            raise HTTPException(status_code=401, detail="Not authenticated")

    async def event_generator():
        settings = get_settings()
        conn = psycopg2.connect(settings.database_url)
        conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute("LISTEN new_collection;")

        try:
            loop = asyncio.get_running_loop()
            while True:
                # select를 executor에서 실행하여 async 블로킹 방지 (5초 타임아웃)
                ready = await loop.run_in_executor(
                    None, lambda: select.select([conn], [], [], 5.0)
                )
                if ready[0]:
                    conn.poll()
                    while conn.notifies:
                        notify = conn.notifies.pop(0)
                        yield sse_event({"type": "new_changes", "collected_at": notify.payload})
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
