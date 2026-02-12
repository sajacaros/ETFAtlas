from sqlalchemy import Column, Integer, String, DateTime, Date, Float, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from ..database import Base


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False, default="My Portfolio")
    calculation_base = Column(String(20), nullable=False, default="CURRENT_TOTAL")
    target_total_amount = Column(Numeric(15, 2), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="portfolios")
    target_allocations = relationship("TargetAllocation", back_populates="portfolio", cascade="all, delete-orphan")
    holdings = relationship("Holding", back_populates="portfolio", cascade="all, delete-orphan")
    snapshots = relationship("PortfolioSnapshot", back_populates="portfolio", cascade="all, delete-orphan")


class TargetAllocation(Base):
    __tablename__ = "target_allocations"
    __table_args__ = (UniqueConstraint("portfolio_id", "ticker"),)

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(20), nullable=False)
    target_weight = Column(Numeric(7, 4), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    portfolio = relationship("Portfolio", back_populates="target_allocations")


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("portfolio_id", "ticker"),)

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(20), nullable=False)
    quantity = Column(Numeric(15, 4), nullable=False, default=0)
    avg_price = Column(Numeric(12, 2), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    portfolio = relationship("Portfolio", back_populates="holdings")


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    total_value = Column(Numeric(15, 2), nullable=False)
    prev_value = Column(Numeric(15, 2), nullable=True)
    change_amount = Column(Numeric(15, 2), nullable=True)
    change_rate = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint('portfolio_id', 'date', name='uq_portfolio_snapshot_date'),)

    portfolio = relationship("Portfolio", back_populates="snapshots")
