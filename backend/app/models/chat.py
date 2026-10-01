from enum import Enum

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index

from ..database import Base
from ..utils.time import utcnow


class ChatLogStatus(str, Enum):
    PENDING = "pending"
    LIKED = "liked"
    DISLIKED = "disliked"
    APPROVED = "approved"
    REJECTED = "rejected"
    EMBEDDED = "embedded"


class ChatLog(Base):
    __tablename__ = "chat_logs"
    __table_args__ = (
        Index("idx_chat_logs_user_id", "user_id"),
        Index("idx_chat_logs_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    generated_code = Column(Text, nullable=True)
    status = Column(String(20), default=ChatLogStatus.PENDING.value)
    created_at = Column(DateTime, default=utcnow)
