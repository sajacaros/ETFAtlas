from datetime import date, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from ...graph_service import GraphService
from ..resolver import EntityResolver
from ..schemas import BarView, DataField, Dataset, Source, TableView
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .common import ETFListArgs, missing_notes, pct_change

PERIODS = [("1일", 1), ("1주", 7), ("1개월", 30), ("3개월", 90), ("6개월", 180), ("1년", 365)]


def period_return(prices: List[Dict], days: int) -> Optional[float]:
    """마지막 종가와, 그보다 days일 이전의 가장 가까운 거래일 종가 사이의 수익률. 데이터가 그만큼 없으면 None."""
    latest = prices[-1]
    target = (date.fromisoformat(latest["date"]) - timedelta(days=days)).isoformat()
    past = [p for p in prices if p["date"] <= target]
    return pct_change(past[-1]["close"], latest["close"]) if past else None


class PeriodReturnsSkill(DataSkill):
    name = "period_returns"
    description = "ETF 1~5개의 기간별 수익률(1일, 1주, 1개월, 3개월, 6개월, 1년) 비교"
    Args = ETFListArgs
    displays = ("bar", "table")

    def fetch(self, args: ETFListArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        found, missing = resolver.etfs(db, args.etfs)
        if not found:
            return not_found(f"ETF를 찾지 못했습니다: {', '.join(missing)}")
        graph = GraphService(db)
        names = {e["code"]: e["name"] for e in found}
        series = {}
        for code in names:
            prices = [p for p in graph.get_etf_prices(code, days=370) if p.get("close")]
            if prices:
                series[code] = prices
        rows = []
        for label, days in PERIODS:
            row = {"period": label, **{code: period_return(ps, days) for code, ps in series.items()}}
            if any(row[code] is not None for code in series):
                rows.append(row)
        if not rows:
            return empty("수익률을 계산할 가격 데이터가 없습니다")

        dataset = Dataset(
            fields=[DataField(key="period", label="기간", format="text")]
            + [DataField(key=code, label=names[code], format="percent") for code in series],
            rows=rows,
        )
        view = BarView(x="period", y=list(series)) if display == "bar" else TableView()
        summary = "\n".join(
            f"{names[code]}: " + ", ".join(f"{r['period']} {r[code]:+.2f}%" for r in rows if r[code] is not None)
            for code in series
        )
        sources = [Source(label="ETF 일별 종가", as_of=max(ps[-1]["date"] for ps in series.values()))]
        return data_result(dataset, view, summary, sources, missing_notes(missing))
