"""weight_change_calc: weight_changes에 저장할 행."""
from collections import defaultdict

import weight_change_calc
from fakes import FakeCursor


def _holdings(rows):
    holdings, names = defaultdict(lambda: defaultdict(dict)), {}
    weight_change_calc.add_holding_rows(holdings, names, rows)
    return holdings, names


def test_rows_compare_each_etf_with_its_previous_collection():
    holdings, names = _holdings([
        {'etf_code': 'A', 'etf_name': '에이', 'date': '2026-10-28', 'stock_code': '1', 'stock_name': '일', 'weight': 10},
        {'etf_code': 'A', 'etf_name': '에이', 'date': '2026-10-28', 'stock_code': '2', 'stock_name': '이', 'weight': 5},
        # 10-29는 빠졌다 — 10-30은 10-28과 비교한다
        {'etf_code': 'A', 'etf_name': '에이', 'date': '2026-10-30', 'stock_code': '1', 'stock_name': '일', 'weight': 12.5},
        {'etf_code': 'A', 'etf_name': '에이', 'date': '2026-10-30', 'stock_code': '3', 'stock_name': None, 'weight': '4'},
        # 이전 HOLDS가 없는 ETF는 비교하지 않는다
        {'etf_code': 'B', 'etf_name': None, 'date': '2026-10-30', 'stock_code': '1', 'stock_name': '일', 'weight': 1},
    ])
    rows = weight_change_calc.weight_change_rows(holdings, names, '2026-10-30')
    assert rows == [
        ('2026-10-30', '2026-10-28', 'A', '에이', '1', '일', 'increased', 10.0, 12.5, 2.5),
        ('2026-10-30', '2026-10-28', 'A', '에이', '2', '이', 'removed', 5.0, 0, -5.0),
        ('2026-10-30', '2026-10-28', 'A', '에이', '3', '3', 'added', 0, 4.0, 4.0),
    ]
    assert names['B'] == 'B'


def test_unchanged_weights_are_skipped():
    holdings, names = _holdings([
        {'etf_code': 'A', 'etf_name': 'A', 'date': d, 'stock_code': '1', 'stock_name': '일', 'weight': 3.00001}
        for d in ('2026-10-29', '2026-10-30')])
    assert weight_change_calc.weight_change_rows(holdings, names, '2026-10-30') == []


def test_pending_dates_redo_the_latest_day():
    assert weight_change_calc.pending_dates(['2026-10-30', '2026-10-28', '2026-10-29'], {'2026-10-28', '2026-10-30'}) == [
        '2026-10-29', '2026-10-30']


def test_compute_weight_changes_replaces_each_pending_day(monkeypatch):
    class Ctx:
        def __init__(self, conn, cur):
            self.pair = (conn, cur)

        def __enter__(self):
            return self.pair

        def __exit__(self, *exc):
            return False

    from fakes import FakeConn
    holds = [('{"etf_code": "A", "etf_name": "에이", "date": "%s", "stock_code": "1", "stock_name": "일", "weight": %s}'
              % (d, w),) for d, w in (("2026-10-29", 1), ("2026-10-30", 2))]
    cur = FakeCursor({
        "WITH DISTINCT h.date": [('{"date": "2026-10-29"}',), ('{"date": "2026-10-30"}',)],
        "SELECT base_date FROM weight_change_dates": [("2026-10-29",)],
        "h.date >= '2026-10-30'": holds,
        "h.date < '2026-10-30'": [('{"etf_code": "A", "date": "2026-10-29"}',)],
        "UNWIND": holds[:1],
    })
    conn = FakeConn(cur)
    monkeypatch.setattr(weight_change_calc, "age_cursor", lambda: Ctx(conn, cur))
    weight_change_calc.compute_weight_changes()
    inserts = [p for s, p in cur.sql if s.startswith("INSERT INTO weight_changes")]
    assert inserts == [[('2026-10-30', '2026-10-29', 'A', '에이', '1', '일', 'increased', 1.0, 2.0, 1.0)]]
    assert ("DELETE FROM weight_changes WHERE base_date = %s", ('2026-10-30',)) in cur.sql
