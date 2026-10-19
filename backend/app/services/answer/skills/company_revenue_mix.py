import asyncio

from pydantic import BaseModel, Field

from . import report_breakdowns
from .base import Skill, SkillContext, SkillResult, empty
from .company_report import chart_events, load_breakdowns, prepare_report


class CompanyRevenueMixArgs(BaseModel):
    stock: str = Field(description="종목 이름 또는 6자리 코드 (하나)")


class CompanyRevenueMixSkill(Skill):
    name = "company_revenue_mix"
    description = (
        "개별 종목(상장사)의 가장 최근 정기보고서 표에 나온 매출 구성 — 주요 고객(매출처)·제품·사업부문·지역(수출/내수)별 "
        "매출을 차트로. 질문이 묻는 구성부터 최대 2개, 실행 중에 스스로 영역을 나눈다. 주요 고객·매출처·매출 구성만 물을 때 "
        "(보고서 요약 전체는 company_report). 고객 이름은 보고서가 가린 대로('고객 A') 나온다. 종목 하나만 받는다. "
        "처음 묻는 보고서는 원문을 읽느라 십여 초 걸린다"
    )
    Args = CompanyRevenueMixArgs
    displays = ("bar", "donut")

    async def run(self, args: CompanyRevenueMixArgs, display: str, ctx: SkillContext):
        prepared = await asyncio.to_thread(
            prepare_report, args.stock, ctx, lambda c: c.breakdowns is not None, lambda c: False)
        if isinstance(prepared, SkillResult):
            yield prepared.event()
            return
        stock, report, cached, sections = prepared
        breakdowns = await load_breakdowns(ctx, stock["code"], report, cached, sections)
        charts = report_breakdowns.choose(breakdowns, ctx.question)
        if not charts:
            yield empty(f"{stock['name']}의 {report.report_nm} 표에서 매출 구성(고객·제품·부문·지역별)을 찾지 못했습니다").event()
            return
        for event in chart_events(stock["name"], report, charts):
            yield event
