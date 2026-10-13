from typing import Dict, List, Optional

from pydantic import Field
from sqlalchemy.orm import Session

from ...graph_service import GraphService
from ..resolver import EntityResolver
from ..schemas import DataField, Dataset, RadarView, Source, TableView
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .common import ETF_NAMES_DESCRIPTION, ETFListArgs, format_value, missing_notes, node

# (축 이름, 지표, 원값 서식, 좋은 방향)
AXES = [
    ("저보수", "expense_ratio", "percent", "low"),
    ("규모", "net_assets", "krw", "high"),
    ("1주 수익률", "return_1w", "percent", "high"),
    ("1주 시총 증감", "market_cap_change_1w", "percent", "high"),
    ("분산도", "top10_weight", "percent", "low"),
]


def percentile(value: Optional[float], population: List[float], better: str) -> Optional[int]:
    """전체 ETF 중 이 값보다 나쁜 비율(동률은 절반). 비교 대상끼리 정규화하면 둘뿐일 때 항상 0과 100이 되므로 전체 기준으로 잡는다."""
    if value is None or not population:
        return None
    worse = sum(1 for v in population if (v < value if better == "high" else v > value))
    ties = sum(1 for v in population if v == value)
    return round((worse + ties / 2) / len(population) * 100)


class ProfileArgs(ETFListArgs):
    etfs: List[str] = Field(min_length=1, max_length=3, description=ETF_NAMES_DESCRIPTION)


class ETFProfileSkill(DataSkill):
    name = "etf_profile"
    description = (
        "ETF 1~3개의 성격을 전체 ETF 대비 백분위 점수(0~100)로: 저보수, 규모, 1주 수익률, 1주 시총 증감, "
        "분산도(상위 10종목 비중이 낮을수록 높음). '어떤 ETF가 더 나은지 종합적으로' 같은 질문에"
    )
    Args = ProfileArgs
    displays = ("radar", "table")

    def fetch(self, args: ProfileArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        found, missing = resolver.etfs(db, args.etfs)
        if not found:
            return not_found(f"ETF를 찾지 못했습니다: {', '.join(missing)}")
        graph = GraphService(db)
        universe: Dict[str, Dict] = {
            e["code"]: e
            for e in node(
                graph,
                "MATCH (e:ETF) RETURN {code: e.code, expense_ratio: e.expense_ratio, net_assets: e.net_assets, "
                "return_1w: e.return_1w, market_cap_change_1w: e.market_cap_change_1w}",
                {},
            )
        }
        for row in node(
            graph,
            "MATCH (e:ETF)-[h:CURRENT_HOLDS]->(:Stock) WITH e.code AS code, collect(h.weight) AS weights "
            "RETURN {code: code, weights: weights}",
            {},
        ):
            if row["code"] in universe:
                universe[row["code"]]["top10_weight"] = round(sum(sorted(row["weights"], reverse=True)[:10]), 2)

        codes = [e["code"] for e in found if e["code"] in universe]
        if not codes:
            return empty("ETF 지표 데이터가 없습니다")
        names = {e["code"]: e["name"] for e in found}
        rows = []
        for label, key, fmt, better in AXES:
            population = [e[key] for e in universe.values() if e.get(key) is not None]
            raw = {c: universe[c].get(key) for c in codes}
            rows.append({
                "axis": label, "_format": fmt, "_raw": raw,
                **{c: percentile(raw[c], population, better) for c in codes},
            })

        dataset = Dataset(
            fields=[DataField(key="axis", label="지표", format="text")]
            + [DataField(key=c, label=names[c]) for c in codes],
            rows=rows,
        )
        view = RadarView(axis="axis", series=codes) if display == "radar" else TableView(orientation="compare")
        summary = "\n".join(
            [f"점수는 전체 {len(universe)}개 ETF 중 백분위(0~100, 높을수록 유리). 괄호는 원값이며 "
             "분산도의 원값은 상위 10종목 비중(낮을수록 고르게 분산, 점수는 높음), 저보수의 원값은 총보수"]
            + [f"{names[c]}: " + ", ".join(f"{r['axis']} {r[c]}점({format_value(r['_raw'][c], r['_format'])})"
                                           for r in rows) for c in codes]
        )
        notes = [
            f"점수는 전체 {len(universe)}개 ETF 중 백분위(0~100)입니다. 보수와 상위 10종목 비중은 낮을수록 높은 점수입니다",
            *missing_notes(missing),
        ]
        sources = [Source(label=f"전체 {len(universe)}개 ETF 대비", as_of=graph.get_latest_price_date())]
        return data_result(dataset, view, summary, sources, notes)
