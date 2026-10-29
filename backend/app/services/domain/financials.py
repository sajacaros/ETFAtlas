"""DART 주요계정으로 계산하는 실적: 연결·별도 선택, 분기 금액, 부채비율."""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ...models.dart import StockFinancial

Q1, H1, Q3, ANNUAL = "11013", "11012", "11014", "11011"
REPORT_ORDER = {Q1: 1, H1: 2, Q3: 3, ANNUAL: 4}
REPORT_LABEL = {Q1: "1분기", H1: "반기", Q3: "3분기", ANNUAL: "사업보고서"}
INCOME = (("revenue", "매출액"), ("operating_income", "영업이익"), ("net_income", "당기순이익"))

Amounts = Dict[Tuple[int, str, str], Tuple[Optional[int], Optional[int]]]  # (연도, 보고서, 계정) → (금액, 누적)


def pick_fs(rows: List[StockFinancial]) -> Tuple[str, Amounts]:
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


def net_above_revenue(periods: List[Dict]) -> List[Dict]:
    """순이익이 매출액보다 큰 기간 (영업 밖의 이익이 컸다는 뜻)."""
    return [p for p in periods if p["revenue"] and p["net_income"] is not None and p["net_income"] > p["revenue"]]


@dataclass
class DebtRatio:
    year: int
    reprt_code: str
    debt: int
    equity: int

    @property
    def ratio(self) -> float:
        return self.debt / self.equity * 100


def latest_debt_ratio(amounts: Amounts) -> Optional[DebtRatio]:
    """가장 최근 보고서의 부채비율 (부채총계 ÷ 자본총계). 자본잠식(자본 0 이하)이면 그 앞 보고서로."""
    reports = sorted({(y, r) for y, r, acc in amounts if acc == "부채총계"},
                     key=lambda k: (k[0], REPORT_ORDER[k[1]]), reverse=True)
    for year, reprt in reports:
        debt = amounts[(year, reprt, "부채총계")][0]
        equity = (amounts.get((year, reprt, "자본총계")) or (None, None))[0]
        if debt is not None and equity and equity > 0:
            return DebtRatio(year, reprt, debt, equity)
    return None
