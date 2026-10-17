from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, Numeric, Boolean, UniqueConstraint, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, ARRAY
from sqlalchemy.orm import relationship
import uuid
from ..database import Base
from ..utils.encryption import EncryptedDecimal, EncryptedFloat
from ..utils.time import utcnow


class Portfolio(Base):
    __tablename__ = "portfolios"
    __table_args__ = (CheckConstraint("cardinality(account_types) >= 1", name="ck_portfolios_account_types"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False, default="My Portfolio")
    calculation_base = Column(String(20), nullable=False, default="CURRENT_TOTAL")
    # 계좌 유형 태그: IRP(개인형 퇴직연금) / PENSION_SAVINGS(연금저축), 1개 이상. 유형마다 편입 조건이 다르다
    account_types = Column(ARRAY(String(20)), nullable=False, default=lambda: ["PENSION_SAVINGS"])
    target_total_amount = Column(Numeric(15, 2), nullable=True)
    display_order = Column(Integer, nullable=False, default=0)
    snapshot_enabled = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    user = relationship("User", back_populates="portfolios")
    target_allocations = relationship("TargetAllocation", back_populates="portfolio", cascade="all, delete-orphan")
    holdings = relationship("Holding", back_populates="portfolio", cascade="all, delete-orphan")
    snapshots = relationship("PortfolioSnapshot", back_populates="portfolio", cascade="all, delete-orphan")


class TargetAllocation(Base):
    __tablename__ = "target_allocations"
    __table_args__ = (UniqueConstraint("portfolio_id", "ticker"),)

    id = Column(Integer, primary_key=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(20), nullable=False)
    target_weight = Column(Numeric(7, 4), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    portfolio = relationship("Portfolio", back_populates="target_allocations")


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("portfolio_id", "ticker"),)

    id = Column(Integer, primary_key=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    ticker = Column(String(20), nullable=False)
    quantity = Column(EncryptedDecimal, nullable=False, default=0)
    avg_price = Column(EncryptedDecimal, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    portfolio = relationship("Portfolio", back_populates="holdings")


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"

    id = Column(Integer, primary_key=True)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    total_value = Column(EncryptedDecimal, nullable=False)
    prev_value = Column(EncryptedDecimal, nullable=True)
    change_amount = Column(EncryptedDecimal, nullable=True)
    change_rate = Column(EncryptedFloat, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint('portfolio_id', 'date', name='uq_portfolio_snapshot_date'),)

    portfolio = relationship("Portfolio", back_populates="snapshots")


class SharedPortfolio(Base):
    """공유 시점의 포트폴리오 구성을 그대로 담은 스냅샷. 원본을 고치거나 지워도 바뀌지 않는다."""
    __tablename__ = "shared_portfolios"
    __table_args__ = (CheckConstraint("cardinality(account_types) >= 1", name="ck_shared_portfolios_account_types"),)

    id = Column(Integer, primary_key=True)
    share_token = Column(PG_UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    portfolio_id = Column(Integer, ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    account_types = Column(ARRAY(String(20)), nullable=False)
    # [{"ticker": "069500", "weight": 40.0}, ...] — weight는 목표 비중(%)
    allocations = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=utcnow)
