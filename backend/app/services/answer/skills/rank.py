from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from ...graph_service import GraphService
from ..resolver import EntityResolver
from ..schemas import BarView, DataField, Dataset, Source, TableView
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .common import format_value, node
from .etf_choice import _theme_etfs, _theme_word
from .period_returns import period_return
from .stock_holders import SAFE_CODE_RE

# 기준: (표시 이름, 서식, ETF만 되는지). 수익률은 마지막 거래일부터 거슬러 센 기간 (period_returns와 같은 계산)
METRICS = {
    "return_1w": ("1주 수익률", "percent", False),
    "return_1m": ("1개월 수익률", "percent", False),
    "return_3m": ("3개월 수익률", "percent", False),
    "return_6m": ("6개월 수익률", "percent", False),
    "return_1y": ("1년 수익률", "percent", False),
    "net_assets": ("순자산", "krw", True),
    "expense_ratio": ("총보수", "percent", True),
}
RETURN_DAYS = {"return_1w": 7, "return_1m": 30, "return_3m": 90, "return_6m": 180, "return_1y": 365}
MAX_TARGETS = 30


class RankArgs(BaseModel):
    kind: Literal["etf", "stock"] = Field(description="순위를 매길 대상의 종류. etf: ETF, stock: 개별 주식 종목")
    targets: List[str] = Field(default_factory=list, max_length=MAX_TARGETS, description=(
        "순위를 매길 후보. ETF·종목 이름이나 6자리 코드, 또는 앞 슬롯 결과의 참조('@이름.1-30'). theme과 함께 쓰지 않는다"
    ))
    theme: Optional[str] = Field(None, description="kind=etf일 때만: 업종·테마 이름(예: '2차전지') — 그 테마의 ETF 전체를 후보로")
    by: Literal[tuple(METRICS)] = Field(description=(
        "정렬 기준. return_1w/1m/3m/6m/1y: 기간 수익률, net_assets: 순자산(ETF만), expense_ratio: 총보수(ETF만)"
    ))
    order: Literal["desc", "asc"] = Field("desc", description="desc: 큰 값부터(가장 많이 오른, 가장 큰), asc: 작은 값부터(가장 낮은 보수)")
    min_value: Optional[float] = Field(None, description=(
        "이 값 이상만 남긴다 (수익률·총보수는 % 숫자, 순자산은 원). 남는 개수는 실행해 봐야 알므로, "
        "이 결과를 받는 슬롯은 나눠 만들지 말고 하나만 만든다"
    ))
    max_value: Optional[float] = Field(None, description="이 값 이하만 남긴다")
    top: int = Field(5, ge=1, le=MAX_TARGETS, description="남길 개수 (순위 순)")

    @model_validator(mode="after")
    def _one_source(self):
        if bool(self.targets) == bool(self.theme):
            raise ValueError("targets와 theme 중 하나만 적으세요")
        if self.theme and self.kind != "etf":
            raise ValueError("theme은 kind=etf일 때만 씁니다")
        if METRICS[self.by][2] and self.kind != "etf":
            raise ValueError(f"{self.by}는 ETF에만 있는 기준입니다")
        return self


