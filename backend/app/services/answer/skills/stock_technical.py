"""stock_technical: 개별 종목의 차트 분석 — 봉차트에 이동평균·볼린저 밴드를 겹치고, 아래에 거래량과 보조지표 칸을 둔다.

지표는 스크리너와 같은 정의(flow.indicators)로 DB 일봉에서 계산한다. 이동평균·MACD가 화면 첫날부터 이어지게
보여 줄 기간보다 앞의 일봉까지 읽는다. 보조지표 칸(MACD·RSI·스토캐스틱)은 화면에 하나씩 넘겨 보지만,
해설에 넘기는 요약에는 모든 지표의 지금 상태를 숫자로 정해 담는다 — LLM은 문장만 쓴다.
"""
from typing import Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...flow import indicators as ind
from ...graph_service import GraphService
from ..resolver import EntityResolver
from ..schemas import CandlestickView, DataField, Dataset, IndicatorPanel, Source
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .common import Period, pct_change, period_base, period_days, period_label, period_span

DEFAULT_TECH_PERIOD = "6m"  # 120일선·MACD 교차를 읽으려면 한 달로는 짧다
WARMUP_DAYS = 200  # 화면 첫날 120일선에 필요한 거래일(약 170일)과 휴장일 여유
MA_PERIODS = (5, 20, 60, 120)
RSI_LEVELS = (30, 70)
STOCH_LEVELS = (20, 80)
TREND_DAYS = 3  # 히스토그램 증감을 보는 최근 거래일 수

PanelName = Literal["macd", "rsi", "stochastic"]

PANELS: Dict[str, IndicatorPanel] = {
    "macd": IndicatorPanel(label="MACD(12,26,9)", lines=["macd", "macd_signal"], bars="macd_hist"),
    "rsi": IndicatorPanel(label="RSI(14)", lines=["rsi"], levels=list(RSI_LEVELS), min=0, max=100),
    "stochastic": IndicatorPanel(label="스토캐스틱 슬로우(5,3,3)", lines=["stoch_k", "stoch_d"],
                                 levels=list(STOCH_LEVELS), min=0, max=100),
}

FIELDS = [
    DataField(key="date", label="날짜", format="date"),
    DataField(key="open", label="시가", format="price"),
    DataField(key="high", label="고가", format="price"),
    DataField(key="low", label="저가", format="price"),
    DataField(key="close", label="종가", format="price"),
    DataField(key="volume", label="거래량", format="number"),
    *[DataField(key=f"ma{n}", label=f"{n}일선", format="price") for n in MA_PERIODS],
    DataField(key="bb_upper", label="볼린저 상단", format="price"),
    DataField(key="bb_lower", label="볼린저 하단", format="price"),
    DataField(key="macd", label="MACD", format="number"),
    DataField(key="macd_signal", label="시그널", format="number"),
    DataField(key="macd_hist", label="히스토그램", format="number"),
    DataField(key="rsi", label="RSI", format="number"),
    DataField(key="stoch_k", label="%K", format="number"),
    DataField(key="stoch_d", label="%D", format="number"),
]


class StockTechnicalArgs(BaseModel):
    stock: str = Field(description="종목 이름 또는 6자리 코드 (하나)")
    period: Period = Field(DEFAULT_TECH_PERIOD, description=(
        "보여 줄 기간. 숫자+단위(d 일, w 주, m 개월, y 년) 또는 ytd. "
        f"질문에 기간이 있으면 그대로 적고, 없으면 기본값 {DEFAULT_TECH_PERIOD}(6개월)"))
    first: PanelName = Field("macd", description=(
        "처음 보이는 보조지표 칸. 질문이 RSI나 스토캐스틱을 콕 집으면 그것, 아니면 macd. 나머지 칸은 화면에서 넘겨 본다"))


def _pad(series: Sequence, total: int) -> List:
    """끝을 맞춘 지표 시계열을 일봉 길이로 — 앞쪽 계산할 수 없는 날은 None."""
    return [None] * (total - len(series)) + list(series)


def _r(v: Optional[float], digits: int = 2) -> Optional[float]:
    return None if v is None else round(v, digits)


def _price(v: float) -> str:
    return f"{v:,.0f}원"


