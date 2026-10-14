from sqlalchemy import Column, DateTime, Float, Integer, String, Text, UniqueConstraint
from ..database import Base
from ..utils.time import utcnow


class WeightChange(Base):
    """액티브 ETF 보유종목의 직전 영업일 대비 비중 변화. Airflow가 수집 후 계산해 넣는다.

    변화가 있는 종목은 크기와 상관없이 모두 담고, 기준값(%p)은 읽는 쪽(웹·디스코드)이 적용한다.
    """
    __tablename__ = "weight_changes"
    __table_args__ = (
        UniqueConstraint("base_date", "etf_code", "stock_code", name="uq_weight_changes_date_etf_stock"),
    )

    id = Column(Integer, primary_key=True)
    base_date = Column(String(10), nullable=False, index=True)
    prev_date = Column(String(10), nullable=False)  # 이 ETF의 직전 영업일 (HOLDS가 있는 이전 날짜)
    etf_code = Column(String(20), nullable=False)
    etf_name = Column(Text, nullable=False)
    stock_code = Column(String(20), nullable=False)
    stock_name = Column(Text, nullable=False)
    change_type = Column(String(10), nullable=False)  # added | removed | increased | decreased
    previous_weight = Column(Float, nullable=False)
    current_weight = Column(Float, nullable=False)
    weight_change = Column(Float, nullable=False)


class WeightChangeDate(Base):
    """비중 변화 계산을 마친 기준일. 변화가 하나도 없던 날도 남겨 다시 계산하지 않게 한다."""
    __tablename__ = "weight_change_dates"

    base_date = Column(String(10), primary_key=True)
    computed_at = Column(DateTime, default=utcnow)
