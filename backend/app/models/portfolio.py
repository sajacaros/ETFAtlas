from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Numeric, Boolean, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from ..database import Base
from ..utils.encryption import EncryptedDecimal, EncryptedFloat


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False, default="My Portfolio")
    calculation_base = Column(String(20), nullable=False, default="CURRENT_TOTAL")
    target_total_amount = Column(Numeric(15, 2), nullable=True)
    display_order = Column(Integer, nullable=False, default=0)
    is_shared = Column(Boolean, nullable=False, default=False)
    share_token = Column(PG_UUID(as_uuid=True), unique=True, nullable=True)
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
    quantity = Column(EncryptedDecimal, nullable=False, default=0)
    avg_price = Column(EncryptedDecimal, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    portfolio = relationship("Portfolio", back_populates="holdings")


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    total_value = Column(EncryptedDecimal, nullable=False)
    prev_value = Column(EncryptedDecimal, nullable=True)
    change_amount = Column(EncryptedDecimal, nullable=True)
    change_rate = Column(EncryptedFloat, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint('portfolio_id', 'date', name='uq_portfolio_snapshot_date'),)

    portfolio = relationship("Portfolio", back_populates="snapshots")
