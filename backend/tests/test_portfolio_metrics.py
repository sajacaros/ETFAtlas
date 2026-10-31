from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.domain.portfolio_metrics import (
    BASE_AMOUNT, common_dates, covers_period, daily_change, invested_amount, risk_metrics, simulate, total_return,
)

D = [date(2026, 10, 1) + timedelta(days=i) for i in range(5)]


def test_common_dates_needs_every_ticker():
    prices = {"A": {D[0]: 1, D[1]: 1, D[2]: 1}, "B": {D[1]: 1, D[2]: 1, D[3]: 1}}
    assert common_dates(prices, ["A", "B"]) == [D[1], D[2]]
    assert common_dates(prices, ["A", "B"], since=D[2]) == [D[2]]


def test_simulate_normalizes_weights_and_buys_on_the_first_day():
    prices = {"A": {D[0]: 100, D[1]: 110}, "B": {D[0]: 50, D[1]: 50}}
    values = simulate({"A": 30, "B": 30}, prices, [D[0], D[1]])
    assert values == [(D[0], BASE_AMOUNT), (D[1], pytest.approx(BASE_AMOUNT * 1.05))]
    assert total_return(values) == pytest.approx(5.0)


def test_simulate_without_weights_or_dates():
    assert simulate({"A": 0}, {"A": {D[0]: 1, D[1]: 1}}, [D[0], D[1]]) is None
    assert simulate({"A": 1}, {"A": {D[0]: 1}}, [D[0]]) is None


def test_risk_metrics_drawdown_and_volatility():
    values = [(D[0], 100.0), (D[1], 120.0), (D[2], 90.0), (D[3], 110.0)]
    metrics = risk_metrics(values)
    assert metrics.mdd == pytest.approx(-25.0)
    assert [round(dd, 2) for _, dd in metrics.drawdowns] == [0.0, 0.0, -25.0, -8.33]
    assert metrics.volatility > 0


def test_covers_period():
    assert covers_period([D[0], D[0] + timedelta(days=21)], 30)
    assert not covers_period([D[0], D[0] + timedelta(days=20)], 30)


def test_invested_amount_adds_cash_only_with_avg_price():
    h = lambda t, q, p=None: SimpleNamespace(ticker=t, quantity=q, avg_price=p)
    assert invested_amount([h("CASH", 1000), h("069500", 10)]) is None
    assert invested_amount([h("CASH", 1000), h("069500", 10, 50)]) == Decimal("1500")


def test_daily_change():
    assert daily_change(Decimal("110"), Decimal("100")) == (Decimal("10"), 10.0)
    assert daily_change(Decimal("110"), None) == (None, None)
