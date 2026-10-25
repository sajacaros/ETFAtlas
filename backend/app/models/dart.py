from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text
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


class StockReport(Base):
    """색인한 정기보고서 (사업·반기·분기, 정정 포함). dart_report_index DAG가 채우고, 종목마다 최근 1년만 남긴다.
    status: pending(원문 받기 전) → tree(목차 트리만, 제목으로 고른다) → summarized(노드 요약까지) | failed
    | missing(DART가 원문을 주지 않는 접수번호 — 다시 받지 않고, 같은 기간의 그 전 접수를 대신 올린다).
    overview·breakdowns는 company_report·company_revenue_mix가 처음 물을 때 만들어 남기는 캐시 (NULL이면 아직)."""
    __tablename__ = "stock_reports"

    rcept_no = Column(String(14), primary_key=True)
    stock_code = Column(String(6), nullable=False, index=True)
    report_nm = Column(Text, nullable=False)  # '2026년 반기보고서', '2025년 사업보고서 (기재정정)'
    period = Column(String(7), nullable=True)  # 'YYYY.MM' — 정정보고서는 원래 보고서와 같다
    status = Column(String(12), nullable=False, default="pending")
    parser_version = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    indexed_at = Column(DateTime, nullable=True)
    summarized_at = Column(DateTime, nullable=True)
    overview = Column(Text, nullable=True)
    breakdowns = Column(Text, nullable=True)  # 원문 표에서 뽑아 검사를 통과한 매출 구성 (JSON 목록)
    model = Column(Text, nullable=True)  # overview를 만든 모델
    created_at = Column(DateTime, default=utcnow)


class StockReportDoc(Base):
    """DART에서 받은 원문 zip 그대로. 파서를 고치면 DART를 다시 부르지 않고 이것으로 트리를 다시 만든다."""
    __tablename__ = "stock_report_docs"

    rcept_no = Column(String(14), ForeignKey("stock_reports.rcept_no", ondelete="CASCADE"), primary_key=True)
    zip = Column(LargeBinary, nullable=False)
    fetched_at = Column(DateTime, default=utcnow)


class ReportNode(Base):
    """보고서 목차 트리의 노드 (장·절·주석, 긴 절은 '가.' 소제목마다 하위 노드). 본문은 blocks에 구조로 둔다 —
    [{kind: heading|para, text} | {kind: table, table: {caption, unit, header, rows}}] (app.services.report_tree).
    summary는 노드에 든 항목을 등록된 LLM이 한 줄로 적은 색인 — 목차에서 노드를 고를 때 쓴다."""
    __tablename__ = "report_nodes"

    rcept_no = Column(String(14), ForeignKey("stock_reports.rcept_no", ondelete="CASCADE"), primary_key=True)
    node_id = Column(String(24), primary_key=True)  # 원문 ATOCID, 나눈 하위 노드는 '27-5'
    parent_id = Column(String(24), nullable=True)
    seq = Column(Integer, nullable=False)  # 문서 순서
    level = Column(Integer, nullable=False)
    title = Column(Text, nullable=False)
    path = Column(Text, nullable=False)  # 'II. 사업의 내용 > 6. 주요계약 및 연구개발활동'
    chars = Column(Integer, nullable=False)
    blocks = Column(Text, nullable=False)
    content_hash = Column(String(40), nullable=False)
    summary = Column(Text, nullable=True)
    summary_model = Column(Text, nullable=True)
