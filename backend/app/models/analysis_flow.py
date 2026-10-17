from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB

from ..database import Base
from ..utils.time import utcnow


class AnalysisFlow(Base):
    """사용자가 저장한 분석 흐름: 노드와 연결(그래프 JSON). 실행 결과는 저장하지 않는다."""
    __tablename__ = "analysis_flows"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    graph = Column(JSONB, nullable=False)  # {"nodes": [{id, type, params, position}], "edges": [{id, source, target}]}
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
