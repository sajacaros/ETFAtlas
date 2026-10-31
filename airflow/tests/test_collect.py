"""수집 순수 함수: Price 항목, 상위 구성종목, 유니버스 정리, 구성종목 날짜."""
from datetime import datetime

import pytest

import collect_holdings
import collect_prices
import universe
from kis_api_client import DailyBar, ETFComponent, ETFSnapshot
from market_calendar import compact_date, dash_date, days_before, holdings_target_date


def _bar(d, close=100):
    return DailyBar(date=d, open=90, high=110, low=80, close=close, volume=5, change_rate=1.5, trade_value=500)


def test_date_formats():
    assert dash_date("20261030") == "2026-10-30" and compact_date("2026-10-30") == "20261030"
    assert days_before("20261101", 2) == "20261030"


def test_etf_price_items_keep_requested_dates_and_snapshot_only_on_the_latest():
    snap = ETFSnapshot(code="069500", price=120, nav=101.5, net_assets=10**12, listed_shares=1000,
                       component_count=50, active=False)
    items = collect_prices.etf_price_items("069500", [_bar("20261028"), _bar("20261029"), _bar("20261030", 120)],
                                           ["20261029", "20261030"], "20261030", snap)
    assert [i['date'] for i in items] == ["2026-10-29", "2026-10-30"]
    assert items[0]['nav'] is None and items[0]['market_cap'] is None
    assert items[1] == {'code': '069500', 'date': '2026-10-30', 'open': 90, 'high': 110, 'low': 80, 'close': 120,
                        'volume': 5, 'trade_value': 500, 'nav': 101.5, 'market_cap': 120_000, 'net_assets': 10**12}


def test_stock_price_item():
    assert collect_prices.stock_price_item("005930", _bar("20261030")) == {
        'code': '005930', 'date': '2026-10-30', 'open': 90.0, 'high': 110.0, 'low': 80.0, 'close': 100.0,
        'volume': 5, 'change_rate': 1.5}


def test_snapshot_property_items_skip_missing_values():
    snaps = {"A": ETFSnapshot("A", 1, 1, 1, 1, component_count=0, active=True),
             "B": ETFSnapshot("B", 1, 1, 1, 1, dividend_cycle=1, component_count=30)}
    codes = {"A", "B", "C"}
    assert collect_prices.snapshot_property_items(codes, snaps, lambda c, s: s.component_count or None) == [
        {'code': 'B', 'value': 30}]
    assert collect_prices.snapshot_property_items(codes, snaps, lambda c, s: s.active) == [{'code': 'A', 'value': True}]


def test_top_holdings_keep_listed_codes_by_weight():
    comps = [ETFComponent(f"{i:06d}", f"S{i}", float(i), 1, 1) for i in range(40)]
    comps += [ETFComponent("010010", "설정현금액", 99.0, 1, 1), ETFComponent("KR7005930003", "채권", 98.0, 1, 1)]
    top = collect_holdings.top_holdings(comps)
    assert len(top) == collect_holdings.HOLDINGS_TOP_N == 30
    assert top[0].stock_code == "000039" and top[-1].stock_code == "000010"


def test_holdings_retry_needed():
    assert collect_holdings.holdings_retry_needed(20, 100, last_try=False)
    assert not collect_holdings.holdings_retry_needed(19, 100, last_try=False)
    assert not collect_holdings.holdings_retry_needed(50, 100, last_try=True)
    assert not collect_holdings.holdings_retry_needed(0, 100, last_try=False)


def test_stock_name_items_prefer_graph_names_for_etfs():
    items = collect_holdings.stock_name_items(["069500", "005930", "999999"], {"069500"},
                                              {"069500": "KODEX 200"}, {"069500": "KIS이름", "005930": "삼성전자"})
    assert sorted(items, key=lambda i: i['code']) == [
        {'code': '005930', 'name': '삼성전자', 'is_etf': False},
        {'code': '069500', 'name': 'KODEX 200', 'is_etf': True},
        {'code': '999999', 'name': '999999', 'is_etf': False}]


def test_delisted_codes_refuse_a_suspicious_master():
    existing = {f"{i:06d}" for i in range(100)}
    master = {c: "x" for c in existing}
    assert universe.delisted_codes(existing, {k: v for k, v in master.items() if k != "000001"}) == ["000001"]
    assert universe.delisted_codes(existing, dict(list(master.items())[:80])) == []  # 20% 사라짐 → 마스터 이상


def test_renamed_etfs_bring_the_new_company():
    renamed = universe.renamed_etfs([{"code": "A", "name": "KODEX 반도체"}, {"code": "B", "name": "TIGER 200"}],
                                    {"A": "RISE 반도체", "B": "TIGER 200"})
    assert renamed == [{'code': 'A', 'name': 'RISE 반도체', 'old_name': 'KODEX 반도체', 'company': 'KB자산운용'}]


@pytest.mark.parametrize("name,tag", [("KODEX 200", "코스피"), ("TIGER 코스닥150", "코스닥"), ("KODEX 반도체", None)])
def test_index_tag(name, tag):
    assert universe.index_tag(name) == tag


@pytest.mark.parametrize("now,is_open,expected", [
    ("2026-10-30 08:34", True, None),         # 공시 갱신 전
    ("2026-10-30 08:35", True, "20261030"),
    ("2026-10-30 16:30", True, "20261030"),
    ("2026-10-31 09:00", False, None),        # 휴장일
])
def test_holdings_target_date(now, is_open, expected):
    seen = []
    target = holdings_target_date(datetime.strptime(now, "%Y-%m-%d %H:%M"),
                                  market_open=lambda d: seen.append(d) or is_open)
    assert target == expected
    assert seen in ([], [datetime.strptime(now, "%Y-%m-%d %H:%M").date()])


def test_holdings_target_date_fails_when_the_calendar_is_unknown():
    with pytest.raises(RuntimeError):
        holdings_target_date(datetime(2026, 10, 30, 9, 0), market_open=lambda d: None)
