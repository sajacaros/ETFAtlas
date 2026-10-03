"""로그인 세션 쿠키. 쿠키에는 랜덤 토큰만 담고(HttpOnly), 서버는 auth_sessions의 해시와 대조한다."""
import hashlib
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models.auth_session import AuthSession
from .time import utcnow

settings = get_settings()

SESSION_COOKIE = "etf_atlas_session"
COOKIE_PATH = "/api"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user_id: int) -> str:
    """세션을 만들고 쿠키에 넣을 원본 토큰을 반환한다. 만료된 세션도 이때 정리한다."""
    now = utcnow()
    db.query(AuthSession).filter(AuthSession.expires_at <= now).delete()
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=now + timedelta(minutes=settings.session_expire_minutes),
    ))
    db.commit()
    return token


def revoke_session(db: Session, token: str) -> None:
    db.query(AuthSession).filter(AuthSession.token_hash == hash_token(token)).delete()
    db.commit()


def resolve_user_id(db: Session, token: Optional[str]) -> Optional[int]:
    if not token:
        return None
    row = db.query(AuthSession.user_id).filter(
        AuthSession.token_hash == hash_token(token),
        AuthSession.expires_at > utcnow(),
    ).first()
    return row[0] if row else None


def get_current_user_id(request: Request, db: Session = Depends(get_db)) -> int:
    user_id = resolve_user_id(db, request.cookies.get(SESSION_COOKIE))
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user_id


# SameSite=Lax + JSON 요청으로 CSRF를 막는다. https로 서비스하면 COOKIE_SECURE=true
def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=settings.session_expire_minutes * 60,
        path=COOKIE_PATH, httponly=True, secure=settings.cookie_secure, samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path=COOKIE_PATH, httponly=True, secure=settings.cookie_secure, samesite="lax",
    )
