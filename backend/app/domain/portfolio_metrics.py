"""목표 비중대로 샀다고 가정한 가상 포트폴리오의 가치·수익률·위험 지표. 내 포트폴리오와 공유 포트폴리오가 함께 쓴다."""
import math
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping, Optional

from .portfolio_calculation import CASH_TICKER

BASE_AMOUNT = 10_000_000  # 시작일에 이 금액을 비중대로 나눠 산다고 본다
TRADING_DAYS = 252  # 연율화에 쓰는 1년 거래일 수
RISK_FREE_RATE = 3.5  # 샤프 지수의 무위험 수익률 (연 %)
MIN_PERIOD_COVERAGE = 0.7  # 공통 시세가 요청 기간의 이 비율도 안 되면 계산하지 않는다 (갓 상장한 종목이 섞인 경우)

PriceHistory = Mapping[str, Mapping[date, float]]  # 티커 → 날짜 → 종가


def common_dates(prices: PriceHistory, tickers: Iterable[str], since: Optional[date] = None) -> list[date]:
    """모든 티커의 시세가 있는 날짜 (오름차순)."""
    tickers = list(tickers)
    dates = set().union(*(prices.get(t, {}) for t in tickers)) if tickers else set()
    return sorted(d for d in dates if (since is None or d >= since) and all(d in prices.get(t, {}) for t in tickers))


def covers_period(dates: list[date], days: int) -> bool:
    return len(dates) >= 2 and (dates[-1] - dates[0]).days >= days * MIN_PERIOD_COVERAGE


def simulate(weights: Mapping[str, float], prices: PriceHistory, dates: list[date]) -> Optional[list[tuple[date, float]]]:
    """dates 첫날 BASE_AMOUNT를 비중(합이 1이 되게 정규화)대로 산 포트폴리오의 날짜별 가치. 비중이 없거나 날짜가 모자라면 None."""
    total_weight = sum(weights.values())
    if total_weight <= 0 or len(dates) < 2:
        return None
    start = dates[0]
    quantities = {
        t: BASE_AMOUNT * (w / total_weight) / prices[t][start] if prices[t][start] > 0 else 0
        for t, w in weights.items()
    }
    return [(d, sum(q * prices[t][d] for t, q in quantities.items())) for d in dates]


def total_return(values: list[tuple[date, float]]) -> float:
    return (values[-1][1] - BASE_AMOUNT) / BASE_AMOUNT * 100


@dataclass
class RiskMetrics:
    total_return: float
    mdd: float
    volatility: float
    sharpe_ratio: Optional[float]
    drawdowns: list[tuple[date, float]] = field(default_factory=list)


def risk_metrics(values: list[tuple[date, float]]) -> RiskMetrics:
    """simulate() 결과의 수익률(%)·최대 낙폭(%)·연율 변동성(%)·샤프 지수."""
    peak = values[0][1]
    mdd = 0.0
    drawdowns = []
    for d, v in values:
        peak = max(peak, v)
        dd = (v - peak) / peak * 100 if peak > 0 else 0.0
        mdd = min(mdd, dd)
        drawdowns.append((d, dd))

    daily_returns = [
        (curr - prev) / prev if prev > 0 else 0.0
        for (_, prev), (_, curr) in zip(values, values[1:])
    ]
    volatility = 0.0
    if len(daily_returns) >= 2:
        mean = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
        volatility = math.sqrt(variance) * math.sqrt(TRADING_DAYS) * 100

    sharpe = None
    if volatility > 0:
        annualized = ((values[-1][1] / BASE_AMOUNT) ** (TRADING_DAYS / len(daily_returns)) - 1) * 100
        sharpe = round((annualized - RISK_FREE_RATE) / volatility, 2)

    return RiskMetrics(total_return(values), mdd, volatility, sharpe, drawdowns)


def invested_amount(holdings: Iterable) -> Optional[Decimal]:
    """평단가 × 수량의 합. 평단가를 넣은 종목이 하나도 없으면 None, 있으면 예수금(CASH)도 더한다.

    holdings: .ticker, .quantity, .avg_price 를 가진 객체들
    """
    invested = Decimal("0")
    cash = Decimal("0")
    has_avg_price = False
    for h in holdings:
        if h.ticker == CASH_TICKER:
            if h.quantity:
                cash = Decimal(str(h.quantity))
        elif h.avg_price is not None and h.quantity:
            invested += Decimal(str(h.quantity)) * Decimal(str(h.avg_price))
            has_avg_price = True
    return invested + cash if has_avg_price else None


def daily_change(total_value: Decimal, prev_value: Optional[Decimal]) -> tuple[Optional[Decimal], Optional[float]]:
    """스냅샷의 전일 대비 (금액, %). 이전 스냅샷이 없으면 (None, None)."""
    if not prev_value:
        return None, None
    amount = total_value - prev_value
    return amount, float(amount / prev_value * 100)
