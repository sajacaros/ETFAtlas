from sqlalchemy import Column, Integer, Date, DateTime
from ..database import Base
from ..utils.time import utcnow


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id = Column(Integer, primary_key=True, index=True)
    collected_at = Column(Date, nullable=False, unique=True)
    created_at = Column(DateTime, default=utcnow)
