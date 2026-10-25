"""정기보고서 표 → 매출 구성 차트 (제품·부문·지역·주요 고객별).

표는 목차 트리의 블록(병합 셀을 푼 마크다운, app.services.report_tree)으로 받는다. 어느 행·열이 매출 구성인지는
회사마다 달라 규칙으로 고르지 않고 LLM이 정해진 형식으로 옮긴다. 대신 옮긴 값을 믿지 않는다:
  - 값은 원문에 적힌 그대로(쉼표 포함)여야 하고, 원문에 그 숫자가 다른 숫자의 일부가 아닌 채로 있어야 한다.
  - 항목 이름도 원문에 있는 셀 하나여야 한다 (여러 셀을 이어 붙이거나 지어낸 이름이면 표를 잘못 읽은 것이다).
  - 항목이 2개 이상, 모두 양수.
  - 합계가 원문에 있고 항목 합과 맞으면(내부거래 없이 나눈 표) 도넛, 아니면 막대 — 부분의 합이 전체가 아닌 표를
    도넛으로 그리면 비중이 틀린다.
"""
import json
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from ..llm import NO_THINKING, build_model
from ..schemas import BarView, DataField, Dataset, DonutView, Source
from .base import SkillResult, data_result

MAX_CHARTS = 2
DONUT_MAX_ITEMS = 8  # 이보다 많으면 도넛 조각이 읽히지 않아 막대로
TOTAL_TOLERANCE = 0.005  # 항목 합과 합계의 차이 (반올림)
PERCENT_TOLERANCE = 1.0  # 비중(%) 표의 항목 합과 100의 차이

KIND_LABEL = {"segment": "부문별 매출", "product": "제품별 매출", "region": "지역별 매출", "customer": "주요 고객별 매출"}
DEFAULT_ORDER = ("segment", "product", "region", "customer")
# 질문이 이런 말을 쓰면 그 구성을 먼저 보여 준다
QUESTION_KINDS = (
    (("고객", "매출처", "거래처", "납품"), "customer"),
    (("지역", "수출", "해외", "내수", "국가"), "region"),
    (("제품", "품목"), "product"),
    (("부문", "사업부"), "segment"),
)
_TOTAL_NAME = re.compile(r"^(합\s*계|총\s*계|소\s*계|계|total)$", re.I)

EXTRACT_PROMPT = """당신은 DART 정기보고서의 표에서 매출 구성을 옮겨 적습니다. 아래 '보고서 표'만 보고 답하세요.
- kind: segment(사업부문별), product(제품·품목·매출유형별), region(지역·국가·수출/내수별), customer(주요 고객·매출처별).
  같은 kind는 하나만, 표가 있는 kind만 넣으세요. 문장 속 숫자로 만들지 말고 표에서만 옮기세요.
- 한 구성의 items는 한 가지 기준으로만 나눈 것이어야 합니다. 제품×지역처럼 두 기준이 섞인 표(제품별 수출·내수)에서는
  한 기준의 소계·합계 행만 쓰세요. 영업부문 주석의 '제품과 용역에 대한 공시', '지역에 대한 공시'처럼 합계까지 한 줄에
  나온 표가 있으면 그것을 먼저 쓰세요.
- 표 머리말의 'A / B'는 위 단계 / 아래 단계 머리말입니다 (예: 'DX 부문 / 3개월', 'DX 부문 / 누적'). 3개월과 누적 열이 함께 있으면
  누적 열을 쓰고, period에 그 머리말을 적으세요 (예: '당반기 누적').
- 영업부문 주석의 '주요 고객에 대한 공시'에 고객별 수익 금액이 있으면 customer로 옮기세요.
- name은 표의 셀 글자 그대로 하나만 쓰세요 (예: 표에 '제품매출'이 있으면 '제품매출'). 셀을 이어 붙이거나 이름을 새로 짓지 마세요.
- 가장 최근 기간(이번 보고서 기간) 열의 값만 옮기세요. period에는 그 열 제목을 그대로 적습니다 (예: '제00기 반기', '당반기').
- value와 total은 표에 적힌 글자 그대로 옮기세요 (예: '1,234,567'). 단위를 바꾸거나 계산하지 마세요.
- 합계·소계·계 행은 items에 넣지 말고 total에 넣으세요. 합계 행이 없으면 total은 비웁니다.
- '부문간 내부거래 제거'처럼 음수(△, -)인 조정 행은 넣지 마세요.
- unit은 표의 (단위 : …) 그대로 (예: '천원', '백만원', '억원'). 금액 대신 비중(%)만 있는 표면 '%'.
- 고객 이름이 '고객 A'처럼 가려져 있으면 그대로 씁니다. 금액이 없는 고객 목록은 넣지 마세요.
- 해당하는 표가 없으면 breakdowns를 비웁니다."""


class ExtractedItem(BaseModel):
    name: str
    value: str = Field(description="표에 적힌 그대로 (쉼표 포함)")


class ExtractedBreakdown(BaseModel):
    kind: Literal["segment", "product", "region", "customer"]
    period: str
    unit: str
    items: List[ExtractedItem]
    total: Optional[str] = None