def _cross_text(cross: Optional[tuple], up: str, down: str) -> str:
    if not cross:
        return "기간 중 교차 없음"
    kind, days = cross
    when = "마지막 거래일" if days == 0 else f"{days}거래일 전"
    return f"{up if kind == 'golden' else down} {when}"


def _zone(value: float, low: float, high: float) -> str:
    if value >= high:
        return f"과매수 기준({high:g} 이상) 구간"
    if value <= low:
        return f"과매도 기준({low:g} 이하) 구간"
    return f"중립 구간({low:g}~{high:g})"


def _hist_trend(values: Sequence[float], days: int = TREND_DAYS) -> str:
    """히스토그램의 최근 변화를 부호와 함께 — '값이 늘었다'만 주면 음수 영역에서 폭이 준 것인지 헷갈린다."""
    recent = list(values[-days - 1:])
    if len(recent) < days + 1:
        return "판단할 데이터 부족"
    if min(recent) < 0 < max(recent):
        return f"최근 {days}거래일 사이 0을 지남 (MACD선과 시그널선이 교차)"
    side = "양(+)" if recent[-1] > 0 else "음(−)"
    sizes = [abs(v) for v in recent]
    diffs = [b - a for a, b in zip(sizes, sizes[1:])]
    if all(d > 0 for d in diffs):
        return f"{side} 영역에서 폭이 최근 {days}거래일 연속 커짐 (두 선이 벌어짐)"
    if all(d < 0 for d in diffs):
        return f"{side} 영역에서 폭이 최근 {days}거래일 연속 줄어듦 (두 선이 좁혀짐)"
    return f"{side} 영역에서 최근 {days}거래일 폭이 커졌다 줄었다 함"


def _ma_lines(rows: List[Dict]) -> List[str]:
    last = rows[-1]
    close = last["close"]
    parts = []
    for n in MA_PERIODS:
        ma = last.get(f"ma{n}")
        if ma is not None:
            parts.append(f"{n}일선 {_price(ma)} {'위' if close > ma else '아래' if close < ma else '같음'}")
    lines = [f"[이동평균] 종가 {_price(close)} 기준: " + (", ".join(parts) if parts else "계산할 데이터 부족")]
    mas = [last.get(f"ma{n}") for n in MA_PERIODS]
    if all(m is not None for m in mas):
        if all(a > b for a, b in zip(mas, mas[1:])):
            lines.append("이평 배열: 정배열 (5일 > 20일 > 60일 > 120일)")
        elif all(a < b for a, b in zip(mas, mas[1:])):
            lines.append("이평 배열: 역배열 (5일 < 20일 < 60일 < 120일)")
        else:
            lines.append("이평 배열: 정배열도 역배열도 아님")
    pairs = [(r["ma5"], r["ma20"]) for r in rows if r.get("ma5") is not None and r.get("ma20") is not None]
    if pairs:
        cross = ind.last_cross([a for a, _ in pairs], [b for _, b in pairs])
        lines.append("5일선과 20일선 마지막 교차: " + _cross_text(cross, "골든크로스(5일선이 위로)", "데드크로스(5일선이 아래로)"))
    return lines


def _band_lines(rows: List[Dict], volumes: List[float]) -> List[str]:
    last = rows[-1]
    lines = []
    if last.get("bb_upper") is not None:
        width = last["bb_upper"] - last["bb_lower"]
        pctb = (last["close"] - last["bb_lower"]) / width * 100 if width else None
        lines.append(f"[볼린저 밴드(20,2)] 상단 {_price(last['bb_upper'])}, 하단 {_price(last['bb_lower'])}"
                     + (f", %B {pctb:.1f} (0이면 하단·100이면 상단, 밴드 밖이면 0 미만·100 초과)" if pctb is not None else ""))
    ratio = ind.volume_ratio(volumes)
    if ratio is not None:
        lines.append(f"[거래량] 마지막 거래일 거래량은 직전 20거래일 평균의 {ratio:.2f}배")
    return lines


