import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from ....domain import indicators as ind
from ..base import FlowContext, Node, StockSet, result

MIN_BARS = 60  # 이보다 짧으면 지표를 믿기 어렵다 (60일 이평·VCP)
RETURN_DAYS = 20  # 수익률 조건·정렬의 기준 기간 (약 한 달). 옵션으로 두면 뜻이 헷갈려 고정한다


class ChartFilterParams(BaseModel):
    """값을 비우거나 끄면 그 조건은 보지 않는다. 켠 조건을 모두 만족하는 종목만 통과한다."""
    ma_aligned: bool = Field(False, title="이동평균 정배열", description="5일 > 20일 > 60일 이평")
    above_ma: Optional[int] = Field(None, ge=5, le=200, title="종가가 N일 이평 위", description="예: 20")
    high_days: int = Field(120, ge=20, le=250, title="고가 기준 기간(일)")
    near_high_pct: Optional[float] = Field(None, ge=0, le=50, title="고가 대비 하락폭 이내(%)", description="예: 10 → 고가에서 10% 안")
    return_min: Optional[float] = Field(None, title="20일 수익률 최소(%)", description="최근 종가 ÷ 20거래일 전 종가. 예: 5")
    return_max: Optional[float] = Field(None, title="20일 수익률 최대(%)")
    volume_ratio_min: Optional[float] = Field(None, ge=0, title="거래량 배수 이상", description="마지막 날 ÷ 직전 20일 평균. 예: 2")
    rsi_min: Optional[float] = Field(None, ge=0, le=100, title="RSI(14) 이상")
    rsi_max: Optional[float] = Field(None, ge=0, le=100, title="RSI(14) 이하")
    vcp: bool = Field(False, title="변동성 수축 (간이 VCP)", description="20일 구간 3개의 변동폭이 차례로 줄고 고가 근처, 거래량 감소")
    macd_cross_days: Optional[int] = Field(None, ge=1, le=20, title="MACD 골든크로스 N일 이내", description="MACD(12,26,9)가 시그널선을 위로 뚫고 지금도 위. 1이면 마지막 거래일에 교차")
    stoch_cross_days: Optional[int] = Field(None, ge=1, le=20, title="스토캐스틱 골든크로스 N일 이내", description="슬로우(5,3,3) %K가 %D를 위로 뚫고 지금도 위")
    stoch_cross_below: Optional[float] = Field(None, ge=0, le=100, title="교차 때 %K 이하", description="스토캐스틱 교차와 함께. 예: 20 → 과매도 구간에서 난 교차만")
    bb_pctb_min: Optional[float] = Field(None, title="볼린저 %B 이상", description="0 = 하단 밴드, 100 = 상단 밴드 (20일, 2σ). 예: 100 → 상단 돌파")
    bb_pctb_max: Optional[float] = Field(None, title="볼린저 %B 이하", description="예: 10 → 하단 밴드 근처")


def metrics(bars: List[ind.Bar], p: ChartFilterParams) -> Dict[str, Any]:
    closes = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]
    m: Dict[str, Any] = {
        "close": closes[-1],
        "ret": ind.period_return(closes, RETURN_DAYS),
        "from_high": ind.from_high(bars, p.high_days),
        "vol_ratio": ind.volume_ratio(volumes),
        "rsi": ind.rsi(closes),
        "ma_aligned": ind.ma_aligned(closes),
        "vcp": ind.is_vcp(bars),
        "bb_pctb": ind.bollinger_pctb(closes),
        "as_of": bars[-1]["date"],
    }
    lines = ind.macd(closes)
    m["macd_cross"] = ind.days_since_golden_cross(*lines) if lines else None
    stoch = ind.stoch_slow(bars)
    m["stoch_k"] = stoch[0][-1] if stoch else None
    m["stoch_cross"] = ind.days_since_golden_cross(*stoch) if stoch else None
    m["stoch_cross_k"] = stoch[0][-1 - m["stoch_cross"]] if m["stoch_cross"] is not None else None
    if p.above_ma:
        ma = ind.sma(closes, p.above_ma)
        m["ma_gap"] = (closes[-1] / ma - 1) * 100 if ma else None
    return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in m.items()}


def _ge(value: Optional[float], bound: float) -> bool:
    return value is not None and value >= bound


def _le(value: Optional[float], bound: float) -> bool:
    return value is not None and value <= bound


def _lt(value: Optional[float], bound: float) -> bool:
    return value is not None and value < bound


def _gt(value: Optional[float], bound: float) -> bool:
    return value is not None and value > bound


@dataclass(frozen=True)
class Condition:
    """조건 하나: 켜졌는지, 통과했는지(값이 없으면 통과하지 못한다), 사람이 읽는 문구(None이면 앞 조건 문구에 들어 있다)."""
    on: Callable[[ChartFilterParams], bool]
    check: Callable[[Dict[str, Any], ChartFilterParams], bool]
    text: Optional[Callable[[ChartFilterParams], str]]


