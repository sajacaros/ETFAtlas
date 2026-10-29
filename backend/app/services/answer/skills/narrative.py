from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ...llm import NO_THINKING, build_model
from .base import Skill, SkillContext, text_result

NARRATIVE_PROMPT = """당신은 ETF Atlas의 AI 어시스턴트입니다. 화면에는 이미 표와 차트가 표시되어 있고, 당신은 그 해설을 씁니다.
- 아래 '화면 데이터 요약'에 있는 사실만 쓰세요. 요약에 없는 수치를 만들지 마세요.
- 한국어로, 지시가 없으면 3~5문장. 표를 다시 그리지 말고 핵심 차이와 특징을 설명하세요.
- 매수·매도 권유, 투자 의견, "어떤 투자자에게 적합하다" 같은 적합성 판단은 쓰지 마세요. 차이만 사실대로 설명합니다.
- 지지선·저항선, 추세 전환 예측, 목표가 같은 기술적 분석 해석은 하지 마세요. 가격은 기간 동안 오르고 내린 사실만 씁니다.
- 보조지표(이동평균·MACD·RSI·스토캐스틱·볼린저 밴드)는 요약에 적힌 값·정의·기준대로 지금 상태만 설명하고, 앞으로 오르내릴지는 쓰지 마세요.
- 요약에 '신호(… 기준)' 줄이 있으면 그 지표를 설명할 때 신호와 근거가 된 기준을 함께 쓰세요 (예: '와인스타인 기준 4단계(하락)로 강한 약세', '엘더 기준 히스토그램이 0 아래에서 위로 꺾여 강한 강세'). 신호는 정해진 규칙으로 본 상태이지 매수·매도 판단이 아닙니다.
- 점수나 지표는 요약에 적힌 정의대로만 해석하세요.
- 데이터가 없거나 부족하면 그렇다고 쓰세요."""


class NarrativeArgs(BaseModel):
    instruction: str = Field(description="무엇을 쓸지 (예: '두 ETF의 차이를 3문장으로 요약')")


class NarrativeSkill(Skill):
    name = "narrative"
    description = "다른 슬롯들의 데이터를 바탕으로 쓰는 해설·요약 텍스트. 데이터 슬롯이 있을 때 마지막에 하나"
    Args = NarrativeArgs
    displays = ("text",)
    after_others = True

    async def run(self, args: NarrativeArgs, display: str, ctx: SkillContext):
        data = "\n\n".join(f"[{title}]\n{summary}" for title, summary in ctx.related if summary) or "(데이터 없음)"
        prompt = f"## 사용자 질문\n{ctx.question}\n\n## 화면 데이터 요약\n{data}\n\n## 작성 지시\n{args.instruction}"
        agent = Agent(build_model(ctx.ai_config), instructions=NARRATIVE_PROMPT, model_settings=NO_THINKING)
        text = ""
        async with agent.run_stream(prompt) as result:
            async for delta in result.stream_text(delta=True):
                text += delta
                yield {"type": "delta", "text": delta}
                if ctx.stop.is_set():
                    break
        yield text_result(text.strip()).event()
