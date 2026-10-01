from sqlalchemy import Column, Integer, String, DateTime
from ..database import Base
from ..utils.time import utcnow


class ETF(Base):
    __tablename__ = "etfs"

    id = Column(Integer, primary_key=True)
    code = Column(String(20), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
