from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from ..database import Base
from ..utils.time import utcnow


class OpinionRun(Base):
    """주간 매수 의견 한 차례 (토요일 날짜). 맡은 프로세스가 종목마다 heartbeat_at을 갱신한다 — 오래 멈춰 있으면 다른 프로세스가 이어 맡는다."""
    __tablename__ = "opinion_runs"

    run_on = Column(Date, primary_key=True)
    status = Column(String(10), nullable=False)  # running | done
    started_at = Column(DateTime, nullable=False, default=utcnow)
    heartbeat_at = Column(DateTime, nullable=False, default=utcnow)
    finished_at = Column(DateTime, nullable=True)


class StockOpinion(Base):
    """한 차례의 종목별 매수 의견 (stock_opinion 스킬의 관점별 판정과 규칙이 정한 종합). rank는 디스코드로 알린 순위."""
    __tablename__ = "stock_opinions"

    run_on = Column(Date, ForeignKey("opinion_runs.run_on", ondelete="CASCADE"), primary_key=True)
    stock_code = Column(String(6), primary_key=True)
    name = Column(Text, nullable=False)
    verdict = Column(String(20), nullable=False)  # 사 볼 만하다 | 지켜본다 | 사지 않는 편이 낫다 | 판단 보류 | 실패
    score = Column(Float, nullable=True)  # 관점 평균 (-2 ~ 2)
    chart_rating = Column(String(10), nullable=True)
    financials_rating = Column(String(10), nullable=True)
    report_rating = Column(String(10), nullable=True)
    company_type = Column(Text, nullable=True)
    reasons = Column(JSONB, nullable=True)  # {chart: [..], financials: [..], report: [..], check: [..]}
    market_cap = Column(Float, nullable=True)
    rank = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