# 판정과 문구를 한 줄에. 순서가 노트·AI 프롬프트의 조건 순서다
CONDITIONS = (
    Condition(lambda p: p.ma_aligned, lambda m, p: m["ma_aligned"] is True, lambda p: "이평 정배열(5>20>60)"),
    Condition(lambda p: bool(p.above_ma), lambda m, p: _gt(m.get("ma_gap"), 0),
              lambda p: f"종가 > {p.above_ma}일 이평"),
    Condition(lambda p: p.near_high_pct is not None, lambda m, p: _ge(m["from_high"], -p.near_high_pct),
              lambda p: f"{p.high_days}일 고가 대비 -{p.near_high_pct:g}% 이내"),
    Condition(lambda p: p.return_min is not None, lambda m, p: _ge(m["ret"], p.return_min),
              lambda p: f"{RETURN_DAYS}일 수익률 ≥ {p.return_min:g}%"),
    Condition(lambda p: p.return_max is not None, lambda m, p: _le(m["ret"], p.return_max),
              lambda p: f"{RETURN_DAYS}일 수익률 ≤ {p.return_max:g}%"),
    Condition(lambda p: p.volume_ratio_min is not None, lambda m, p: _ge(m["vol_ratio"], p.volume_ratio_min),
              lambda p: f"거래량 ≥ 20일 평균 × {p.volume_ratio_min:g}"),
    Condition(lambda p: p.rsi_min is not None, lambda m, p: _ge(m["rsi"], p.rsi_min), lambda p: f"RSI ≥ {p.rsi_min:g}"),
    Condition(lambda p: p.rsi_max is not None, lambda m, p: _le(m["rsi"], p.rsi_max), lambda p: f"RSI ≤ {p.rsi_max:g}"),
    Condition(lambda p: p.vcp, lambda m, p: m["vcp"] is True, lambda p: "변동성 수축(간이 VCP)"),
    Condition(lambda p: bool(p.macd_cross_days), lambda m, p: _lt(m["macd_cross"], p.macd_cross_days),
              lambda p: f"MACD 골든크로스 {p.macd_cross_days}거래일 이내"),
    Condition(lambda p: bool(p.stoch_cross_days), lambda m, p: _lt(m["stoch_cross"], p.stoch_cross_days),
              lambda p: f"스토캐스틱 골든크로스 {p.stoch_cross_days}거래일 이내"
                        + (f"(교차 때 %K ≤ {p.stoch_cross_below:g})" if p.stoch_cross_below is not None else "")),
    # 교차 때 %K는 스토캐스틱 교차와 함께만 본다 — 문구는 위 줄에 붙는다
    Condition(lambda p: bool(p.stoch_cross_days) and p.stoch_cross_below is not None,
              lambda m, p: _le(m["stoch_cross_k"], p.stoch_cross_below), None),
    Condition(lambda p: p.bb_pctb_min is not None, lambda m, p: _ge(m["bb_pctb"], p.bb_pctb_min),
              lambda p: f"볼린저 %B ≥ {p.bb_pctb_min:g}"),
    Condition(lambda p: p.bb_pctb_max is not None, lambda m, p: _le(m["bb_pctb"], p.bb_pctb_max),
              lambda p: f"볼린저 %B ≤ {p.bb_pctb_max:g}"),
)


def passes(m: Dict[str, Any], p: ChartFilterParams) -> bool:
    """켠 조건을 모두 통과해야 한다. 값이 없으면(기간 부족) 그 조건은 통과하지 못한다."""
    return all(c.check(m, p) for c in CONDITIONS if c.on(p))


def conditions(p: ChartFilterParams) -> List[str]:
    """켠 조건을 사람이 읽는 문구로 (노트와 AI 프롬프트에 쓴다)."""
    return [c.text(p) for c in CONDITIONS if c.on(p) and c.text]


class ChartFilterNode(Node):
    type = "chart_filter"
    label = "차트 필터"
    category = "filter"
    icon = "📈"
    description = "일봉(최근 1년, yfinance)으로 이평·고가 위치·수익률·거래량·RSI·변동성 수축·MACD·스토캐스틱·볼린저를 계산해 켠 조건을 모두 만족하는 종목만 남긴다"
    Params = ChartFilterParams

    async def run(self, params: ChartFilterParams, inputs: List[StockSet], ctx: FlowContext):
        source = inputs[0]
        yield {"type": "progress", "message": f"{len(source.rows):,}종목 일봉 받는 중"}
        bars = await asyncio.to_thread(ctx.market.bars, list(source.rows))

        computed: Dict[str, Dict[str, Any]] = {}
        short = 0
        for code, row in source.rows.items():
            b = bars.get(code)
            if not b or len(b) < MIN_BARS:
                short += 1
                continue
            m = metrics(b, params)
            if passes(m, params):
                computed[code] = {**row, **m}

        # 수익률 높은 순 (값 없는 종목은 뒤로)
        ordered = dict(sorted(computed.items(), key=lambda kv: -(kv[1]["ret"] if kv[1]["ret"] is not None else -1e9)))
        items = source.derive(ordered)
        items.add_field("close", "종가", "price")
        items.add_field("ret", f"{RETURN_DAYS}일 수익률", "percent")
        items.add_field("from_high", f"{params.high_days}일 고가 대비", "percent")
        items.add_field("vol_ratio", "거래량 배수")
        items.add_field("rsi", "RSI(14)")
        if params.above_ma:
            items.add_field("ma_gap", f"{params.above_ma}일 이평 대비", "percent")
        if params.macd_cross_days:
            items.add_field("macd_cross", "MACD 교차 후 일수")
        if params.stoch_cross_days:
            items.add_field("stoch_k", "스토캐스틱 %K")
            items.add_field("stoch_cross", "스토캐스틱 교차 후 일수")
        if params.bb_pctb_min is not None or params.bb_pctb_max is not None:
            items.add_field("bb_pctb", "볼린저 %B")
        items.add_field("as_of", "기준일", "date")
        cond = conditions(params)
        items.notes.append(f"조건: {', '.join(cond)}" if cond else "켠 조건이 없어 모든 종목이 통과했습니다")
        if short:
            items.notes.append(f"일봉이 {MIN_BARS}일보다 짧거나 받지 못한 {short}종목은 제외했습니다")
        yield result(items)
