import re
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from ...graph_service import GraphService
from ..resolver import EntityResolver
from ..schemas import BarView, DataField, Dataset, Source, TableView
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .common import (DEFAULT_PERIOD, PERIOD_DESCRIPTION, Period, format_value, node, pct_change, period_base, period_days,
                     period_label, period_span)
from .etf_choice import _theme_etfs, _theme_word
from .stock_holders import SAFE_CODE_RE

# 기준: (표시 이름, 서식, ETF만 되는지). 수익률은 마지막 거래일부터 period만큼 거슬러 센다 (period_returns와 같은 계산)
METRICS = {
    "return": ("수익률", "percent", False),
    "net_assets": ("순자산", "krw", True),
    "expense_ratio": ("총보수", "percent", True),
    "dividend_yield": ("분배율(최근 12개월)", "percent", True),
}
# 예전 계획(레이아웃 예시 등)의 'return_1m' 같은 기준은 by=return + period로 읽는다
LEGACY_RETURN = re.compile(r"return_(\w+)")
MAX_TARGETS = 30


class RankArgs(BaseModel):
    kind: Literal["etf", "stock"] = Field(description="순위를 매길 대상의 종류. etf: ETF, stock: 개별 주식 종목")
    targets: List[str] = Field(default_factory=list, max_length=MAX_TARGETS, description=(
        "순위를 매길 후보. ETF·종목 이름이나 6자리 코드, 또는 앞 슬롯 결과의 참조('@이름.1-30'). theme과 함께 쓰지 않는다. "
        "kind=etf에서 targets와 theme을 모두 비우면 관리하는 ETF 전체가 후보"
    ))
    theme: Optional[str] = Field(None, description="kind=etf일 때만: 업종·테마 이름(예: '2차전지') — 그 테마의 ETF 전체를 후보로")
    by: Literal[tuple(METRICS)] = Field(description=(
        "정렬 기준. return: 기간 수익률(기간은 period), net_assets: 순자산(ETF만), expense_ratio: 총보수(ETF만), "
        "dividend_yield: 최근 12개월 분배율(ETF만, '배당률'·'배당 수익률'도 이것)"
    ))
    period: Period = Field(DEFAULT_PERIOD, description="by=return일 때만: " + PERIOD_DESCRIPTION)
    order: Literal["desc", "asc"] = Field("desc", description="desc: 큰 값부터(가장 많이 오른, 가장 큰), asc: 작은 값부터(가장 낮은 보수)")
    min_value: Optional[float] = Field(None, description=(
        "이 값 이상만 남긴다 (수익률·총보수·분배율은 % 숫자, 순자산은 원). 남는 개수는 실행해 봐야 알므로, "
        "이 결과를 받는 슬롯은 나눠 만들지 말고 하나만 만든다"
    ))
    max_value: Optional[float] = Field(None, description="이 값 이하만 남긴다")
    top: int = Field(5, ge=1, le=MAX_TARGETS, description="남길 개수 (순위 순)")

    @model_validator(mode="before")
    @classmethod
    def _legacy_return(cls, data):
        if isinstance(data, dict) and isinstance(data.get("by"), str):
            match = LEGACY_RETURN.fullmatch(data["by"])
            if match:
                data = {**data, "by": "return", "period": match.group(1)}
        return data

    @model_validator(mode="after")
    def _one_source(self):
        if self.targets and self.theme:
            raise ValueError("targets와 theme 중 하나만 적으세요")
        if not self.targets and not self.theme and self.kind != "etf":
            raise ValueError("종목은 targets로 후보를 적으세요")
        if self.theme and self.kind != "etf":
            raise ValueError("theme은 kind=etf일 때만 씁니다")
        if METRICS[self.by][2] and self.kind != "etf":
            raise ValueError(f"{self.by}는 ETF에만 있는 기준입니다")
        return self


