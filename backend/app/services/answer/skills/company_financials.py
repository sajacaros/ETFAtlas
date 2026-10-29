from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....models.dart import StockFinancial
from ...content import BarView, DataField, Dataset, LineView, Source, TableView
from ...domain import financials as fin
from ...domain.entities import EntityResolver
from ...domain.format import format_value
from ...domain.periods import pct_change
from .base import DataSkill, SkillResult, data_result, empty, not_found

FS_LABEL = {"CFS": "연결", "OFS": "별도"}


class CompanyFinancialsArgs(BaseModel):
    stock: str = Field(description="종목 이름 또는 6자리 코드 (하나)")
    basis: Literal["quarter", "year"] = Field("quarter", description="quarter: 분기 실적, year: 연간 실적")
    periods: int = Field(8, ge=2, le=12, description="보여줄 기간 수 (분기면 분기 수, 연간이면 연도 수). 최근 3개 사업연도까지 있다")


def _krw(value: Optional[int]) -> str:
    if value is None:
        return "-"
    return ("-" if value < 0 else "") + format_value(abs(value), "krw")


def _year_ago(period: str) -> str:
    """'2026.2Q' → '2025.2Q', '2026' → '2025' (빠진 분기가 있어도 같은 분기와 비교한다)."""
    year, _, quarter = period.partition(".")
    return f"{int(year) - 1}" + (f".{quarter}" if quarter else "")


def _summary(name: str, fs: str, basis: str, periods: List[Dict], all_periods: List[Dict],
             debt_ratio: Optional[str]) -> str:
    lines = [f"{name} {'분기' if basis == 'quarter' else '연간'} 실적 (DART 주요계정, {fs}):"]
    for p in periods:
        margin = f", 영업이익률 {p['margin']:.1f}%" if p["margin"] is not None else ""
        lines.append(f"- {p['period']}: 매출액 {_krw(p['revenue'])}, 영업이익 {_krw(p['operating_income'])}{margin}, "
                     f"순이익 {_krw(p['net_income'])}")
    last = periods[-1]
    prev = next((p for p in all_periods if p["period"] == _year_ago(last["period"])), None)
    if prev:
        changes = []
        for key, label in (("revenue", "매출액"), ("operating_income", "영업이익")):
            # 기준이 0 이하면 증감률이 뜻이 없다 (적자 → 흑자를 '증가율'로 쓰지 않는다)
            if last[key] is not None and prev[key] is not None and prev[key] > 0:
                changes.append(f"{label} {pct_change(prev[key], last[key]):+.1f}%")
            elif last[key] is not None and prev[key] is not None:
                changes.append(f"{label} {_krw(prev[key])} → {_krw(last[key])}")
        if changes:
            label = "전년 동기" if basis == "quarter" else "전년"
            lines.append(f"{last['period']}의 {label}({prev['period']}) 대비: {', '.join(changes)}")
    above = net_above_revenue(periods)
    lines.append(above or "보여 준 모든 기간에서 순이익은 매출액보다 작습니다")
    if debt_ratio:
        lines.append(debt_ratio)
    return "\n".join(lines)


def net_above_revenue(periods: List[Dict]) -> Optional[str]:
    """순이익이 매출액보다 큰 기간. 해설이 숫자를 직접 비교하다 틀리지 않게 사실로 적어 준다."""
    hits = fin.net_above_revenue(periods)
    if not hits:
        return None
    detail = ", ".join(f"{p['period']} 순이익 {_krw(p['net_income'])} > 매출액 {_krw(p['revenue'])}" for p in hits)
    return (f"순이익이 매출액보다 큰 기간이 있습니다: {detail}. 영업이익 밖의 이익(금융수익·처분이익 등)이 컸다는 뜻이며, "
            "어떤 이익인지는 이 데이터(주요계정)에 없어 공시 본문에서 확인해야 합니다")


def _debt_ratio(amounts: fin.Amounts) -> Optional[str]:
    dr = fin.latest_debt_ratio(amounts)
    if dr is None:
        return None
    return (f"부채비율 {dr.ratio:.1f}% ({dr.year}년 {fin.REPORT_LABEL[dr.reprt_code]} 기준, "
            f"부채총계 {_krw(dr.debt)} ÷ 자본총계 {_krw(dr.equity)})")


class CompanyFinancialsSkill(DataSkill):
    name = "company_financials"
    description = (
        "개별 종목(상장사)의 실적: DART 공시 기준 분기 또는 연간 매출액·영업이익·순이익과 영업이익률, 최근 부채비율. "
        "기업 분석, 실적·이익·매출 추이를 물을 때. 종목 하나만 받는다"
    )
    Args = CompanyFinancialsArgs
    displays = ("bar", "line", "table")

    def fetch(self, args: CompanyFinancialsArgs, display: str, db: Session, resolver: EntityResolver) -> SkillResult:
        stock = resolver.stock(db, args.stock)
        if stock is None:
            return not_found(f"종목을 찾지 못했습니다: {args.stock}")
        rows = db.query(StockFinancial).filter(StockFinancial.stock_code == stock["code"]).all()
        if not rows:
            return empty(f"{stock['name']}의 DART 실적 데이터가 아직 없습니다 (수집 전이거나 주요계정을 공시하지 않는 종목)")
        fs_div, amounts = fin.pick_fs(rows)
        all_periods = fin.build_periods(amounts, args.basis)
        periods = all_periods[-args.periods:]
        if not periods:
            return empty(f"{stock['name']}의 {'분기' if args.basis == 'quarter' else '연간'} 실적 데이터가 없습니다")

        fs = FS_LABEL.get(fs_div, fs_div)
        debt_ratio = _debt_ratio(amounts)
        summary = _summary(stock["name"], fs, args.basis, periods, all_periods, debt_ratio)
        latest = max((r.rcept_no or "")[:8] for r in rows if r.fs_div == fs_div)
        as_of = f"{latest[:4]}-{latest[4:6]}-{latest[6:]}" if len(latest) == 8 else None
        sources = [Source(label=f"DART 주요계정 ({fs}재무제표)", as_of=as_of)]
        notes = [f"{fs}재무제표 기준입니다" + (" (연결재무제표를 공시하지 않는 회사)" if fs_div == "OFS" else "")]
        if args.basis == "quarter":
            notes.append("4분기는 사업보고서의 연간 금액에서 3분기 누적을 뺀 값입니다")
        if any(p[key] is None for p in periods for key, _ in fin.INCOME):
            notes.append("빈 칸은 공시에 없는 값입니다")
        above = net_above_revenue(periods)
        if above:
            notes.append(above)
        if debt_ratio:
            notes.append(debt_ratio)

        fields = [DataField(key="period", label="기간", format="text")]
        fields += [DataField(key=key, label=label, format="krw") for key, label in fin.INCOME]
        fields.append(DataField(key="margin", label="영업이익률", format="percent"))  # 차트에는 그리지 않고 표로 보기에 나온다
        dataset = Dataset(fields=fields, rows=[{f.key: p[f.key] for f in fields} for p in periods])
        y = [key for key, _ in fin.INCOME]
        view = {"table": TableView(), "line": LineView(x="period", y=y)}.get(display, BarView(x="period", y=y))
        return data_result(dataset, view, summary, sources, notes)
