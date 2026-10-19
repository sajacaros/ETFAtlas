from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ....models.dart import StockFinancial
from ..resolver import EntityResolver
from ..schemas import BarView, DataField, Dataset, LineView, Source, TableView
from .base import DataSkill, SkillResult, data_result, empty, not_found
from .common import format_value, pct_change

Q1, H1, Q3, ANNUAL = "11013", "11012", "11014", "11011"
INCOME = (("revenue", "매출액"), ("operating_income", "영업이익"), ("net_income", "당기순이익"))
FS_LABEL = {"CFS": "연결", "OFS": "별도"}


class CompanyFinancialsArgs(BaseModel):
    stock: str = Field(description="종목 이름 또는 6자리 코드 (하나)")
    basis: Literal["quarter", "year"] = Field("quarter", description="quarter: 분기 실적, year: 연간 실적")
    periods: int = Field(8, ge=2, le=12, description="보여줄 기간 수 (분기면 분기 수, 연간이면 연도 수). 최근 3개 사업연도까지 있다")


Amounts = Dict[Tuple[int, str, str], Tuple[Optional[int], Optional[int]]]  # (연도, 보고서, 계정) → (금액, 누적)


def _pick_fs(rows: List[StockFinancial]) -> Tuple[str, Amounts]:
    """연결(CFS)이 하나라도 있으면 연결, 없으면 별도(OFS). 섞어 쓰지 않는다."""
    fs_div = "CFS" if any(r.fs_div == "CFS" for r in rows) else "OFS"
    return fs_div, {(r.bsns_year, r.reprt_code, r.account): (r.amount, r.amount_cum) for r in rows if r.fs_div == fs_div}


def quarter_values(amounts: Amounts, year: int, account: str) -> List[Optional[int]]:
    """1~4분기 값. 1~3분기는 분·반기 보고서의 3개월 금액, 4분기는 연간 − 3분기 누적.
    3분기 누적이 없으면 1~3분기를 더해 빼고, 하나라도 없으면 4분기는 비운다 (0으로 채우지 않는다)."""
    def get(reprt, cum=False):
        value = amounts.get((year, reprt, account))
        return None if value is None else value[1 if cum else 0]

    q1, q2, q3 = get(Q1), get(H1), get(Q3)
    annual, cum9 = get(ANNUAL), get(Q3, cum=True)
    if cum9 is None and None not in (q1, q2, q3):
        cum9 = q1 + q2 + q3
    q4 = annual - cum9 if annual is not None and cum9 is not None else None
    return [q1, q2, q3, q4]


def build_periods(amounts: Amounts, basis: str) -> List[Dict]:
    """[{period, revenue, operating_income, net_income, margin}] 오래된 순. 값이 하나도 없는 기간은 뺀다."""
    years = sorted({y for y, _, _ in amounts})
    periods = []
    for year in years:
        if basis == "year":
            values = {key: (amounts.get((year, ANNUAL, acc)) or (None, None))[0] for key, acc in INCOME}
            periods.append({"period": str(year), **values})
            continue
        by_account = {key: quarter_values(amounts, year, acc) for key, acc in INCOME}
        for q in range(4):
            periods.append({"period": f"{year}.{q + 1}Q", **{key: vals[q] for key, vals in by_account.items()}})
    periods = [p for p in periods if any(p[key] is not None for key, _ in INCOME)]
    for p in periods:
        p["margin"] = round(p["operating_income"] / p["revenue"] * 100, 2) \
            if p["operating_income"] is not None and p["revenue"] else None
    return periods


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
    if debt_ratio:
        lines.append(debt_ratio)
    return "\n".join(lines)


def _debt_ratio(amounts: Amounts) -> Optional[str]:
    """가장 최근 보고서의 부채비율 (부채총계 ÷ 자본총계)."""
    order = {Q1: 1, H1: 2, Q3: 3, ANNUAL: 4}
    reports = sorted({(y, r) for y, r, acc in amounts if acc == "부채총계"}, key=lambda k: (k[0], order[k[1]]), reverse=True)
    for year, reprt in reports:
        debt = amounts[(year, reprt, "부채총계")][0]
        equity = (amounts.get((year, reprt, "자본총계")) or (None, None))[0]
        if debt is not None and equity and equity > 0:
            label = {Q1: "1분기", H1: "반기", Q3: "3분기", ANNUAL: "사업보고서"}[reprt]
            return f"부채비율 {debt / equity * 100:.1f}% ({year}년 {label} 기준, 부채총계 {_krw(debt)} ÷ 자본총계 {_krw(equity)})"
    return None


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
        fs_div, amounts = _pick_fs(rows)
        all_periods = build_periods(amounts, args.basis)
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
        if any(p[key] is None for p in periods for key, _ in INCOME):
            notes.append("빈 칸은 공시에 없는 값입니다")
        if debt_ratio:
            notes.append(debt_ratio)

        fields = [DataField(key="period", label="기간", format="text")]
        fields += [DataField(key=key, label=label, format="krw") for key, label in INCOME]
        fields.append(DataField(key="margin", label="영업이익률", format="percent"))  # 차트에는 그리지 않고 표로 보기에 나온다
        dataset = Dataset(fields=fields, rows=[{f.key: p[f.key] for f in fields} for p in periods])
        y = [key for key, _ in INCOME]
        view = {"table": TableView(), "line": LineView(x="period", y=y)}.get(display, BarView(x="period", y=y))
        return data_result(dataset, view, summary, sources, notes)
