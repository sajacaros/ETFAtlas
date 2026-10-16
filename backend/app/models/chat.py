from enum import Enum

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index, PrimaryKeyConstraint
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


class ChatLogResult(str, Enum):
    """답변을 어떻게 마쳤는지. status(평가·예제 검수)와는 별개다."""
    RUNNING = "running"  # 답변을 만드는 중 (서버가 도중에 죽으면 그대로 남는다)
    COMPLETED = "completed"  # 일부 영역이 비거나 실패해도 답을 냈으면 완료
    CANCELLED = "cancelled"  # 사용자가 중지했다
    FAILED = "failed"  # 오류가 났거나 모든 영역이 실패했다
    CLARIFYING = "clarifying"  # 대상을 정하지 못해 되물었다


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
    # 답변 화면 구성 (column/row/slot 트리). 슬롯 내용은 chat_slots. NULL이면 answer 마크다운만 있는 예전 답변
    layout = Column(JSONB, nullable=True)
    status = Column(String(20), default=ChatLogStatus.PENDING.value)
    result = Column(String(20), nullable=False, default=ChatLogResult.COMPLETED.value)
    created_at = Column(DateTime, default=utcnow)


class ChatSlot(Base):
    """답변 화면 한 영역의 내용. 슬롯이 끝나는 대로 저장되고, 프런트는 완료 알림을 받으면 여기서 가져간다."""
    __tablename__ = "chat_slots"
    __table_args__ = (PrimaryKeyConstraint("chat_log_id", "slot_id"),)

    chat_log_id = Column(Integer, ForeignKey("chat_logs.id", ondelete="CASCADE"), nullable=False)
    slot_id = Column(String(20), nullable=False)
    skill = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)  # pending | running | complete | empty | failed | stopped
    content = Column(JSONB, nullable=True)
    # 대화 기억·요약 텍스트에 넘기는 짧은 요약
    summary = Column(Text, nullable=True)
    message = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
