from enum import Enum

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB

from ..database import Base
from ..utils.time import utcnow


class ChatLogStatus(str, Enum):
    PENDING = "pending"
    LIKED = "liked"
    DISLIKED = "disliked"
    APPROVED = "approved"
    REJECTED = "rejected"
    EMBEDDED = "embedded"


class ChatSession(Base):
    """챗봇 대화 세션. 최근 턴은 chat_logs 원문으로, 그 이전 턴은 summary로 기억한다."""
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    summary = Column(Text, nullable=True)
    # summary에 반영된 마지막 chat_logs.id (이 id까지의 턴은 요약으로만 기억)
    summarized_until_log_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow)


class ChatLog(Base):
    __tablename__ = "chat_logs"
    __table_args__ = (
        Index("idx_chat_logs_user_id", "user_id"),
        Index("idx_chat_logs_status", "status"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)  # 회원 삭제 후에도 로그는 남긴다
    # 세션을 지워도 로그(코드 예제 큐레이션 자료)는 남긴다
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    question = Column(Text, nullable=False)
    # 대화 맥락으로 대명사·생략을 풀어 쓴 독립 질문 (맥락이 없거나 바꿀 게 없으면 NULL)
    refined_question = Column(Text, nullable=True)
    answer = Column(Text, nullable=False)
    generated_code = Column(Text, nullable=True)
    # 실행 과정(도구 호출 step 목록). 세션을 다시 열 때 보여 준다
    steps = Column(JSONB, nullable=True)
    status = Column(String(20), default=ChatLogStatus.PENDING.value)
    created_at = Column(DateTime, default=utcnow)
