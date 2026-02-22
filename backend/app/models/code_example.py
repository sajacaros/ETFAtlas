from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from datetime import datetime

from ..database import Base


class CodeExample(Base):
    __tablename__ = "code_examples"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    question_generalized = Column(Text, nullable=True)
    code = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    embedding = Column(Text, nullable=True)  # vector(1536), managed via raw SQL
    status = Column(String(20), default="active")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    source_chat_log_id = Column(Integer, ForeignKey("chat_logs.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
