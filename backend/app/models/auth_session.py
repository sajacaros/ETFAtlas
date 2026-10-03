from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from ..database import Base
from ..utils.time import utcnow


class AuthSession(Base):
    """로그인 세션. 쿠키의 랜덤 토큰은 SHA-256 해시로만 저장한다 — 로그아웃·사용자 삭제 시 행이 사라져 즉시 무효."""
    __tablename__ = "auth_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
