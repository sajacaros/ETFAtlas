from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from ..database import Base
from ..utils.time import utcnow


class AnalysisFlow(Base):
    """사용자가 저장한 종목 스크리너(분석 흐름): 노드와 연결(그래프 JSON). 고른 종목은 날마다 FlowRun에 남는다."""
    __tablename__ = "analysis_flows"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    graph = Column(JSONB, nullable=False)  # {"nodes": [{id, type, params, position}], "edges": [{id, source, target}]}
    schedule_enabled = Column(Boolean, nullable=False, default=False)  # 영업일 장 마감 뒤 자동 실행
    notify = Column(Boolean, nullable=False, default=False)  # 자동 실행 결과의 변화를 디스코드로 알린다
    last_scheduled_on = Column(Date, nullable=True)  # 자동 실행을 마친(또는 맡은) 날 — 하루 한 번만 돈다
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class FlowRun(Base):
    """저장한 흐름이 그날 고른 종목 (결과 노드에 닿은 종목). 흐름·날짜마다 한 행, 같은 날 다시 돌리면 덮어쓴다."""
    __tablename__ = "flow_runs"
    __table_args__ = (UniqueConstraint("flow_id", "run_date", name="uq_flow_runs_flow_date"),)

    id = Column(Integer, primary_key=True)
    flow_id = Column(Integer, ForeignKey("analysis_flows.id", ondelete="CASCADE"), nullable=False)
    run_date = Column(Date, nullable=False)  # 한국 날짜. 채점은 이 날 다음 거래일 종가에 샀다고 친다
    trigger = Column(String(10), nullable=False)  # manual | schedule
    picks = Column(JSONB, nullable=False)  # [{code, name}] 표시 순서
    created_at = Column(DateTime, default=utcnow)
