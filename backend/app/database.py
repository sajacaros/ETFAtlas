from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import get_settings

settings = get_settings()

# DATABASE_URL은 psycopg2.connect()에서도 직접 쓰므로 postgresql:// 형태를 유지하고,
# SQLAlchemy 2.1+의 기본 드라이버(psycopg3) 대신 psycopg2를 명시한다.
engine = create_engine(
    settings.database_url.replace("postgresql://", "postgresql+psycopg2://", 1),
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
