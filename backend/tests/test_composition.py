import asyncio

import pytest
from fastapi import HTTPException

from app.domain.composition import ETFAllocation, aggregate_composition, normalize_weights
from app.routers import etfs


def _h(code, name, weight):
    return {"stock_code": code, "stock_name": name, "weight": weight}


def test_normalize_weights_scales_to_100():
    allocations = [
        ETFAllocation("A", "a", 15, []),
        ETFAllocation("B", "b", 10, []),
        ETFAllocation("C", "c", 10, []),
        ETFAllocation("D", "d", 5, []),
    ]
    assert normalize_weights(allocations) == pytest.approx({"A": 37.5, "B": 25, "C": 25, "D": 12.5})


def test_normalize_weights_ignores_zero_and_handles_empty():
    assert normalize_weights([ETFAllocation("A", "a", 0, [])]) == {}
    assert normalize_weights([ETFAllocation("A", "a", 0, []), ETFAllocation("B", "b", 20, [])]) == {"B": 100}


def test_aggregate_sums_overlapping_stocks_and_sorts():
    allocations = [
        ETFAllocation("SEMI", "반도체", 30, [_h("005930", "삼성전자", 25), _h("000660", "SK하이닉스", 30)]),
        ETFAllocation("DIV", "고배당", 10, [_h("005930", "삼성전자", 10), _h("105560", "KB금융", 8)]),
    ]
    result = aggregate_composition(allocations)

    assert [s.stock_code for s in result] == ["000660", "005930", "105560"]
    samsung = result[1]
    # 반도체 75% × 25% + 고배당 25% × 10%
    assert samsung.weight == pytest.approx(18.75 + 2.5)
    assert [(e.code, round(e.weight, 4)) for e in samsung.etfs] == [("SEMI", 18.75), ("DIV", 2.5)]
    assert result[2].weight == pytest.approx(2.0)


def test_aggregate_skips_zero_weight_holdings():
    allocations = [ETFAllocation("A", "a", 10, [_h("1", "x", 0), _h("2", "y", None), _h("3", "z", 5)])]
    assert [s.stock_code for s in aggregate_composition(allocations)] == ["3"]


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def all(self):
        return self.rows


class _ETFRow:
    def __init__(self, code, name):
        self.code = code
        self.name = name


class FakeDB:
    def query(self, model):
        return _Query([_ETFRow("SEMI", "반도체"), _ETFRow("DIV", "고배당")])


@pytest.fixture
def fake_graph(monkeypatch):
    holdings = {
        "SEMI": [{**_h("005930", "삼성전자", 25), "recorded_at": "2026-10-06"}],
        "DIV": [{**_h("005930", "삼성전자", 10), "recorded_at": "2026-10-02"}]
        + [{**_h(f"S{i:02d}", f"종목{i}", 1), "recorded_at": "2026-10-02"} for i in range(40)],
    }
    calls = []

    class FakeGraph:
        def __init__(self, db):
            pass

        def get_etf_holdings_full(self, code):
            calls.append(code)
            return holdings.get(code, [])

    monkeypatch.setattr(etfs, "GraphService", FakeGraph)
    return calls


def _run(items):
    request = etfs.CompositionRequest(items=[etfs.CompositionItem(code=c, weight=w) for c, w in items])
    return asyncio.run(etfs.get_composition(request, db=FakeDB()))


def test_composition_endpoint_limits_to_top_30(fake_graph):
    res = _run([("SEMI", 15), ("DIV", 5), ("CASH", 60)])

    assert res.total_stocks == 41
    assert len(res.stocks) == 30
    top = res.stocks[0]
    assert (top.rank, top.stock_name) == (1, "삼성전자")
    # 현금은 환산에서 빠지므로 반도체 75%, 고배당 25%
    assert top.weight == pytest.approx(75 * 0.25 + 25 * 0.10)
    assert [e.name for e in top.etfs] == ["반도체", "고배당"]
    assert res.as_of == "2026-10-06"
    assert "CASH" not in fake_graph


def test_composition_endpoint_rejects_duplicate_etf(fake_graph):
    with pytest.raises(HTTPException) as exc:
        _run([("SEMI", 10), ("SEMI", 5)])
    assert exc.value.status_code == 400
