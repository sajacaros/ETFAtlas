"""stock_opinion: '살까 말까'에 차트·재무·보고서 세 관점으로 의견을 낸다.

앞 슬롯(stock_technical, company_financials·company_valuation, company_report)의 요약을 LLM이 관점마다 읽어
판정과 근거를 내고, 종합 의견은 그 판정으로 규칙이 정한다 (app/domain/opinion.py) — LLM이 종합을 바꾸지 못한다.
narrative는 투자 의견을 쓰지 않으므로 이 스킬이 해설 자리를 대신한다.
"""
from typing import List, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ....domain.opinion import RATINGS, combine
from ...llm import NO_THINKING, build_model
from .base import Skill, SkillContext, empty, text_result

PERSPECTIVES = (("chart", "차트 분석"), ("financials", "재무 분석"), ("report", "보고서 분석"))

OPINION_PROMPT = """당신은 ETF Atlas의 종목 의견 담당입니다. 사용자가 종목을 살지 말지 묻고, 화면에는 이미 차트·실적·밸류에이션·정기보고서 영역이 있습니다.
'화면 데이터 요약'을 세 관점으로 나눠 관점마다 판정(…_rating)과 근거(…_reasons)를 내세요.
- chart(차트 분석): 차트 분석 영역의 이동평균·볼린저·거래량·MACD·RSI·스토캐스틱 값과 '신호(… 기준)' 줄.
- financials(재무 분석): 실적 영역(매출·영업이익·순이익·영업이익률의 추이, 전년 동기 대비, 부채비율)과 밸류에이션 영역(PER·PBR·ROE).
- report(보고서 분석): 정기보고서 영역의 사업 구조·영업 상황·위험 요인·소송·제재.
판정은 긍정 / 다소 긍정 / 중립 / 다소 부정 / 부정 중 하나, 그 관점의 데이터가 요약에 없거나 비었으면 '판단 불가'입니다.
- 근거는 요약에 있는 사실·수치만 1~3개, 한 문장씩. 요약에 없는 수치·사건·업황·목표가를 만들지 마세요.
- 차트 신호는 그 기준 이름을 함께 쓰세요 (예: '미너비니 기준 추세 템플릿 충족'). 앞으로 오를지 내릴지는 예측하지 마세요.
- PER·PBR이 높고 낮은지는 요약에 있는 그 회사의 값·ROE·실적 추이로만 말하고, 업종 평균을 지어내지 마세요.
- 한 관점 안에서 좋은 점과 나쁜 점이 섞이면 무게를 따져 '다소'나 '중립'으로 판정하세요.
- check에는 사기 전에 확인할 위험·변수를 요약에 근거해 1~3개 적으세요.
- 판단 불가인 관점의 근거에는 왜 판단하지 못했는지 한 문장만."""

Rating = Literal[RATINGS]

DISCLAIMER = ("> ETF Atlas가 모은 데이터(시세·DART 실적·정기보고서)를 정해진 관점으로 읽은 참고 의견이며, 투자 권유가 아닙니다. "
              "업황·수급·뉴스는 보지 않았습니다. 투자 판단과 책임은 본인에게 있습니다.")


REASONS = "요약에 있는 사실·수치로 쓴 근거 1~3개, 한 문장씩"


class Opinion(BaseModel):
    # 관점마다 판정과 근거를 평평하게 둔다 — 중첩 객체는 작은 모델이 JSON 문자열로 내보내 검증에 걸린다
    chart_rating: Rating
    chart_reasons: List[str] = Field(description=REASONS)
    financials_rating: Rating
    financials_reasons: List[str] = Field(description=REASONS)
    report_rating: Rating
    report_reasons: List[str] = Field(description=REASONS)
    check: List[str] = Field(default_factory=list, description="사기 전에 확인할 위험·변수 1~3개")


class StockOpinionArgs(BaseModel):
    stock: str = Field(description="의견을 낼 종목 이름 또는 6자리 코드 (하나). 같은 종목의 차트·실적·밸류에이션·보고서 슬롯과 함께 쓴다")


def render(stock: str, opinion: Opinion) -> str:
    ratings = {label: getattr(opinion, f"{key}_rating") for key, label in PERSPECTIVES}
    verdict = combine(ratings)
    lines = [f"### 종합: {verdict.label}",
             " · ".join(f"{label} **{rating}**" for label, rating in ratings.items()),
             "",
             f"{stock}: {verdict.reason}. (긍정 +2 ~ 부정 −2점의 평균, +1 이상이면 '사 볼 만하다', −1 이하면 '사지 않는 편이 낫다', "
             "'부정'인 관점이 하나라도 있으면 사 볼 만하다고 하지 않는다)"]
    for key, label in PERSPECTIVES:
        lines += ["", f"**{label} — {ratings[label]}**", *(f"- {r}" for r in getattr(opinion, f"{key}_reasons"))]
    if opinion.check:
        lines += ["", "**사기 전에 확인할 것**", *(f"- {c}" for c in opinion.check)]
    lines += ["", DISCLAIMER]
    return "\n".join(lines)


class StockOpinionSkill(Skill):
    name = "stock_opinion"
    description = (
        "종목을 '살까 말까', '사도 될까', '매수해도 돼?'처럼 매수 의견을 물을 때만 쓰는 스킬. "
        "같은 종목의 stock_technical(차트), company_financials·company_valuation(재무), company_report(보고서, need 없이) "
        "슬롯을 앞에 두고 마지막 줄에 이것 하나 — narrative 대신 해설 자리를 맡는다 (narrative는 매수 의견을 쓰지 않는다). "
        "세 관점마다 긍정~부정 판정과 근거, 판정으로 규칙이 정한 종합 의견(사 볼 만하다·지켜본다·사지 않는 편이 낫다)"
    )
    Args = StockOpinionArgs
    displays = ("markdown",)
    subject = "stock"
    entity_args = {"stock": "stock"}
    uses_llm = True
    after_others = True

    async def run(self, args: StockOpinionArgs, display: str, ctx: SkillContext):
        data = "\n\n".join(f"[{title}]\n{summary}" for title, summary in ctx.related if summary)
        if not data:
            yield empty("차트·실적·보고서 데이터가 없어 의견을 내지 못했습니다").event()
            return
        prompt = f"## 사용자 질문\n{ctx.question}\n\n## 종목\n{args.stock}\n\n## 화면 데이터 요약\n{data}"
        agent = Agent(build_model(ctx.ai_config), output_type=Opinion, instructions=OPINION_PROMPT,
                      model_settings={**NO_THINKING, "temperature": 0})
        result = await agent.run(prompt)
        yield text_result(render(args.stock, result.output), kind="markdown").event()
