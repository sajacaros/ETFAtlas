from typing import Dict, List, Optional

from pydantic import Field
from sqlalchemy.orm import Session

from ...graph_service import GraphService
from ..resolver import EntityResolver
from ..schemas import BarView, DataField, Dataset, Source, TableView
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .common import ETFListArgs, Period, missing_notes, pct_change, period_base, period_days, period_label

PERIODS = ["1d", "1w", "1m", "3m", "6m", "1y"]


class PeriodReturnsArgs(ETFListArgs):
    period: Optional[Period] = Field(None, description=(
        "질문이 기본 기간(1일·1주·1개월·3개월·6개월·1년) 밖의 기간을 말하면 그 기간 (예: '2주'→2w, '올해'→ytd). "
        "그 기간 행을 더한다. 기본 기간이거나 기간이 없으면 비운다"
    ))


def period_return(prices: List[Dict], spec: str) -> Optional[float]:
    """마지막 종가와 시작점(period_base) 종가 사이의 수익률. 데이터가 그만큼 없으면 None."""
    base = period_base(prices, spec)
    return pct_change(base["close"], prices[-1]["close"]) if base else None


class PeriodReturnsSkill(DataSkill):
    name = "period_returns"
    description = "ETF 1~5개의 기간별 수익률(1일, 1주, 1개월, 3개월, 6개월, 1년, 그리고 질문이 말한 기간) 비교"
    Args = PeriodReturnsArgs
    displays = ("bar", "table")

    def fetch(self, args: PeriodReturnsArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        found, missing = resolver.etfs(db, args.etfs)
        if not found:
            return not_found(f"ETF를 찾지 못했습니다: {', '.join(missing)}")
        specs = PERIODS + ([args.period] if args.period and args.period not in PERIODS else [])
        specs.sort(key=period_days)
        graph = GraphService(db)
        names = {e["code"]: e["name"] for e in found}
        series = {}
        for code in names:
            prices = [p for p in graph.get_etf_prices(code, days=max(370, period_days(specs[-1]))) if p.get("close")]
            if prices:
                series[code] = prices
        end = max((ps[-1]["date"] for ps in series.values()), default=None)
        rows = []
        for spec in specs:
            bases = {code: period_base(ps, spec) for code, ps in series.items()}
            starts = [b["date"] for b in bases.values() if b]
            if not starts:
                continue
            rows.append({"period": period_label(spec), "start": min(starts),
                         **{code: pct_change(b["close"], series[code][-1]["close"]) if b else None
                            for code, b in bases.items()}})
        if not rows:
            return empty("수익률을 계산할 가격 데이터가 없습니다")

        dataset = Dataset(
            fields=[DataField(key="period", label="기간", format="text"),
                    DataField(key="start", label="시작일", format="date")]
            + [DataField(key=code, label=names[code], format="percent") for code in series],
            rows=rows,
        )
        view = BarView(x="period", y=list(series)) if display == "bar" else TableView()
        # 차트에는 시작일 열이 안 보이므로 기간마다 어디서부터 셌는지 주석과 요약에 적는다
        span = f"{end} 종가 기준, 시작일: " + " · ".join(f"{r['period']} {r['start']}" for r in rows)
        summary = span + "\n" + "\n".join(
            f"{names[code]}: " + ", ".join(f"{r['period']} {r[code]:+.2f}%" for r in rows if r[code] is not None)
            for code in series
        )
        notes = [span] + missing_notes(missing)
        if args.period and period_label(args.period) not in {r["period"] for r in rows}:
            notes.append(f"{period_label(args.period)} 수익률은 가격 데이터가 그만큼 길지 않아 계산하지 못했습니다")
        sources = [Source(label="ETF 일별 종가", as_of=end)]
        return data_result(dataset, view, summary, sources, notes)
