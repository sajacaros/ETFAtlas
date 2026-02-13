from sqlalchemy import Column, String, Date, Numeric, DateTime, PrimaryKeyConstraint
from datetime import datetime
from ..database import Base


class TickerPrice(Base):
    __tablename__ = "ticker_prices"
    __table_args__ = (PrimaryKeyConstraint("ticker", "date"),)

    ticker = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    price = Column(Numeric(18, 2), nullable=False)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
