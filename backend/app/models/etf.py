from sqlalchemy import Column, Integer, String, DateTime, Date, Numeric, BigInteger
from datetime import datetime
from ..database import Base


class ETF(Base):
    __tablename__ = "etfs"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    issuer = Column(String(255))
    category = Column(String(100))
    net_assets = Column(BigInteger)
    expense_ratio = Column(Numeric(5, 4))
    inception_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
