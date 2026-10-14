from sqlalchemy import Column, DateTime, String, Text
from ..database import Base
from ..utils.time import utcnow


class DiscordWatchETF(Base):
    """디스코드 비중변화 알림 대상 ETF. 관리자 페이지에서 추가·삭제한다."""
    __tablename__ = "discord_watch_etfs"

    etf_code = Column(String(20), primary_key=True)
    etf_name = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
