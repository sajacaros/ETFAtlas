from sqlalchemy import Boolean, Column, DateTime, Float, Integer, Text
from ..database import Base
from ..utils.discord import DEFAULT_SETTINGS
from ..utils.time import utcnow


class DiscordSetting(Base):
    """디스코드 알림(비중변화·일일 리포트) 설정. 한 행(id=1)만 쓴다 — 행이 없으면 DAG는 환경변수 DISCORD_WEBHOOK_URL을 쓴다."""
    __tablename__ = "discord_settings"

    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, nullable=False, default=DEFAULT_SETTINGS["enabled"])
    webhook_url = Column(Text, nullable=True)
    threshold = Column(Float, nullable=False, default=DEFAULT_SETTINGS["threshold"])  # 이 값(%p)을 넘는 비중변화만 알린다
    added_threshold = Column(Float, nullable=False, default=DEFAULT_SETTINGS["added_threshold"])  # 신규편입은 이 값(%p)을 넘으면 알린다
    rise_threshold = Column(Float, nullable=False, default=DEFAULT_SETTINGS["rise_threshold"])  # 일일 리포트: 1일 수익률이 이 값(%) 이상인 ETF
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
