"""DART 현금흐름(영업활동현금흐름·유형/무형자산의 취득)으로 계산하는 최근 4분기 합계와 잉여현금흐름(FCF).

현금흐름표는 분·반기 보고서도 연초부터의 누적만 준다 (stock_financials: 1분기는 amount·amount_cum, 반기·3분기는 amount_cum,
사업보고서는 amount). 그래서 최근 4분기 합계는 '올해 누적 + 직전 연간 − 직전 연도 같은 시점 누적'으로 만든다.
취득 금액은 회사마다 부호가 양수·음수로 섞여 있어 크기(절댓값)로 쓴다.
"""
from dataclasses import dataclass
from typing import Optional

from .financials import ANNUAL, Q1, REPORT_ORDER, Amounts, without_revenue

OCF, CAPEX, INTANGIBLE = "영업활동현금흐름", "유형자산의취득", "무형자산의취득"


@dataclass
class Flow:
    label: str   # 기간 표기 (예: '2025.3Q~2026.2Q', '2025년')
    amount: int


def ytd(amounts: Amounts, year: int, reprt: str, account: str) -> Optional[int]:
    """그 보고서의 연초부터 누적 금액 (사업보고서는 연간)."""
    value = amounts.get((year, reprt, account))
    if value is None:
        return None
    amount, cum = value
    if reprt == ANNUAL:
        return amount
    if reprt == Q1:
        return amount if amount is not None else cum
    return cum


def ttm_flow(amounts: Amounts, account: str) -> Optional[Flow]:
    """금액이 있는 가장 최근 보고서까지의 4개 분기 합. 직전 연도의 연간·같은 시점 누적이 없으면 None."""
    reports = sorted({(y, r) for y, r, acc in amounts if acc == account and ytd(amounts, y, r, account) is not None},
                     key=lambda k: (k[0], REPORT_ORDER[k[1]]), reverse=True)
    if not reports:
        return None
    year, reprt = reports[0]
    current = ytd(amounts, year, reprt, account)
    if reprt == ANNUAL:
        return Flow(f"{year}년", current)
    prev_annual, prev_same = ytd(amounts, year - 1, ANNUAL, account), ytd(amounts, year - 1, reprt, account)
    if prev_annual is None or prev_same is None:
        return None
    q = REPORT_ORDER[reprt]
    return Flow(f"{year - 1}.{q + 1}Q~{year}.{q}Q", current + prev_annual - prev_same)


def annual_flow(amounts: Amounts, year: int, account: str) -> Optional[int]:
    return ytd(amounts, year, ANNUAL, account)


def free_cash_flow(ocf: Optional[int], capex: Optional[int], intangible: Optional[int]) -> Optional[int]:
    """영업활동현금흐름 − 유형자산 취득 − 무형자산 취득. 무형자산 취득 줄이 없는 회사는 0으로 본다."""
    if ocf is None or capex is None:
        return None
    return ocf - abs(capex) - abs(intangible or 0)


def ttm_fcf(amounts: Amounts) -> Optional[Flow]:
    """최근 4분기 FCF. 영업현금흐름과 유형자산 취득이 같은 기간이어야 한다.
    금융사(매출액 계정 없음)는 영업현금흐름에 대출·예금·투자 흐름이 섞여 FCF가 뜻이 없어 None."""
    if without_revenue(amounts):
        return None
    ocf, capex = ttm_flow(amounts, OCF), ttm_flow(amounts, CAPEX)
    if not ocf or not capex or ocf.label != capex.label:
        return None
    intangible = ttm_flow(amounts, INTANGIBLE)
    value = free_cash_flow(ocf.amount, capex.amount, intangible.amount if intangible and intangible.label == ocf.label else None)
    return Flow(ocf.label, value)