def _macd_lines(rows: List[Dict]) -> List[str]:
    shown = [r for r in rows if r.get("macd") is not None]
    if not shown:
        return ["[MACD(12,26,9)] 계산할 데이터 부족"]
    last = shown[-1]
    cross = ind.last_cross([r["macd"] for r in shown], [r["macd_signal"] for r in shown])
    return [
        f"[MACD(12,26,9)] MACD선 {last['macd']:,.1f}, 시그널선 {last['macd_signal']:,.1f}, 히스토그램 {last['macd_hist']:,.1f} "
        f"(MACD선이 시그널선 {'위' if last['macd_hist'] > 0 else '아래'}, MACD선이 0선 {'위' if last['macd'] > 0 else '아래'})",
        "MACD선과 시그널선 마지막 교차: " + _cross_text(cross, "골든크로스(MACD선이 위로)", "데드크로스(MACD선이 아래로)"),
        "히스토그램(MACD선 − 시그널선): " + _hist_trend([r["macd_hist"] for r in shown]),
        "정의: MACD = 12일 EMA − 26일 EMA, 시그널 = MACD의 9일 EMA",
    ]


def _rsi_lines(rows: List[Dict]) -> List[str]:
    shown = [r for r in rows if r.get("rsi") is not None]
    if not shown:
        return ["[RSI(14)] 계산할 데이터 부족"]
    last = shown[-1]
    low, high = RSI_LEVELS
    top = max(shown, key=lambda r: r["rsi"])
    bottom = min(shown, key=lambda r: r["rsi"])
    lines = [f"[RSI(14)] 현재 {last['rsi']:.1f}, {_zone(last['rsi'], low, high)}"]
    if len(shown) > 5:
        lines.append(f"5거래일 전 {shown[-6]['rsi']:.1f}")
    lines += [
        f"기간 중 최고 {top['rsi']:.1f}({top['date']}), 최저 {bottom['rsi']:.1f}({bottom['date']}); "
        f"{high} 이상이었던 날 {sum(r['rsi'] >= high for r in shown)}거래일, {low} 이하였던 날 {sum(r['rsi'] <= low for r in shown)}거래일",
        f"정의: 14일 동안 상승폭과 하락폭의 상대 크기(Wilder 평활, 0~100). {high} 이상을 과매수, {low} 이하를 과매도로 보는 것이 관례",
    ]
    return lines


def _stoch_lines(rows: List[Dict]) -> List[str]:
    shown = [r for r in rows if r.get("stoch_k") is not None]
    if not shown:
        return ["[스토캐스틱 슬로우(5,3,3)] 계산할 데이터 부족"]
    last = shown[-1]
    low, high = STOCH_LEVELS
    ks, ds = [r["stoch_k"] for r in shown], [r["stoch_d"] for r in shown]
    cross = ind.last_cross(ks, ds)
    at = f" (교차한 날 %K {ks[len(ks) - 1 - cross[1]]:.1f})" if cross else ""
    return [
        f"[스토캐스틱 슬로우(5,3,3)] %K {last['stoch_k']:.1f}, %D {last['stoch_d']:.1f} "
        f"(%K가 %D {'위' if last['stoch_k'] > last['stoch_d'] else '아래'}), %K는 {_zone(last['stoch_k'], low, high)}",
        "%K와 %D 마지막 교차: " + _cross_text(cross, "골든크로스(%K가 위로)", "데드크로스(%K가 아래로)") + at,
        f"정의: %K = 최근 5거래일 가격 범위에서 종가의 위치(0~100)를 3일 평균, %D = %K의 3일 평균. "
        f"{high} 이상을 과매수, {low} 이하를 과매도로 보는 것이 관례",
    ]


