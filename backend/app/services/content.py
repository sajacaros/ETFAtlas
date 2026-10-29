"""슬롯 내용의 형식 — 프런트로 가는 JSON. 스킬은 이 형식으로만 결과를 내고, 프런트는 이 형식만 렌더링한다.

데이터 슬롯은 dataset(원시값 + 서식 힌트)과 view(어떻게 그릴지)로 나뉜다.
같은 dataset을 table로도 그릴 수 있어서, 프런트는 모르는 차트를 표로 대신 보여준다.
"""
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator

# 셀 값을 사람이 읽는 형태로 바꾸는 규칙 (변환은 프런트가 한다)
ValueFormat = Literal["text", "number", "percent", "krw", "price", "date"]


class DataField(BaseModel):
    key: str
    label: str
    format: ValueFormat = "number"


class Dataset(BaseModel):
    """rows의 값은 원시값. 행 단위 메타는 밑줄 키로 둔다:
    _format(행 서식, 열 서식보다 우선), _better("high"|"low", 비교 강조), _raw({key: 원래 값}, 점수화한 값의 원값).
    """
    fields: list[DataField]
    rows: list[dict[str, Any]]


class TableView(BaseModel):
    kind: Literal["table"] = "table"
    # list: 행이 대상(ETF·종목), compare: 행이 항목이고 열이 대상
    orientation: Literal["list", "compare"] = "list"


class LineView(BaseModel):
    kind: Literal["line"] = "line"
    x: str
    y: list[str]


class BarView(BaseModel):
    kind: Literal["bar"] = "bar"
    x: str
    y: list[str]
    horizontal: bool = False
    stacked: bool = False  # 계열을 한 막대에 쌓는다 (막대 길이 = 합계)


class DonutView(BaseModel):
    kind: Literal["donut"] = "donut"
    name: str
    value: str


class TreemapView(BaseModel):
    kind: Literal["treemap"] = "treemap"
    name: str
    value: str


class RadarView(BaseModel):
    kind: Literal["radar"] = "radar"
    axis: str
    series: list[str]
    max: float = 100


class IndicatorPanel(BaseModel):
    """봉차트 아래 보조지표 칸 하나. 칸이 여럿이면 프런트는 한 번에 하나만 보이고 넘겨 보게 한다."""
    label: str  # 칸 이름 (예: 'MACD(12,26,9)')
    lines: list[str]
    bars: Optional[str] = None  # 막대로 그릴 계열 (MACD 히스토그램)
    levels: list[float] = []  # 기준 가로선 (RSI 30·70)
    min: Optional[float] = None
    max: Optional[float] = None


class ChartRange(BaseModel):
    """화면에서 고르는 표시 기간. rows는 가장 긴 기간까지 오고, 프런트가 start(포함)부터 잘라 그린다."""
    label: str  # '1개월'
    start: str  # 첫 거래일 (기간 전 마지막 거래일)
    short: bool = False  # 데이터가 그 기간보다 짧아 처음부터 그린다


class CandlestickView(BaseModel):
    kind: Literal["candlestick"] = "candlestick"
    x: str
    open: str
    high: str
    low: str
    close: str
    volume: Optional[str] = None
    overlays: list[str] = []  # 가격 칸에 겹쳐 그릴 선 (이동평균, 볼린저 밴드)
    panels: list[IndicatorPanel] = []
    ranges: list[ChartRange] = []
    range: int = 0  # 처음 보이는 ranges 번호 (질문한 기간)


View = Annotated[
    Union[TableView, LineView, BarView, DonutView, TreemapView, RadarView, CandlestickView],
    Field(discriminator="kind"),
]

# 슬롯이 화면에 표시되는 방식. 레이아웃은 이것으로 스켈레톤 모양을 정한다
CHART_DISPLAYS = ("line", "bar", "donut", "treemap", "radar", "candlestick")
TEXT_DISPLAYS = ("text", "markdown")


def slot_type(display: str) -> str:
    """표시 방식 → 스켈레톤 종류 (text | markdown | table | chart)."""
    if display in CHART_DISPLAYS:
        return "chart"
    return display


def _view_keys(view: BaseModel) -> list[str]:
    keys: list[str] = []
    for name, value in view:
        if name in ("kind", "orientation", "horizontal", "stacked", "max", "label", "levels", "start", "short"):
            continue
        if isinstance(value, list):
            for item in value:
                keys.extend(_view_keys(item) if isinstance(item, BaseModel) else [item])
        elif isinstance(value, str):
            keys.append(value)
    return keys


class Source(BaseModel):
    label: str
    as_of: Optional[str] = None


class Signal(BaseModel):
    """지표 하나를 정해진 규칙으로 본 강세·약세 상태. 프런트는 화살표와 상태를 한 줄로, 규칙은 펼쳐 보게 한다."""
    key: str
    label: str
    level: Optional[int] = Field(None, ge=-2, le=2)  # 2 ▲▲ … −2 ▼▼, None이면 화살표 없이 상태만
    state: str
    rule: str


class DataContent(BaseModel):
    type: Literal["data"] = "data"
    dataset: Dataset
    view: View
    sources: list[Source] = []
    notes: list[str] = []
    signals: list[Signal] = []

    @model_validator(mode="after")
    def check_view_keys(self):
        known = {f.key for f in self.dataset.fields}
        missing = [k for k in _view_keys(self.view) if k not in known]
        if missing:
            raise ValueError(f"view가 dataset에 없는 필드를 가리킵니다: {missing}")
        return self


class TextContent(BaseModel):
    type: Literal["text", "markdown"]
    text: str
