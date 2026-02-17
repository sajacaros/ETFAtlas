from sqlalchemy import Column, Integer, Date, DateTime
from datetime import datetime
from ..database import Base


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id = Column(Integer, primary_key=True, index=True)
    collected_at = Column(Date, nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
