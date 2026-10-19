import asyncio
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from sqlalchemy.orm import Session

from ....models.dart import StockDisclosure, StockFinancial, StockReportSummary
from ...dart_config import load_dart_key
from ...dart_document import extract_sections, fetch_document
from ..llm import NO_THINKING, build_model
from ..resolver import UnmanagedStock
from .base import Skill, SkillContext, SkillResult, empty, not_found, text_result, unmanaged_stock_result
from .company_disclosures import DART_VIEWER

# "반기보고서 (2026.06)", "[기재정정]사업보고서 (2025.12)" — 정정이 나오면 정정본이 완전한 최신 보고서다
PERIODIC = re.compile(r"^(?:\[([^\]]*)\]\s*)?(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)")
REPORT_LABEL = {"11013": "1분기보고서", "11012": "반기보고서", "11014": "3분기보고서", "11011": "사업보고서"}
# 공시 제목은 1·3분기를 모두 '분기보고서'라 쓴다. 주요계정에 같은 접수번호가 없으면 기간 끝 달로 가린다 (12월 결산 기준)
QUARTER_BY_MONTH = {"03": "1분기보고서", "09": "3분기보고서"}

REPORT_PROMPT = """당신은 DART 정기보고서 본문을 요약합니다. 아래 '보고서 본문'은 보고서에서 사업의 내용, 경영진단, 투자자 보호 사항, 영업부문 주석만 뽑은 것입니다.
- 본문에 있는 사실만 쓰세요. 본문에 없는 수치·전망·평가를 만들지 마세요.
- 수치는 본문에 적힌 숫자와 단위를 그대로 옮기세요 (예: '1,234,567백만원'). 단위를 조·억원으로 바꾸지 마세요 — 자릿수를 틀리기 쉽습니다. 본문 문장에 이미 '12조 3,456억원'처럼 적힌 값은 그대로 씁니다.
- 매수·매도 권유나 투자 의견은 쓰지 마세요.
- 제목(#, ##)이나 머리말 없이 바로 아래 형식으로 시작하세요. 항목마다 2~4개의 짧은 글머리표. 본문에 내용이 없는 항목은 통째로 빼세요.

#### 사업 구조
(무엇을 팔아 돈을 버는지, 제품·부문별 매출 비중)
#### 이번 기간 영업 상황
(가격·출하·수주·가동률 등 본문이 설명하는 실적 배경, 경영진 설명이 있으면 그 요지)
#### 위험 요인
(본문이 밝힌 시장·환율·금리·원재료 등 위험과 대응)
#### 소송·제재·기준일 이후 주요사항
(우발부채, 제재, 작성기준일 이후 발생한 주요사항, 진행 중인 공시사항)"""


class CompanyReportArgs(BaseModel):
    stock: str = Field(description="종목 이름 또는 6자리 코드 (하나)")


@dataclass
class Report:
    rcept_no: str
    report_nm: str

    @property
    def filed(self) -> str:
        return date(int(self.rcept_no[:4]), int(self.rcept_no[4:6]), int(self.rcept_no[6:8])).isoformat()


def report_name(title: Optional[str], financial: Optional[StockFinancial]) -> str:
    """'2026년 반기보고서', '2026년 1분기보고서', '2025년 사업보고서 (기재정정)'. 보고서 종류는 주요계정의 보고서 코드를 먼저 믿는다."""
    m = PERIODIC.match(title) if title else None
    if financial is not None and financial.reprt_code in REPORT_LABEL:
        name = f"{financial.bsns_year}년 {REPORT_LABEL[financial.reprt_code]}"
    elif m:
        kind = f"{m.group(2)}보고서" if m.group(2) != "분기" else QUARTER_BY_MONTH.get(m.group(4), "분기보고서")
        name = f"{m.group(3)}년 {kind}"
    else:
        name = "정기보고서"
    return f"{name} ({m.group(1)})" if m and m.group(1) else name


def latest_report(db: Session, stock_code: str) -> Optional[Report]:
    """가장 최근에 접수된 정기보고서 (사업·반기·분기, 정정 포함). 공시 목록과 주요계정 중 접수번호가 큰 쪽.
    공시 목록(최근 90일 백필)에 없으면 주요계정의 접수번호로 찾는다."""
    financials = {r.rcept_no: r for r in db.query(StockFinancial).filter(StockFinancial.stock_code == stock_code).all()
                  if r.rcept_no}
    titles = {r.rcept_no: r.report_nm for r in db.query(StockDisclosure).filter(StockDisclosure.stock_code == stock_code).all()
              if PERIODIC.match(r.report_nm)}
    if not financials and not titles:
        return None
    rcept_no = max([*financials, *titles])
    return Report(rcept_no, report_name(titles.get(rcept_no), financials.get(rcept_no)))


FOOTER = "\n\n_보고서 본문(사업의 내용·투자자 보호 사항 등)을 AI가 요약했습니다. 정확한 내용은 원문을 확인하세요._"


