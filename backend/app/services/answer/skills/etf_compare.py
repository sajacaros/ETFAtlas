from typing import List

from pydantic import Field
from sqlalchemy.orm import Session

from ...graph_service import GraphService
from ..resolver import EntityResolver
from ..schemas import DataField, Dataset, Source, TableView
from .base import DataSkill, SkillResult, data_result, not_found
from .common import ETF_NAMES_DESCRIPTION, ETFListArgs, format_value, missing_notes, node

DIVIDEND_CYCLE = {0: "분배 없음", 1: "월", 3: "분기", 6: "반기", 12: "연"}

# (항목, 속성, 서식, 좋은 방향)
ITEMS = [
    ("운용사", "company", "text", None),
    ("기초지수", "base_index", "text", None),
    ("총보수", "expense_ratio", "percent", "low"),
    ("순자산", "net_assets", "krw", "high"),
    ("1일 수익률", "return_1d", "percent", "high"),
    ("1주 수익률", "return_1w", "percent", "high"),
    ("1주 시총 증감", "market_cap_change_1w", "percent", "high"),
    ("분배 주기", "dividend_cycle", "text", None),
    ("분배율(12개월)", "dividend_yield", "percent", "high"),
    ("주당 분배금(12개월)", "dividend_per_share", "price", None),
    ("상장일", "listed_date", "date", None),
]


class CompareArgs(ETFListArgs):
    etfs: List[str] = Field(min_length=2, max_length=5, description=ETF_NAMES_DESCRIPTION)


class ETFCompareSkill(DataSkill):
    name = "etf_compare"
    description = (
        "ETF 2~5개의 기본 정보 비교표: 운용사, 기초지수, 총보수, 순자산, 1일·1주 수익률, 시총 증감, 분배 주기, "
        "최근 12개월 분배율·주당 분배금, 상장일"
    )
    Args = CompareArgs
    displays = ("table",)

    def fetch(self, args: CompareArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        found, missing = resolver.etfs(db, args.etfs)
        if not found:
            return not_found(f"ETF를 찾지 못했습니다: {', '.join(missing)}")
        graph = GraphService(db)
        infos = {}
        for etf in found:
            rows = node(
                graph,
                "MATCH (e:ETF {code: $code}) OPTIONAL MATCH (e)-[:MANAGED_BY]->(c:Company) "
                "RETURN {code: e.code, name: e.name, company: c.name, base_index: e.base_index, "
                "expense_ratio: e.expense_ratio, net_assets: e.net_assets, return_1d: e.return_1d, "
                "return_1w: e.return_1w, market_cap_change_1w: e.market_cap_change_1w, "
                "dividend_cycle: e.dividend_cycle, dividend_yield: e.dividend_yield, "
                "dividend_per_share: e.dividend_per_share, listed_date: e.listed_date}",
                {"code": etf["code"]},
            )
            if rows:
                info = rows[0]
                if info.get("dividend_cycle") is not None:
                    info["dividend_cycle"] = DIVIDEND_CYCLE.get(info["dividend_cycle"], f"{info['dividend_cycle']}개월")
                infos[etf["code"]] = info

        table_rows = []
        for label, key, fmt, better in ITEMS:
            values = {code: info.get(key) for code, info in infos.items()}
            if all(v is None for v in values.values()):
                continue
            row = {"item": label, "_format": fmt, **values}
            if better:
                row["_better"] = better
            table_rows.append(row)

        dataset = Dataset(
            fields=[DataField(key="item", label="항목", format="text")]
            + [DataField(key=code, label=info["name"]) for code, info in infos.items()],
            rows=table_rows,
        )
        summary = "\n".join(
            f"{r['item']}: " + ", ".join(f"{infos[c]['name']} {format_value(r.get(c), r['_format'])}" for c in infos)
            for r in table_rows
        )
        sources = [Source(label="ETF 기본정보·시세", as_of=graph.get_latest_price_date())]
        return data_result(dataset, TableView(orientation="compare"), summary, sources, missing_notes(missing))
