from typing import ClassVar, Dict, List, Tuple

from pydantic import Field
from sqlalchemy.orm import Session

from ....domain.periods import Period, pct_change, period_base, period_days, period_label
from ...content import CandlestickView, DataField, Dataset, LineView, Source, TableView
from ...entities import EntityResolver
from ...graph_service import GraphService
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .common import DEFAULT_PERIOD, PERIOD_DESCRIPTION, ETFListArgs, missing_notes, period_span


class PriceTrendArgs(ETFListArgs):
    period: Period = Field(DEFAULT_PERIOD, description=PERIOD_DESCRIPTION)


def _summary_line(name: str, prices: List[Dict]) -> str:
    closes = [p["close"] for p in prices]
    return (
        f"{name}: {prices[0]['date']}~{prices[-1]['date']}({len(prices)}거래일) 종가 {closes[0]:,.0f}→{closes[-1]:,.0f}원 "
        f"({pct_change(closes[0], closes[-1]):+.2f}%), 최고 {max(closes):,.0f}, 최저 {min(closes):,.0f}"
    )


class PriceTrendBase(DataSkill):
    """가격 추이 공통: 대상(ETF·종목)을 찾고 가격을 가져오는 부분만 하위 클래스가 정한다."""
    displays = ("line", "candlestick", "table")
    target: ClassVar[str]  # 화면 문구에 쓰는 대상 이름

    def targets(self, args, db: Session, resolver: EntityResolver) -> Tuple[List[Dict], List[str]]:
        raise NotImplementedError

    def prices(self, graph: GraphService, code: str, days: int) -> List[Dict]:
        raise NotImplementedError

    def fetch(self, args, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        found, missing = self.targets(args, db, resolver)
        if not found:
            return not_found(f"찾지 못한 {self.target}: {', '.join(missing)}")
        graph = GraphService(db)
        names = {e["code"]: e["name"] for e in found}
        series: Dict[str, List[Dict]] = {}
        short: List[str] = []  # 수집 이력이 요청 기간의 시작점까지 닿지 않는 대상
        for code in names:
            prices = [p for p in self.prices(graph, code, period_days(args.period)) if p.get("close")]
            if not prices:
                continue
            # 수익률 순위·기간 수익률과 같은 시작점(기간 전 마지막 거래일)부터 그려 같은 기간이면 등락률이 같게
            base = period_base(prices, args.period)
            if base:
                prices = [p for p in prices if p["date"] >= base["date"]]
            else:
                short.append(code)
            series[code] = prices
        if not series:
            return empty("해당 기간의 가격 데이터가 없습니다")

        first_date = min(ps[0]["date"] for ps in series.values())
        last_date = max(ps[-1]["date"] for ps in series.values())
        span = period_span(first_date, last_date, period_label(args.period))
        summary = span + "\n" + "\n".join(_summary_line(names[c], ps) for c, ps in series.items())
        sources = [Source(label=f"{self.target} 일별 시세", as_of=last_date)]
        notes = [span] + missing_notes(missing)
        # 수집 이력이 요청 기간보다 짧으면 알린다 (해설이 '한 달간'처럼 쓰지 않게 요약에도 넣는다)
        if short:
            note = "요청한 기간보다 데이터가 짧습니다: " + ", ".join(f"{names[c]} {series[c][0]['date']}부터" for c in short)
            notes.append(note)
            summary += f"\n({note})"

        if display == "candlestick":
            code, prices = next(iter(series.items()))
            if len(series) > 1:
                notes.append(f"봉차트는 하나만 그립니다: {names[code]}")
            dataset = Dataset(
                fields=[
                    DataField(key="date", label="날짜", format="date"),
                    DataField(key="open", label="시가", format="price"),
                    DataField(key="high", label="고가", format="price"),
                    DataField(key="low", label="저가", format="price"),
                    DataField(key="close", label="종가", format="price"),
                    DataField(key="volume", label="거래량", format="number"),
                ],
                rows=[{k: p.get(k) for k in ("date", "open", "high", "low", "close", "volume")} for p in prices],
            )
            view = CandlestickView(x="date", open="open", high="high", low="low", close="close", volume="volume")
            return data_result(dataset, view, summary, sources, notes)

        if display == "table":
            dataset = Dataset(
                fields=[
                    DataField(key="name", label=self.target, format="text"),
                    DataField(key="start", label="시작 종가", format="price"),
                    DataField(key="end", label="마지막 종가", format="price"),
                    DataField(key="change", label="등락률", format="percent"),
                    DataField(key="high", label="최고", format="price"),
                    DataField(key="low", label="최저", format="price"),
                ],
                rows=[
                    {
                        "name": names[c], "start": ps[0]["close"], "end": ps[-1]["close"],
                        "change": pct_change(ps[0]["close"], ps[-1]["close"]),
                        "high": max(p["close"] for p in ps), "low": min(p["close"] for p in ps),
                    }
                    for c, ps in series.items()
                ],
            )
            return data_result(dataset, TableView(), summary, sources, notes)

        # line: 하나면 종가, 여럿이면 가격대가 달라 겹쳐 볼 수 없으니 시작일 대비 누적 수익률
        single = len(series) == 1
        by_date: Dict[str, Dict] = {}
        for code, prices in series.items():
            base = prices[0]["close"]
            for p in prices:
                row = by_date.setdefault(p["date"], {"date": p["date"]})
                row[code] = p["close"] if single else pct_change(base, p["close"])
        dataset = Dataset(
            fields=[DataField(key="date", label="날짜", format="date")]
            + [DataField(key=c, label=names[c], format="price" if single else "percent") for c in series],
            rows=[by_date[d] for d in sorted(by_date)],
        )
        if not single:
            notes.append("시작일 종가를 기준으로 한 누적 수익률입니다")
        return data_result(dataset, LineView(x="date", y=list(series)), summary, sources, notes)


class PriceTrendSkill(PriceTrendBase):
    name = "price_trend"
    description = (
        "ETF 가격 추이. ETF가 여럿이면 시작일 대비 누적 수익률(%)로 겹쳐 그린다. "
        "candlestick은 ETF 하나의 일별 시가·고가·저가·종가와 거래량, table은 ETF별 기간 요약(시작·끝 종가, 등락률, 최고·최저)"
    )
    Args = PriceTrendArgs
    target = "ETF"
    subject = "etf"
    entity_args = {"etfs": "etf"}

    def targets(self, args: PriceTrendArgs, db: Session, resolver: EntityResolver):
        return resolver.etfs(db, args.etfs)

    def prices(self, graph: GraphService, code: str, days: int) -> List[Dict]:
        return graph.get_etf_prices(code, days=days)
