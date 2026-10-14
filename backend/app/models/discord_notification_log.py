from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from ..database import Base
from ..utils.time import utcnow


class DiscordNotificationLog(Base):
    """디스코드로 보낸 비중변화 알림 이력. DAG가 발송할 때마다 한 행을 남긴다."""
    __tablename__ = "discord_notification_logs"

    id = Column(Integer, primary_key=True)
    base_date = Column(String(10), nullable=False, index=True)
    status = Column(String(10), nullable=False)  # sent | failed
    threshold = Column(Float, nullable=False)
    # [{etf_code, etf_name, prev_date, changes: [{stock_code, stock_name, change_type,
    #   previous_weight, current_weight, weight_change}]}]
    items = Column(JSONB, nullable=False)
    message_count = Column(Integer, nullable=False)
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=utcnow)
