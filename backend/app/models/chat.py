from enum import Enum

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from datetime import datetime

from ..database import Base


class ChatLogStatus(str, Enum):
    PENDING = "pending"
    LIKED = "liked"
    DISLIKED = "disliked"
    APPROVED = "approved"
    REJECTED = "rejected"
    EMBEDDED = "embedded"


class ChatLog(Base):
    __tablename__ = "chat_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    generated_code = Column(Text, nullable=True)
    status = Column(String(20), default=ChatLogStatus.PENDING.value, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
