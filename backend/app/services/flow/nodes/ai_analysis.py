import asyncio
import logging
import re
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ....domain import indicators as ind
from ....domain.format import format_value
from ...llm import NO_THINKING, build_model
from ..base import FlowContext, Node, StockSet, result
from ..lookups import held_by

logger = logging.getLogger(__name__)

CONCURRENCY = 3  # LLM 프록시에 동시에 보내는 요청 수
HAN_RE = re.compile(r"[\u3400-\u9fff]")  # 모델이 가끔 한자·중국어 낱말을 섞는다

FOCUS = {
    "summary": "종합 — 추세·위치·거래량·ETF 편입을 고르게",
    "trend": "추세 — 이평·수익률·고가 위치 중심",
    "risk": "위험 — 과열·급등락·고가 대비 하락·거래량 이상 중심",
}

PROMPT = """당신은 ETF Atlas의 종목 분석 보조입니다. 주어진 '사실'만으로 이 종목이 앞 단계 조건을 통과한 근거를 정리합니다.
- 사실에 없는 수치·뉴스·실적·업황을 만들지 마세요. 모르는 것은 쓰지 않습니다.
- 매수·매도 권유, 목표가, 앞으로 오르거나 내릴 것이라는 예측은 쓰지 마세요.
- 한글로만 3문장 이내로 씁니다 (한자·중국어 낱말을 섞지 않습니다. RSI·ETF 같은 지표 이름은 그대로 씁니다). 첫 문장은 핵심 근거, 둘째는 수치로 본 특징, 셋째는 주의할 점(사실에서 보이는 위험).
- 지표는 적힌 정의대로만 해석하세요. 거래량 배수 = 마지막 날 거래량 ÷ 직전 20일 평균, 고가 대비 = 기간 최고가에서 몇 % 아래인지, 볼린저 %B = 0이면 하단 밴드·100이면 상단 밴드, 스토캐스틱 %K = 최근 5일 가격 범위에서 종가의 위치(0~100), 교차 후 일수 = 0이면 마지막 거래일에 교차.
- 담은 ETF는 몇 개 ETF가 얼마나 담았는지만 쓰고, 그것이 주가에 어떤 의미인지는 추측하지 마세요."""


class AIAnalysisParams(BaseModel):
    max_stocks: int = Field(10, ge=1, le=30, title="분석할 최대 종목 수", description="들어온 순서대로 앞에서부터. 나머지는 다음 노드로 넘기지 않는다")
    focus: Literal["summary", "trend", "risk"] = Field("summary", title="관점", json_schema_extra={"options": FOCUS})


def facts(row: Dict[str, Any], bars: List[ind.Bar], held_by: List[Dict], fields) -> List[str]:
    """LLM에 넘기는 사실 목록. 숫자는 여기서 정해지고 LLM은 문장만 쓴다."""
    lines = []
    for key, f in fields.items():
        if key != "ai" and row.get(key) is not None:
            lines.append(f"{f.label}: {format_value(row[key], f.format)}")
    if bars:
        closes = [b["close"] for b in bars]
        computed = {
            "기준일": bars[-1]["date"],
            "5일 수익률": ind.period_return(closes, 5),
            "20일 수익률": ind.period_return(closes, 20),
            "60일 수익률": ind.period_return(closes, 60),
            f"{len(bars)}일 고가 대비": ind.from_high(bars, len(bars)),
            "RSI(14)": ind.rsi(closes),
            "거래량 배수": ind.volume_ratio([b["volume"] for b in bars]),
            "이평 정배열(5>20>60)": ind.ma_aligned(closes),
            "변동성 수축(간이 VCP)": ind.is_vcp(bars),
            "볼린저 %B": ind.bollinger_pctb(closes),
        }
        stoch = ind.stoch_slow(bars)
        if stoch:
            computed["스토캐스틱 %K"] = stoch[0][-1]
        macd_lines = ind.macd(closes)
        if macd_lines:
            computed["MACD선이 시그널선 위"] = macd_lines[0][-1] > macd_lines[1][-1]
        shown = {line.split(":")[0] for line in lines}  # 앞 노드가 이미 계산한 값은 다시 넣지 않는다
        for label, v in computed.items():
            if v is None or label in shown:
                continue
            if isinstance(v, bool):
                v = "예" if v else "아니오"
            elif isinstance(v, float):
                v = f"{v:.2f}" + ("%" if "수익률" in label or "대비" in label else "")
            lines.append(f"{label}: {v}")
    if held_by:
        top = ", ".join(f"{h['etf']} {h['weight']:.2f}%" for h in held_by[:3])
        lines.append(f"담은 ETF 수: {len(held_by)}개 (비중 큰 순: {top})")
    else:
        lines.append("담은 ETF 수: 0개 (관리 중인 ETF의 상위 30개 구성종목에 없음)")
    return lines


