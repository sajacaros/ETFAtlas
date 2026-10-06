from sqlalchemy import Column, DateTime, Integer, Text
from ..database import Base
from ..utils.time import utcnow


class AISetting(Base):
    """LLM/임베딩 접속 설정. 한 행(id=1)만 쓴다 — 비어 있는 항목은 환경변수(LLM_API_BASE 등)를 쓴다.

    API 키는 ENCRYPTION_KEY로 암호화해 저장한다 (app.utils.encryption).
    """
    __tablename__ = "ai_settings"

    id = Column(Integer, primary_key=True)
    llm_api_base = Column(Text, nullable=True)
    llm_api_key = Column(Text, nullable=True)  # 암호문
    llm_model = Column(Text, nullable=True)
    embedding_api_base = Column(Text, nullable=True)
    embedding_api_key = Column(Text, nullable=True)  # 암호문
    embedding_model = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
