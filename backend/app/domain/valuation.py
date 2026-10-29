"""시가총액과 DART 실적으로 계산하는 밸류에이션: PER(최근 4분기·직전 사업연도), PBR, ROE.

시가총액 = 종가 × 상장주식수(보통주). 순이익·자본총계는 DART 주요계정(연결이 있으면 연결)이라 비지배지분을 포함한다.
분모가 0 이하(적자·자본잠식)면 배수를 내지 않는다 — 음수 PER은 뜻이 없다.
"""
from dataclasses import dataclass
from typing import Optional

from .financials import ANNUAL, REPORT_LABEL, Amounts, build_periods, latest_amount


@dataclass
class Earnings:
    label: str   # 기간 표기 (예: '2025.3Q~2026.2Q', '2025년')
    amount: int  # 순이익 (원)


@dataclass
class Valuation:
    price: float
    price_date: str
    shares: int
    ttm: Optional[Earnings]      # 최근 4개 분기 순이익 합
    annual: Optional[Earnings]   # 직전 사업연도 순이익
    equity: Optional[Earnings]   # 최근 보고서의 자본총계 (label은 보고서)

    @property
    def market_cap(self) -> float:
        return self.price * self.shares

    def _multiple(self, base: Optional[Earnings]) -> Optional[float]:
        return round(self.market_cap / base.amount, 2) if base and base.amount > 0 else None

    @property
    def per_ttm(self) -> Optional[float]:
        return self._multiple(self.ttm)

    @property
    def per_annual(self) -> Optional[float]:
        return self._multiple(self.annual)

    @property
    def pbr(self) -> Optional[float]:
        return self._multiple(self.equity)

    @property
    def roe(self) -> Optional[float]:
        """최근 4분기 순이익 ÷ 최근 자본총계 (%)."""
        if not self.ttm or not self.equity or self.equity.amount <= 0:
            return None
        return round(self.ttm.amount / self.equity.amount * 100, 2)


def _quarter_index(period: str) -> int:
    year, _, q = period.partition(".")
    return int(year) * 4 + int(q[0]) - 1


def ttm_earnings(amounts: Amounts) -> Optional[Earnings]:
    """순이익이 있는 가장 최근 분기부터 이어진 4개 분기의 합. 중간에 빈 분기가 있으면 None (4분기는 사업보고서가 나와야 생긴다)."""
    quarters = [p for p in build_periods(amounts, "quarter") if p["net_income"] is not None]
    if len(quarters) < 4:
        return None
    last4 = quarters[-4:]
    if _quarter_index(last4[-1]["period"]) - _quarter_index(last4[0]["period"]) != 3:
        return None
    return Earnings(f"{last4[0]['period']}~{last4[-1]['period']}", sum(p["net_income"] for p in last4))


def annual_earnings(amounts: Amounts) -> Optional[Earnings]:
    years = sorted((y for y, r, acc in amounts if r == ANNUAL and acc == "당기순이익" and amounts[(y, r, acc)][0] is not None),
                   reverse=True)
    return Earnings(f"{years[0]}년", amounts[(years[0], ANNUAL, "당기순이익")][0]) if years else None


def latest_equity(amounts: Amounts) -> Optional[Earnings]:
    found = latest_amount(amounts, "자본총계")
    if not found:
        return None
    year, reprt, amount = found
    return Earnings(f"{year}년 {REPORT_LABEL[reprt]}", amount)


def valuation(price: float, price_date: str, shares: int, amounts: Amounts) -> Valuation:
    return Valuation(price, price_date, shares, ttm_earnings(amounts), annual_earnings(amounts), latest_equity(amounts))