class AIAnalysisNode(Node):
    type = "ai_analysis"
    label = "AI 분석"
    category = "ai"
    icon = "🤖"
    description = "종목마다 계산된 지표와 ETF 편입 정보를 LLM에 넘겨 근거를 3문장으로 정리한다. 숫자는 백엔드가 계산하고 LLM은 문장만 쓴다"
    Params = AIAnalysisParams

    async def run(self, params: AIAnalysisParams, inputs: List[StockSet], ctx: FlowContext):
        source = inputs[0]
        if not source.rows:
            yield result(source.derive({}))
            return
        if ctx.ai_config is None:
            raise ValueError("AI 설정이 없습니다")
        targets = list(source.rows.items())[: params.max_stocks]
        codes = [c for c, _ in targets]
        bars = await asyncio.to_thread(ctx.market.bars, codes)
        holders = await asyncio.to_thread(self._held_by, ctx, codes)

        agent = Agent(build_model(ctx.ai_config), instructions=PROMPT, model_settings=NO_THINKING)
        semaphore = asyncio.Semaphore(CONCURRENCY)

        async def analyze(code: str, row: Dict[str, Any]) -> tuple[str, str]:
            prompt = (
                f"## 종목\n{row.get('name')}({code})\n\n## 앞 단계 조건\n"
                + ("\n".join(n for n in source.notes if n.startswith("조건")) or "(없음)")
                + "\n\n## 사실\n" + "\n".join(f"- {line}" for line in facts(row, bars.get(code, []), holders.get(code, []), source.fields))
                + f"\n\n## 관점\n{FOCUS[params.focus]}"
            )
            async with semaphore:
                if ctx.stop.is_set():
                    return code, "중지됨"
                try:
                    text = (await agent.run(prompt)).output.strip()
                    if HAN_RE.search(text):  # 한 번만 다시 쓰게 한다
                        retry = await agent.run(prompt + "\n\n(앞 답에 한자가 섞였습니다. 한글로만 다시 쓰세요.)")
                        text = retry.output.strip()
                    return code, text
                except Exception:
                    logger.warning("AI analysis of %s failed", code, exc_info=True)  # 원인은 로그에만
                    return code, "분석 실패"

        tasks = [asyncio.create_task(analyze(code, row)) for code, row in targets]
        texts: Dict[str, str] = {}
        try:
            for done in asyncio.as_completed(tasks):
                code, text = await done
                texts[code] = text
                yield {"type": "progress", "message": f"{len(texts)}/{len(targets)} 분석"}
        finally:
            for t in tasks:
                t.cancel()

        items = source.derive({code: {**row, "ai": texts.get(code, "")} for code, row in targets})
        items.add_field("ai", "AI 근거 정리", "text")
        if len(source.rows) > len(targets):
            items.notes.append(f"{len(source.rows):,}종목 중 앞의 {len(targets)}종목만 분석했습니다")
        items.notes.append("AI 근거 정리는 계산된 지표를 문장으로 옮긴 것으로, 투자 권유가 아닙니다")
        yield result(items)

    @staticmethod
    def _held_by(ctx: FlowContext, codes: List[str]) -> Dict[str, List[Dict]]:
        db = ctx.session_factory()
        try:
            return held_by(db, codes)
        finally:
            db.close()

    @staticmethod
    def badge(items: StockSet) -> str:
        return f"{len(items.rows):,}종목 분석"
