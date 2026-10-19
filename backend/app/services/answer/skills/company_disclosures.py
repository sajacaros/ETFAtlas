from datetime import date, timedelta

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....models.dart import StockDisclosure
from ..resolver import EntityResolver
from .base import DataSkill, SkillResult, empty, not_found, text_result

DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
# 임원·주요주주가 주식을 사고팔 때마다 내는 보고서. 대형주는 공시의 대부분이라(삼성전자 90일 839건 중 805건) 기본으로 뺀다
INSIDER_REPORT = "임원ㆍ주요주주특정증권등소유상황보고서"


class CompanyDisclosuresArgs(BaseModel):
    stock: str = Field(description="종목 이름 또는 6자리 코드 (하나)")
    days: int = Field(90, ge=7, le=365, description="최근 며칠의 공시")
    limit: int = Field(15, ge=5, le=30, description="보여줄 공시 수 (최신순)")
    insider: bool = Field(False, description="임원·주요주주 지분 변동 보고서까지 보여줄지. 내부자 매매·임원 지분을 물을 때만 true")


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


class CompanyDisclosuresSkill(DataSkill):
    name = "company_disclosures"
    description = (
        "개별 종목(상장사)의 최근 DART 공시 목록: 접수일, 공시 제목(원문 링크), 제출인. "
        "기업 분석, 최근 공시·이슈·자사주·유상증자 등을 물을 때 (보고서 본문은 company_report). 종목 하나만 받는다"
    )
    Args = CompanyDisclosuresArgs
    displays = ("markdown",)

    def fetch(self, args: CompanyDisclosuresArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        stock = resolver.stock(db, args.stock)
        if stock is None:
            return not_found(f"종목을 찾지 못했습니다: {args.stock}")
        since = date.today() - timedelta(days=args.days)
        query = db.query(StockDisclosure).filter(StockDisclosure.stock_code == stock["code"])
        if query.first() is None:
            return empty(f"{stock['name']}의 DART 공시 데이터가 아직 없습니다")
        rows = (query.filter(StockDisclosure.rcept_dt >= since)
                .order_by(StockDisclosure.rcept_dt.desc(), StockDisclosure.rcept_no.desc()).all())
        hidden = 0
        if not args.insider:
            kept = [r for r in rows if INSIDER_REPORT not in r.report_nm]
            hidden, rows = len(rows) - len(kept), kept
        if not rows:
            return empty(f"{stock['name']}의 최근 {args.days}일 공시가 없습니다"
                         + (f" (임원·주요주주 지분 변동 보고서 {hidden}건 제외)" if hidden else ""))
        shown = rows[:args.limit]
        lines = ["| 접수일 | 공시 | 제출인 |", "|---|---|---|"]
        lines += [f"| {r.rcept_dt.isoformat()} | [{_cell(r.report_nm)}]({DART_VIEWER}{r.rcept_no}) | {_cell(r.flr_nm or '')} |"
                  for r in shown]
        more = f"최근 {args.days}일 공시 {len(rows)}건 중 최신 {len(shown)}건입니다. " if len(rows) > len(shown) else ""
        excluded = f"임원·주요주주 지분 변동 보고서 {hidden}건은 뺐습니다. " if hidden else ""
        lines += ["", f"{more}{excluded}출처: DART 전자공시 (제목을 누르면 원문이 열립니다)"]
        result = text_result("\n".join(lines), kind="markdown")
        # 해설에는 표 대신 날짜와 제목만 넘긴다 — 제목 말고는 공시 내용을 모른다
        result.summary = f"{stock['name']} 최근 {args.days}일 DART 공시 {len(rows)}건 (제목만, 본문은 읽지 않음" + \
            (f", 임원·주요주주 지분 변동 보고서 {hidden}건 제외" if hidden else "") + "):\n" + \
            "\n".join(f"- {r.rcept_dt.isoformat()} {r.report_nm}" for r in shown)
        return result