def _header(report: Report) -> str:
    # 보고서 이름은 영역 제목에 있다
    return f"{report.filed} 접수 · [DART 원문]({DART_VIEWER}{report.rcept_no})\n\n"


def _result(name: str, report: Report, summary: str) -> SkillResult:
    # 화면은 흘려받은 텍스트를 그대로 두므로 본문은 머리줄 + 요약 + 꼬리말, 흘려보낸 순서와 같게 만든다
    result = text_result(_header(report) + summary + FOOTER, kind="markdown")
    result.summary = f"{name}의 {report.report_nm} ({report.filed} 접수) 본문 요약:\n{summary}"
    return result


class CompanyReportSkill(Skill):
    name = "company_report"
    description = (
        "개별 종목(상장사)의 가장 최근 정기보고서(사업·반기·분기보고서) 본문 요약: 사업 구조와 제품별 매출 비중, "
        "이번 기간 영업 상황, 위험 요인, 소송·제재·기준일 이후 주요사항. 기업 분석, 무슨 사업을 하는지, "
        "보고서 내용을 물을 때. 종목 하나만 받는다. 처음 묻는 보고서는 원문을 읽느라 수십 초 걸린다"
    )
    Args = CompanyReportArgs
    displays = ("markdown",)

    def _prepare(self, args: CompanyReportArgs, ctx: SkillContext):
        """(종목, 보고서, 캐시된 요약 | None, 읽을 장 | None) 또는 결과(SkillResult)."""
        db = ctx.session_factory()
        try:
            try:
                stock = ctx.resolver.stock(db, args.stock)
            except UnmanagedStock as e:  # 그래프 밖의 회사면 무엇을 분석하는지와 함께 왜 안 되는지 알린다
                return unmanaged_stock_result(e)
            if stock is None:
                return not_found(f"종목을 찾지 못했습니다: {args.stock}")
            report = latest_report(db, stock["code"])
            if report is None:
                return empty(f"{stock['name']}의 정기보고서를 찾지 못했습니다 (DART 수집 전이거나 정기보고서를 내지 않는 종목)")
            cached = db.get(StockReportSummary, report.rcept_no)
            if cached is not None:
                return stock, report, cached.summary, None
            key = load_dart_key(db)
        finally:
            db.close()
        if not key:
            return empty("DART API 키가 없어 보고서 원문을 읽을 수 없습니다 (관리자 페이지에서 등록)")
        try:
            sections = extract_sections(fetch_document(key, report.rcept_no))
        except Exception as e:
            return SkillResult(status="failed", message=f"{report.report_nm} 원문을 읽지 못했습니다: {str(e)[:120]}")
        if not sections:
            return empty(f"{report.report_nm} 원문에서 사업의 내용을 찾지 못했습니다")
        return stock, report, None, sections

    def _save(self, ctx: SkillContext, stock_code: str, report: Report, sections, summary: str) -> None:
        db = ctx.session_factory()
        try:
            db.merge(StockReportSummary(rcept_no=report.rcept_no, stock_code=stock_code, report_nm=report.report_nm,
                                        sections="\n".join(s.path for s in sections), summary=summary,
                                        model=ctx.ai_config.llm_model))
            db.commit()
        finally:
            db.close()

    async def run(self, args: CompanyReportArgs, display: str, ctx: SkillContext):
        prepared = await asyncio.to_thread(self._prepare, args, ctx)
        if isinstance(prepared, SkillResult):
            yield prepared.event()
            return
        stock, report, cached, sections = prepared
        # 계획 단계에서는 어느 보고서인지 모르므로 영역 제목을 실제 보고서 이름으로 바꾼다
        yield {"type": "title", "title": f"{stock['name']} {report.report_nm} 요약"}
        if cached is not None:
            yield _result(stock["name"], report, cached).event()
            return

        body = "\n\n".join(f"## {s.path}\n{s.text}" for s in sections)
        prompt = f"## 보고서\n{stock['name']} {report.report_nm}\n\n## 보고서 본문\n{body}"
        agent = Agent(build_model(ctx.ai_config), instructions=REPORT_PROMPT, model_settings=NO_THINKING)
        yield {"type": "delta", "text": _header(report)}
        text = ""
        async with agent.run_stream(prompt) as result:
            async for delta in result.stream_text(delta=True):
                text += delta
                yield {"type": "delta", "text": delta}
                if ctx.stop.is_set():
                    break
        summary = text.strip()
        if not summary:
            yield SkillResult(status="failed", message=f"{report.report_nm}을(를) 요약하지 못했습니다").event()
            return
        yield {"type": "delta", "text": FOOTER}
        if not ctx.stop.is_set():  # 중간에 멈춘 요약은 남기지 않는다
            await asyncio.to_thread(self._save, ctx, stock["code"], report, sections, summary)
        yield _result(stock["name"], report, summary).event()