class RankSkill(DataSkill):
    name = "rank"
    description = (
        "ETF나 종목 후보를 수치 기준(기간 수익률, 순자산, 총보수, 분배율)으로 정렬·필터해 상위 N개를 고른다. "
        "후보는 앞 슬롯 결과의 참조('@이름.1-30')나 이름 목록, 또는 테마(ETF). 앞 슬롯은 후보를 넉넉히(top 최대) 내보내게 한다. "
        "'~ 중 수익률이 가장 높은 3개', '~ 중 보수가 가장 낮은 ETF', '테마 ETF 중 순자산 상위 3개', "
        "'구성종목 중 가장 많이 오른 5개'처럼 앞 결과를 앞 슬롯의 순서와 다른 기준으로 다시 골라야 할 때, "
        "'분배율 5% 이상 ETF'처럼 ETF 전체를 수치로 거를 때. "
        "고른 결과를 다음 슬롯이 다시 참조로 받는다. "
        "질문에 수익률·순자산·보수·분배율 같은 기준이 없으면 쓰지 않는다 — '많이 담은 ETF 상위 N개', '비중 상위 N개'는 "
        "앞 슬롯의 순서 그대로이므로 그 슬롯의 top과 참조('@이름.1')만 쓴다. 이름을 댄 ETF끼리 나란히 비교만 하면 etf_compare"
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
        elif args.kind == "etf" and not args.targets:
            candidates = node(graph, "MATCH (e:ETF) RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC", {})
        elif args.kind == "etf":
            candidates, missing = resolver.etfs(db, args.targets)
        else:
            candidates, missing = resolver.stocks(db, args.targets)
        if not candidates:
            return not_found(f"후보를 찾지 못했습니다: {', '.join(args.targets)}")

        label, fmt, _ = METRICS[args.by]
        if args.by == "return":
            label = f"{period_label(args.period)} 수익률"
        values, spans = self._values(graph, args, candidates)
        scored = [{"code": c["code"], "name": c["name"], "value": values.get(c["code"])} for c in candidates]
        no_data = [s["name"] for s in scored if s["value"] is None]
        scored = [s for s in scored if s["value"] is not None]
        target = "ETF" if args.kind == "etf" else "종목"
        if not scored:
            return empty(f"후보 {target} {len(candidates)}개 모두 {label} 데이터가 없습니다")
        if args.min_value is not None:
            scored = [s for s in scored if s["value"] >= args.min_value]
        if args.max_value is not None:
            scored = [s for s in scored if s["value"] <= args.max_value]
        scored.sort(key=lambda s: (s["value"], s["code"]), reverse=args.order == "desc")
        picked = scored[:args.top]
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
        as_of = None
        if args.by == "return":
            # 고른 대상의 시작·끝 거래일 (거래 정지 등으로 대상마다 다를 수 있어 가장 이른 시작 ~ 가장 늦은 끝)
            picked_spans = [spans[p["code"]] for p in picked]
            as_of = max(end for _, end in picked_spans)
            span = period_span(min(start for start, _ in picked_spans), as_of, "종가 기준")
            notes.append(span)
            summary = f"{span}\n{summary}"
        if args.by == "dividend_yield":
            notes.append("분배율은 최근 12개월 분배금 합을 현재가로 나눈 값입니다 (특별분배가 있으면 높게, "
                         "상장 1년 미만이면 낮게 나옵니다)")
        if len(picked) < args.top:
            notes.append(f"조건에 맞는 {target}가 {len(picked)}개뿐입니다")
        if no_data:
            notes.append(f"{label} 데이터가 없어 뺀 {target}: {', '.join(no_data)}")
        if missing:
            notes.append(f"찾지 못한 {target}: {', '.join(missing)}")
        source = "일별 종가" if args.by == "return" else "ETF 기본 정보"
        return data_result(dataset, view, summary, [Source(label=f"{target} {source}", as_of=as_of)], notes,
                           exports=[{"code": p["code"], "name": p["name"]} for p in picked])

    @staticmethod
    def _values(graph: GraphService, args: RankArgs,
                candidates: List[Dict]) -> Tuple[Dict[str, Optional[float]], Dict[str, Tuple[str, str]]]:
        """{code: 값}과, 수익률이면 값을 낸 대상의 {code: (시작일, 끝일)}."""
        if args.by == "return":
            prices = graph.get_etf_prices if args.kind == "etf" else graph.get_stock_prices
            out, spans = {}, {}
            for c in candidates:
                series = [p for p in prices(c["code"], days=period_days(args.period)) if p.get("close")]
                base = period_base(series, args.period) if series else None
                out[c["code"]] = pct_change(base["close"], series[-1]["close"]) if base else None
                if base:
                    spans[c["code"]] = (base["date"], series[-1]["date"])
            return out, spans
        codes = ", ".join(repr(c["code"]) for c in candidates if SAFE_CODE_RE.fullmatch(c["code"]))
        rows = node(graph, f"MATCH (e:ETF) WHERE e.code IN [{codes}] RETURN {{code: e.code, value: e.{args.by}}}", {})
        return {r["code"]: (float(r["value"]) if r.get("value") is not None else None) for r in rows}, {}

    @staticmethod
    def _condition(args: RankArgs, fmt: str) -> str:
        parts = []
        if args.min_value is not None:
            parts.append(f"{format_value(args.min_value, fmt)} 이상")
        if args.max_value is not None:
            parts.append(f"{format_value(args.max_value, fmt)} 이하")
        return f"({', '.join(parts)})" if parts else ""