class Extraction(BaseModel):
    breakdowns: List[ExtractedBreakdown] = Field(default_factory=list)


def _in_source(value: str, source: str) -> bool:
    """그 숫자가 원문에 그대로 있는지 — '624,089'가 '69,624,089'의 일부로만 있으면 아니다."""
    return re.search(rf"(?<![\d,.]){re.escape(value)}(?![\d,.]*\d)", source) is not None


def _number(value: str) -> Optional[float]:
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def check(b: ExtractedBreakdown, source: str) -> Optional[Dict[str, Any]]:
    """검사를 통과한 구성 {kind, period, unit, items: [{name, value}], whole} 또는 None."""
    items, names = [], set()
    squashed = _squash(source)
    for item in b.items:
        name, raw = item.name.strip(), item.value.strip()
        if not name or _TOTAL_NAME.match(name) or name in names:
            continue
        if "|" in name or _squash(name) not in squashed:  # 표의 셀이 아닌 이름 — 표를 잘못 읽었다
            return None
        value = _number(raw)
        if value is None or value <= 0:  # 음수 조정 행(△)이나 숫자가 아닌 칸 — 그 행만 뺀다
            continue
        if not _in_source(raw, source):
            return None  # 하나라도 원문에 없는 값이면 표 전체를 믿지 않는다
        items.append({"name": name, "value": value})
        names.add(name)
    if len(items) < 2:
        return None
    total = sum(i["value"] for i in items)
    if b.unit.strip() == "%":
        whole = abs(total - 100) <= PERCENT_TOLERANCE
    else:
        stated = _number(b.total.strip()) if b.total and _in_source(b.total.strip(), source) else None
        whole = bool(stated) and abs(total - stated) <= stated * TOTAL_TOLERANCE
    return {"kind": b.kind, "period": b.period.strip(), "unit": b.unit.strip(), "items": items, "whole": whole}


async def extract(config, source: str) -> List[Dict[str, Any]]:
    """source: 매출·부문 절의 마크다운 (company_report.mix_sources). 값·이름 검사도 이 글에 대고 한다."""
    # 같은 보고서면 같은 표를 고르도록 (결과를 캐시하므로 한 번 빗나가면 그대로 남는다)
    agent = Agent(build_model(config), output_type=Extraction, instructions=EXTRACT_PROMPT,
                  model_settings={**NO_THINKING, "temperature": 0})
    result = await agent.run(f"## 보고서 표\n{source}")
    checked, kinds = [], set()
    for b in result.output.breakdowns:
        c = check(b, source)
        if c and c["kind"] not in kinds:
            checked.append(c)
            kinds.add(c["kind"])
    return checked


def dumps(breakdowns: List[Dict[str, Any]]) -> str:
    return json.dumps(breakdowns, ensure_ascii=False)


def choose(breakdowns: List[Dict[str, Any]], question: str) -> List[Dict[str, Any]]:
    """보여 줄 구성 (최대 MAX_CHARTS개): 질문이 묻는 구성을 먼저, 나머지는 부문 → 제품 → 지역 → 고객."""
    first = [kind for words, kind in QUESTION_KINDS if any(w in question for w in words)]
    order = list(dict.fromkeys([*first, *DEFAULT_ORDER]))
    by_kind = {b["kind"]: b for b in breakdowns}
    return [by_kind[k] for k in order if k in by_kind][:MAX_CHARTS]


def chart_title(stock_name: str, b: Dict[str, Any]) -> str:
    return f"{stock_name} {KIND_LABEL[b['kind']]} · {b['period']}"


def chart_display(b: Dict[str, Any]) -> str:
    return "donut" if b["whole"] and len(b["items"]) <= DONUT_MAX_ITEMS else "bar"


def chart_result(title: str, b: Dict[str, Any], source: Source) -> SkillResult:
    percent = b["unit"] == "%"
    total = sum(i["value"] for i in b["items"])
    rows = [{"name": i["name"], "value": i["value"], **({"share": round(i["value"] / total * 100, 1)}
                                                         if b["whole"] and not percent else {})}
            for i in b["items"]]
    fields = [DataField(key="name", label="구분", format="text"),
              DataField(key="value", label="비중" if percent else f"매출({b['unit']})",
                        format="percent" if percent else "number")]
    if b["whole"] and not percent:
        fields.append(DataField(key="share", label="비중", format="percent"))
    view = DonutView(name="name", value="value") if chart_display(b) == "donut" \
        else BarView(x="name", y=["value"], horizontal=True)
    unit = "%" if percent else b["unit"]
    summary = f"{title}: " + ", ".join(
        f"{r['name']} {r['value']:,.15g}{unit}" + (f"({r['share']}%)" if "share" in r else "") for r in rows)
    notes = [] if b["whole"] else ["항목을 더한 값이 총 매출과 같지 않습니다 (부문 간 내부거래 포함, 일부 항목만 공시 등)"]
    return data_result(Dataset(fields=fields, rows=rows), view, summary, [source], notes)