class StockTechnicalSkill(DataSkill):
    name = "stock_technical"
    description = (
        "개별 주식 종목(ETF 아님) 하나의 차트 분석: 봉차트에 이동평균(5·20·60·120일)과 볼린저 밴드, 거래량, "
        "보조지표 칸(MACD·RSI·스토캐스틱을 넘겨 보며). 요약에 이평 위치·배열, 볼린저 %B, MACD 교차, RSI·스토캐스틱 구간을 담는다. "
        "주가 분석, 차트·기술적 분석, 보조지표(MACD·RSI·스토캐스틱·이평·볼린저)를 물을 때. "
        "주가 흐름(추이)만 보거나 여러 종목을 겹쳐 보면 stock_trend. 종목 하나만 받는다"
    )
    Args = StockTechnicalArgs
    displays = ("candlestick",)

    def fetch(self, args: StockTechnicalArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        stock = resolver.stock(db, args.stock)
        if not stock:
            return not_found(f"찾지 못한 종목: {args.stock}")
        name = stock["name"]
        prices = GraphService(db).get_stock_prices(stock["code"], days=period_days(args.period) + WARMUP_DAYS)
        bars = [p for p in prices if all(p.get(k) is not None for k in ("open", "high", "low", "close"))]
        if not bars:
            return empty(f"{name}의 가격 데이터가 없습니다")
        for b in bars:
            b["volume"] = b.get("volume") or 0

        n = len(bars)
        closes = [b["close"] for b in bars]
        mas = {p: _pad(ind.rolling_mean(closes, p), n) for p in MA_PERIODS}
        bands = _pad(ind.bollinger_series(closes), n)
        macd = ind.macd(closes)
        macd_line, macd_sig = (_pad(macd[0], n), _pad(macd[1], n)) if macd else ([None] * n, [None] * n)
        rsi = _pad(ind.rsi_series(closes), n)
        stoch = ind.stoch_slow(bars)
        stoch_k, stoch_d = (_pad(stoch[0], n), _pad(stoch[1], n)) if stoch else ([None] * n, [None] * n)

        # 가격 추이·기간 수익률과 같은 시작점(기간 전 마지막 거래일)부터 보여 준다
        base = period_base(bars, args.period)
        start = bars.index(base) if base else 0
        rows = []
        for i in range(start, n):
            b = bars[i]
            rows.append({
                "date": b["date"], **{k: b[k] for k in ("open", "high", "low", "close", "volume")},
                **{f"ma{p}": _r(mas[p][i]) for p in MA_PERIODS},
                "bb_upper": _r(bands[i][1]) if bands[i] else None,
                "bb_lower": _r(bands[i][2]) if bands[i] else None,
                "macd": _r(macd_line[i]), "macd_signal": _r(macd_sig[i]),
                "macd_hist": _r(macd_line[i] - macd_sig[i]) if macd_line[i] is not None else None,
                "rsi": _r(rsi[i]), "stoch_k": _r(stoch_k[i]), "stoch_d": _r(stoch_d[i]),
            })

        span = period_span(rows[0]["date"], rows[-1]["date"], period_label(args.period))
        notes = [span, "이동평균·보조지표는 기간 앞의 일봉까지 넣어 계산했습니다"]
        if not base:
            notes.append(f"요청한 기간보다 데이터가 짧습니다: {rows[0]['date']}부터")
        missing_ma = [p for p in MA_PERIODS if rows[0][f"ma{p}"] is None]
        if missing_ma:
            notes.append("데이터가 모자라 기간 첫날부터 그리지 못한 이평: " + ", ".join(f"{p}일선" for p in missing_ma))

        first, last = rows[0], rows[-1]
        summary_lines = [
            span + (f" — {notes[2]}" if not base else ""),
            f"{name}: 종가 {_price(first['close'])} → {_price(last['close'])} ({pct_change(first['close'], last['close']):+.2f}%), "
            f"기간 최고 {_price(max(r['high'] for r in rows))}, 최저 {_price(min(r['low'] for r in rows))}, 마지막 거래일 {last['date']}",
            *_ma_lines(rows),
            *_band_lines(rows, [b["volume"] for b in bars]),
            *_macd_lines(rows),
            *_rsi_lines(rows),
            *_stoch_lines(rows),
        ]

        available = {"macd": macd, "rsi": any(v is not None for v in rsi), "stochastic": stoch}
        order = [args.first, *[p for p in PANELS if p != args.first]]
        view = CandlestickView(
            x="date", open="open", high="high", low="low", close="close", volume="volume",
            overlays=[f"ma{p}" for p in MA_PERIODS if any(r[f"ma{p}"] is not None for r in rows)] + ["bb_upper", "bb_lower"],
            panels=[PANELS[p] for p in order if available[p]],
        )
        sources = [Source(label="종목 일별 시세", as_of=last["date"])]
        return data_result(Dataset(fields=FIELDS, rows=rows), view, "\n".join(summary_lines), sources, notes)
