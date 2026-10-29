from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...content import BarView, DataField, Dataset, DonutView, Source, TableView, TreemapView
from ...domain.entities import EntityResolver
from ...domain.graph import node
from ...graph_service import GraphService
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .common import cut_note, min_weight_field

DONUT_MAX_SLICES = 8  # 넘으면 나머지를 '기타'로 묶는다


class HoldingsArgs(BaseModel):
    etf: str = Field(description="ETF 이름 또는 6자리 코드")
    top: int = Field(10, ge=3, le=30, description="보여줄 상위 종목 수")
    min_weight: Optional[float] = min_weight_field("종목")


class HoldingsSkill(DataSkill):
    name = "holdings"
    description = (
        "ETF 하나의 구성종목과 비중(상위 최대 30개). treemap은 종목이 많은 구성을 한눈에, "
        "donut은 상위 몇 개 종목의 비중, bar는 비중 순위, table은 정확한 비중 목록"
    )
    Args = HoldingsArgs
    displays = ("treemap", "donut", "bar", "table")
    exports = "종목 목록, ETF 내 비중 높은 순 (상위 30개)"

    def fetch(self, args: HoldingsArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        etf = resolver.etf(db, args.etf)
        if etf is None:
            return not_found(f"ETF를 찾지 못했습니다: {args.etf}")
        holdings = node(
            GraphService(db),
            "MATCH (e:ETF {code: $code})-[h:CURRENT_HOLDS]->(s:Stock) "
            "RETURN {code: s.code, name: s.name, weight: h.weight, date: h.date} ORDER BY h.weight DESC",
            {"code": etf["code"]},
        )
        holdings = [h for h in holdings if h.get("weight") is not None]
        if not holdings:
            return empty(f"{etf['name']}의 구성종목 데이터가 없습니다")
        if args.min_weight is not None:
            holdings = [h for h in holdings if h["weight"] >= args.min_weight]
            if not holdings:
                return empty(f"{etf['name']}에 비중 {args.min_weight:g}% 이상인 종목이 없습니다")

        top = args.top
        if display == "donut":
            top = min(top, DONUT_MAX_SLICES - 1)
        shown = holdings[:top]
        rows = [{"name": h["name"], "code": h["code"], "weight": h["weight"]} for h in shown]
        shown_sum = round(sum(h["weight"] for h in shown), 2)
        # 수집 데이터는 상위 30개뿐이라, 나머지 비중은 30위 밖 종목·현금 등을 합친 값이다
        rest = round(100 - shown_sum, 2)
        if display in ("treemap", "donut") and rest > 0.05:
            rows.append({"name": "기타", "code": None, "weight": rest})

        dataset = Dataset(
            fields=[
                DataField(key="name", label="종목", format="text"),
                DataField(key="code", label="코드", format="text"),
                DataField(key="weight", label="비중", format="percent"),
            ],
            rows=rows,
        )
        view = {
            "treemap": TreemapView(name="name", value="weight"),
            "donut": DonutView(name="name", value="weight"),
            "bar": BarView(x="name", y=["weight"], horizontal=True),
        }.get(display, TableView())
        condition = f"비중 {args.min_weight:g}% 이상 " if args.min_weight is not None else ""
        summary = (
            f"{etf['name']} {condition}상위 {len(shown)}개 종목: "
            + ", ".join(f"{h['name']} {h['weight']:.2f}%" for h in shown)
            + f" (합계 {shown_sum:.2f}%)"
        )
        sources = [Source(label=f"{etf['name']} 구성종목", as_of=shown[0].get("date"))]
        notes = cut_note(len(holdings), len(shown), "종목") if args.min_weight is not None else []
        return data_result(dataset, view, summary, sources, notes,
                           exports=[{"code": h["code"], "name": h["name"]} for h in holdings])