class RankSkill(DataSkill):
    name = "rank"
    description = (
        "ETF나 종목 후보를 수치 기준(기간 수익률, 순자산, 총보수)으로 정렬·필터해 상위 N개를 고른다. "
        "후보는 앞 슬롯 결과의 참조('@이름.1-30')나 이름 목록, 또는 테마(ETF). 앞 슬롯은 후보를 넉넉히(top 최대) 내보내게 한다. "
        "'~ 중 수익률이 가장 높은 3개', '~ 중 보수가 가장 낮은 ETF', '테마 ETF 중 순자산 상위 3개', "
        "'구성종목 중 가장 많이 오른 5개'처럼 앞 결과를 앞 슬롯의 순서와 다른 기준으로 다시 골라야 할 때. "
        "고른 결과를 다음 슬롯이 다시 참조로 받는다. "
        "질문에 수익률·순자산·보수 같은 기준이 없으면 쓰지 않는다 — '많이 담은 ETF 상위 N개', '비중 상위 N개'는 "
        "앞 슬롯의 순서 그대로이므로 그 슬롯의 top과 참조('@이름.1')만 쓴다"
    )
    Args = RankArgs
    displays = ("bar", "table")
    exports = "ETF 또는 종목 목록, 정렬 기준 순 (필터를 통과한 것만)"

    def fetch(self, args: RankArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        graph = GraphService(db)
        missing: List[str] = []
        if args.theme:
            candidates = _theme_etfs(db, _theme_word(args.theme))
            if not candidates:
                return not_found(f"'{args.theme}' 테마의 ETF를 찾지 못했습니다")
        elif args.kind == "etf":
            candidates, missing = resolver.etfs(db, args.targets)
        else:
            candidates, missing = resolver.stocks(db, args.targets)
        if not candidates:
            return not_found(f"후보를 찾지 못했습니다: {', '.join(args.targets)}")

        label, fmt, _ = METRICS[args.by]
        values = self._values(graph, args, candidates)
        scored = [{"code": c["code"], "name": c["name"], "value": values.get(c["code"])} for c in candidates]
        no_data = [s["name"] for s in scored if s["value"] is None]
        scored = [s for s in scored if s["value"] is not None]
        if args.min_value is not None:
            scored = [s for s in scored if s["value"] >= args.min_value]
        if args.max_value is not None:
            scored = [s for s in scored if s["value"] <= args.max_value]
        scored.sort(key=lambda s: (s["value"], s["code"]), reverse=args.order == "desc")
        picked = scored[:args.top]
        target = "ETF" if args.kind == "etf" else "종목"
        if not picked:
            return empty(f"조건에 맞는 {target}가 없습니다 (후보 {len(candidates)}개)")

        dataset = Dataset(
            fields=[DataField(key="name", label=target, format="text"), DataField(key="code", label="코드", format="text"),
                    DataField(key="value", label=label, format=fmt)],
            rows=picked,
        )
        view = BarView(x="name", y=["value"], horizontal=True) if display == "bar" else TableView()
        direction = "높은" if args.order == "desc" else "낮은"
        condition = self._condition(args, fmt)
        summary = (f"후보 {target} {len(candidates)}개 중 {label} {direction} 순{condition} {len(picked)}개: "
                   + "; ".join(f"{p['name']} {format_value(p['value'], fmt)}" for p in picked))
        notes = []
        if len(picked) < args.top:
            notes.append(f"조건에 맞는 {target}가 {len(picked)}개뿐입니다")
        if no_data:
            notes.append(f"{label} 데이터가 없어 뺀 {target}: {', '.join(no_data)}")
        if missing:
            notes.append(f"찾지 못한 {target}: {', '.join(missing)}")
        source = "일별 종가" if args.by in RETURN_DAYS else "ETF 기본 정보"
        return data_result(dataset, view, summary, [Source(label=f"{target} {source}")], notes,
                           exports=[{"code": p["code"], "name": p["name"]} for p in picked])

    @staticmethod
    def _values(graph: GraphService, args: RankArgs, candidates: List[Dict]) -> Dict[str, Optional[float]]:
        if args.by in RETURN_DAYS:
            prices = graph.get_etf_prices if args.kind == "etf" else graph.get_stock_prices
            out = {}
            for c in candidates:
                series = [p for p in prices(c["code"], days=RETURN_DAYS[args.by] + 10) if p.get("close")]
                out[c["code"]] = period_return(series, RETURN_DAYS[args.by]) if series else None
            return out
        codes = ", ".join(repr(c["code"]) for c in candidates if SAFE_CODE_RE.fullmatch(c["code"]))
        rows = node(graph, f"MATCH (e:ETF) WHERE e.code IN [{codes}] RETURN {{code: e.code, value: e.{args.by}}}", {})
        return {r["code"]: (float(r["value"]) if r.get("value") is not None else None) for r in rows}

    @staticmethod
    def _condition(args: RankArgs, fmt: str) -> str:
        parts = []
        if args.min_value is not None:
            parts.append(f"{format_value(args.min_value, fmt)} 이상")
        if args.max_value is not None:
            parts.append(f"{format_value(args.max_value, fmt)} 이하")
        return f"({', '.join(parts)})" if parts else ""
