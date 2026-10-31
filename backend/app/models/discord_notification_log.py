from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from ..database import Base
from ..utils.time import utcnow


class DiscordNotificationLog(Base):
    """디스코드로 보낸 알림 이력. DAG가 발송할 때마다 한 행을 남긴다."""
    __tablename__ = "discord_notification_logs"

    id = Column(Integer, primary_key=True)
    kind = Column(String(20), nullable=False, default="weight_change")  # weight_change | daily_report | chat_review
    base_date = Column(String(10), nullable=False, index=True)
    status = Column(String(10), nullable=False)  # sent | failed
    threshold = Column(Float, nullable=False)
    # [{etf_code, etf_name, prev_date, changes: [{stock_code, stock_name, change_type,
    #   previous_weight, current_weight, weight_change}]}]  (weight_change)
    # {rising: [{etf_code, etf_name, return_1d, holdings}], market_return, features: [str]}  (daily_report)
    # {issues: [...], failed_sessions: [...]}  (chat_review — 예전 행은 issue 목록)
    # 실패한 발송을 다시 할 때 LLM을 다시 부르지 않고 이 값으로 같은 메시지를 만든다
    items = Column(JSONB, nullable=False)
    # sent: 보낸 메시지 수, failed: 실패 전까지 보낸 수 (재시도는 그다음 메시지부터 보낸다)
    message_count = Column(Integer, nullable=False)
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=utcnow)
