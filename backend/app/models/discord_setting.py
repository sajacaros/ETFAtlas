from sqlalchemy import Boolean, Column, DateTime, Float, Integer, Text
from ..database import Base
from ..utils.time import utcnow


class DiscordSetting(Base):
    """디스코드 비중변화 알림 설정. 한 행(id=1)만 쓴다 — 행이 없으면 DAG는 환경변수 DISCORD_WEBHOOK_URL을 쓴다."""
    __tablename__ = "discord_settings"

    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=True)
    webhook_url = Column(Text, nullable=True)
    threshold = Column(Float, nullable=False, default=3.0)  # 이 값(%p)을 넘는 비중변화만 알린다
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
