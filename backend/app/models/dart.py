from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, String, Text
from ..database import Base
from ..utils.time import utcnow


class DartSetting(Base):
    """DART OpenAPI 키. 한 행(id=1)만 쓴다 — 환경변수 대체는 없다.

    키는 ENCRYPTION_KEY로 암호화해 저장한다 (app.utils.encryption).
    """
    __tablename__ = "dart_settings"

    id = Column(Integer, primary_key=True)
    api_key = Column(Text, nullable=True)  # 암호문
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class DartCorp(Base):
    """DART 고유번호 전체 (corpCode.xml). stock_code가 있으면 상장사. dart_sync DAG가 채운다."""
    __tablename__ = "dart_corps"

    corp_code = Column(String(8), primary_key=True)
    corp_name = Column(Text, nullable=False)
    stock_code = Column(String(6), nullable=True)
    modify_date = Column(String(8), nullable=True)


class StockFinancial(Base):
    """주요계정(fnlttMultiAcnt) 원본. 분기·반기·3분기 보고서의 amount는 3개월 값, amount_cum은 누적.
    사업보고서(11011)는 amount가 연간 값이다 — 4분기는 연간 − 3분기 누적으로 계산한다."""
    __tablename__ = "stock_financials"

    stock_code = Column(String(6), primary_key=True)
    bsns_year = Column(Integer, primary_key=True)
    reprt_code = Column(String(5), primary_key=True)  # 11013 1분기, 11012 반기, 11014 3분기, 11011 사업보고서
    fs_div = Column(String(3), primary_key=True)  # CFS 연결, OFS 별도
    account = Column(Text, primary_key=True)  # 매출액, 영업이익, 당기순이익, 자산총계, 부채총계, 자본총계
    amount = Column(BigInteger, nullable=True)
    amount_cum = Column(BigInteger, nullable=True)
    rcept_no = Column(String(14), nullable=True)
    fetched_at = Column(DateTime, default=utcnow)


class StockDisclosure(Base):
    """그래프에 있는 종목의 DART 공시 목록 (list.json)."""
    __tablename__ = "stock_disclosures"

    rcept_no = Column(String(14), primary_key=True)
    stock_code = Column(String(6), nullable=False)
    corp_code = Column(String(8), nullable=False)
    report_nm = Column(Text, nullable=False)
    rcept_dt = Column(Date, nullable=False)
    flr_nm = Column(Text, nullable=True)
    rm = Column(Text, nullable=True)
