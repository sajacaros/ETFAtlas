"""company_valuation: 종목의 시가총액과 PER·PBR·ROE.

시가총액은 DB의 최근 종가 × 상장주식수(KIS 일봉 수집 때 함께 받는다), 이익·자본은 DART 주요계정이다 (app/domain/valuation.py).
KIS가 주는 PER·PBR은 산정 기준(지배주주 순이익·발행주식수 등)이 달라 대조용으로만 함께 보여 준다.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....domain import financials as fin
from ....domain.format import format_value
from ....domain.valuation import Valuation, valuation
from ....models.dart import StockFinancial
from ...content import DataField, Dataset, Source, TableView
from ...entities import EntityResolver
from ...graph_service import GraphService, node
from .base import DataSkill, SkillResult, data_result, empty
from .stock_holders import SAFE_CODE_RE

PRICE_DAYS = 14  # 최근 종가를 찾는 범위 (연휴 여유)

FIELDS = [
    DataField(key="name", label="종목", format="text"),
    DataField(key="close", label="종가", format="price"),
    DataField(key="market_cap", label="시가총액", format="krw"),
    DataField(key="per_ttm", label="PER(최근 4분기)", format="number"),
    DataField(key="per_annual", label="PER(직전 연도)", format="number"),
    DataField(key="pbr", label="PBR", format="number"),
    DataField(key="roe", label="ROE(최근 4분기)", format="percent"),
    DataField(key="kis_per", label="PER(KIS)", format="number"),
    DataField(key="kis_pbr", label="PBR(KIS)", format="number"),
]


class CompanyValuationArgs(BaseModel):
    stocks: List[str] = Field(min_length=1, max_length=5, description="종목 이름 또는 6자리 코드 (여러 개면 나란히 비교)")


def _krw(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return ("-" if value < 0 else "") + format_value(abs(value), "krw")


def _multiple_text(label: str, value: Optional[float], base, what: str, absent: str = "") -> str:
    if base is None:
        return f"{label}: 계산하지 않음 ({absent or what + ' 데이터 없음'})"
    if value is None:
        reason = "적자" if base.amount < 0 else "0 이하"
        return f"{label}: 계산하지 않음 ({base.label} {what} {_krw(base.amount)}, {reason})"
    return f"{label} {value:.2f}배 ({base.label} {what} {_krw(base.amount)})"


def _line(name: str, v: Valuation, kis: Dict) -> str:
    parts = [
        f"{name}: 종가 {v.price:,.0f}원({v.price_date}) × 상장주식수 {v.shares:,}주 = 시가총액 {_krw(v.market_cap)}",
        _multiple_text("PER(최근 4분기)", v.per_ttm, v.ttm, "순이익", "이어진 4개 분기의 순이익이 공시에 없음"),
        _multiple_text("PER(직전 연도)", v.per_annual, v.annual, "순이익"),
        _multiple_text("PBR", v.pbr, v.equity, "자본총계"),
    ]
    if v.roe is not None:
        parts.append(f"ROE(최근 4분기 순이익 ÷ 자본총계) {v.roe:.2f}%")
    if kis.get("kis_per") or kis.get("kis_pbr"):
        values = ", ".join(f"{k} {kis[f'kis_{k.lower()}']}" for k in ("PER", "PBR") if kis.get(f"kis_{k.lower()}"))
        parts.append(f"KIS 제공 {values} ({kis.get('quote_date')} 종가 기준)")
    return "; ".join(parts)


class CompanyValuationSkill(DataSkill):
    name = "company_valuation"
    description = (
        "PER·PBR·ROE·시가총액(밸류에이션)을 물을 때만 쓰는 스킬. '주가 비교'·'주가 추이'·'차트'에는 쓰지 않는다 "
        "(주가는 stock_trend, 차트 분석은 stock_technical, 실적 추이는 company_financials). "
        "개별 종목의 시가총액(종가 × 상장주식수), PER(최근 4분기·직전 연도 순이익 기준), PBR, ROE와 대조용 KIS 제공 PER·PBR. "
        "종목 1~5개를 한 표에 놓는다"
    )
    Args = CompanyValuationArgs
    displays = ("table",)
    tool = True
    subject = "stock"
    entity_args = {"stocks": "stock"}

    def fetch(self, args: CompanyValuationArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        stocks, missing = resolver.stocks(db, args.stocks)
        stocks = [s for s in stocks if SAFE_CODE_RE.fullmatch(s["code"])]
        if not stocks:
            return empty(f"찾지 못한 종목: {', '.join(missing)}" if missing else "종목을 찾지 못했습니다")
        graph = GraphService(db)
        codes = [s["code"] for s in stocks]
        props = {r["code"]: r for r in node(graph, (
            "MATCH (s:Stock) WHERE s.code IN [" + ", ".join(f"'{c}'" for c in codes) + "] "
            "RETURN {code: s.code, shares: s.listed_shares, kis_per: s.kis_per, kis_pbr: s.kis_pbr, quote_date: s.quote_date}"
        ), {})}
        rows, lines, notes, as_of = [], [], [], []
        for stock in stocks:
            name, code = stock["name"], stock["code"]
            prices = [p for p in graph.get_stock_prices(code, days=PRICE_DAYS) if p.get("close")]
            shares = (props.get(code) or {}).get("shares")
            if not prices or not shares:
                why = "최근 종가" if not prices else "상장주식수(다음 시세 수집 때 채워진다)"
                notes.append(f"{name}: {why}가 없어 계산하지 못했습니다")
                continue
            fs_div, amounts = fin.pick_fs(db.query(StockFinancial).filter(StockFinancial.stock_code == code).all())
            v = valuation(prices[-1]["close"], prices[-1]["date"], int(shares), amounts)
            kis = props.get(code) or {}
            rows.append({"name": name, "close": v.price, "market_cap": v.market_cap, "per_ttm": v.per_ttm,
                         "per_annual": v.per_annual, "pbr": v.pbr, "roe": v.roe,
                         "kis_per": kis.get("kis_per"), "kis_pbr": kis.get("kis_pbr")})
            lines.append(_line(name, v, kis))
            as_of.append(v.price_date)
            if amounts and fs_div == "OFS":
                notes.append(f"{name}: 연결재무제표가 없어 별도 기준입니다")
        if not rows:
            return empty(" / ".join(notes) or "계산할 수 있는 종목이 없습니다")

        notes = [
            "시가총액 = 최근 종가 × 상장주식수(보통주). 우선주가 있는 회사는 우선주 시가총액이 빠집니다",
            "순이익·자본총계는 DART 주요계정(연결이 있으면 연결)으로 비지배지분을 포함합니다 — 지배주주 기준 PER과 다를 수 있습니다",
            "PER·PBR은 순이익·자본이 0 이하(적자·자본잠식)면 계산하지 않습니다",
            "KIS PER·PBR은 KIS 산정값(직전 사업연도 지배주주 EPS 등)이라 대조용입니다",
            *notes, *([f"찾지 못한 종목: {', '.join(missing)}"] if missing else []),
        ]
        sources = [Source(label="종목 일별 시세·상장주식수(KIS)", as_of=max(as_of)), Source(label="DART 주요계정")]
        dataset = Dataset(fields=FIELDS, rows=rows)
        return data_result(dataset, TableView(), "\n".join(lines), sources, notes)
