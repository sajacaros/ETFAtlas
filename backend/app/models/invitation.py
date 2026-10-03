from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from ..database import Base
from ..utils.time import utcnow


class Invitation(Base):
    """멤버 초대 링크. 한 번 쓰면(used_at) 다시 쓸 수 없고 expires_at이 지나면 무효."""
    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True)
    token = Column(String(64), unique=True, nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    used_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
