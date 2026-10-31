"""returns: ETF 수익률 계산."""
import returns


def test_etf_returns_pick_the_last_price_on_or_before_each_target():
    prices = [  # 최근 날짜부터
        {'date': '2026-10-30', 'close': 110, 'market_cap': 1100},
        {'date': '2026-10-29', 'close': 100, 'market_cap': 1000},
        {'date': '2026-10-23', 'close': 88, 'market_cap': 800},
        {'date': '2026-10-22', 'close': 50, 'market_cap': 500},
        {'date': '2026-09-29', 'close': 55, 'market_cap': None},
    ]
    assert returns.etf_returns('A', prices) == {
        'code': 'A', 'close_price': 110.0, 'return_1d': 10.0, 'return_1w': 25.0, 'return_1m': 100.0,
        'market_cap_change_1w': 37.5}


def test_etf_returns_without_history_or_price():
    assert returns.etf_returns('A', []) is None
    assert returns.etf_returns('A', [{'date': '2026-10-30', 'close': 0}]) is None
    only = returns.etf_returns('A', [{'date': '2026-10-30', 'close': 10}])
    assert only['return_1d'] is None and only['return_1w'] is None and only['return_1m'] is None


def test_group_recent_prices_caps_each_etf():
    rows = [{'code': 'A', 'date': f"2026-{m:02d}-01", 'close': 1} for m in range(12, 0, -1)] * 5
    rows.append({'code': 'B', 'date': None, 'close': 1})
    grouped = returns.group_recent_prices(rows)
    assert len(grouped['A']) == returns.RETURNS_MAX_PRICES and 'B' not in grouped
