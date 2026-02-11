from sqlalchemy import Column, Integer, String, DateTime, Date, Numeric, BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from pgvector.sqlalchemy import Vector
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

    holdings = relationship("ETFHolding", back_populates="etf", cascade="all, delete-orphan")
    embedding = relationship("ETFEmbedding", back_populates="etf", uselist=False, cascade="all, delete-orphan")


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    sector = Column(String(100))
    market_cap = Column(BigInteger)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    holdings = relationship("ETFHolding", back_populates="stock")


class ETFHolding(Base):
    __tablename__ = "etf_holdings"

    id = Column(Integer, primary_key=True, index=True)
    etf_id = Column(Integer, ForeignKey("etfs.id", ondelete="CASCADE"), nullable=False)
    stock_id = Column(Integer, ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    weight = Column(Numeric(7, 4))
    shares = Column(BigInteger)
    recorded_at = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    etf = relationship("ETF", back_populates="holdings")
    stock = relationship("Stock", back_populates="holdings")


class ETFPrice(Base):
    __tablename__ = "etf_prices"
    __table_args__ = (UniqueConstraint("etf_code", "date", name="uq_etf_prices_code_date"),)

    id = Column(Integer, primary_key=True, index=True)
    etf_code = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    open_price = Column(Numeric(12, 2))
    high_price = Column(Numeric(12, 2))
    low_price = Column(Numeric(12, 2))
    close_price = Column(Numeric(12, 2))
    volume = Column(BigInteger)
    nav = Column(Numeric(14, 2))           # 순자산가치 (NAV)
    market_cap = Column(BigInteger)         # 시가총액
    net_assets = Column(BigInteger)         # 순자산총액
    trade_value = Column(BigInteger)        # 거래대금
    created_at = Column(DateTime, default=datetime.utcnow)


class ETFEmbedding(Base):
    __tablename__ = "etf_embeddings"

    id = Column(Integer, primary_key=True, index=True)
    etf_id = Column(Integer, ForeignKey("etfs.id", ondelete="CASCADE"), nullable=False, unique=True)
    embedding = Column(Vector(1536))
    created_at = Column(DateTime, default=datetime.utcnow)

    etf = relationship("ETF", back_populates="embedding")
