from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from ..database import Base
from ..utils.time import utcnow


class LayoutExample(Base):
    """챗봇 레이아웃 플래너의 few-shot 예시: 질문 유형 → 화면 설계(슬롯 계획 JSON).
    질문은 고유명사를 뺀 일반화 질문으로 임베딩하고, 계획의 대상 이름은 <종목> 같은 자리표시자로 둔다."""
    __tablename__ = "layout_examples"

    id = Column(Integer, primary_key=True)
    question = Column(Text, nullable=False)
    question_generalized = Column(Text, nullable=True)
    plan = Column(Text, nullable=False)  # {"rows": [{"slots": [...]}]} — 플래너 출력과 같은 형식
    description = Column(Text, nullable=True)
    embedding = Column(Text, nullable=True)  # vector(768), managed via raw SQL
    status = Column(String(20), default="active")  # active: 임베딩 전, embedded: 검색 대상
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
