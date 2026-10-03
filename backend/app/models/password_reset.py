from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from ..database import Base
from ..utils.time import utcnow


class PasswordReset(Base):
    """관리자가 만든 비밀번호 재설정 링크. 토큰은 SHA-256 해시로만 저장하고, 한 번 쓰면(used_at) 다시 쓸 수 없다."""
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
