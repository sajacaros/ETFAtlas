import asyncio

import pytest

from app.services.flow import executor as ex
from app.domain import indicators as ind
from app.services.flow.base import FlowContext, Node, StockSet, node_spec, result
from app.services.flow.market_data import YFinanceMarketData
from app.services.flow.nodes import REGISTRY
from app.services.flow.nodes.chart_filter import ChartFilterNode, ChartFilterParams, metrics, passes
from app.services.flow.nodes.combine import combine
from app.services.flow.nodes.result_view import ResultNode, ResultParams
from app.services.flow.nodes.source import SourceParams
from app.services.flow.templates import TEMPLATES


def _bars(closes, volume=1000.0, spread=0.01):
    return [
        {"date": f"2026-01-{i % 28 + 1:02d}", "open": c, "high": c * (1 + spread), "low": c * (1 - spread), "close": c, "volume": volume}
        for i, c in enumerate(closes)
    ]


# --- indicators ---

def test_sma_and_period_return():
    assert ind.sma([1, 2, 3, 4], 2) == 3.5
    assert ind.sma([1, 2], 3) is None
    assert ind.period_return([100, 110, 121], 2) == pytest.approx(21.0)
    assert ind.period_return([100], 1) is None


def test_from_high_is_zero_at_new_high_and_negative_below():
    rising = _bars(range(100, 130), spread=0)
    assert ind.from_high(rising, 20) == pytest.approx(0)
    falling = _bars([100] * 10 + [90], spread=0)
    assert ind.from_high(falling, 11) == pytest.approx(-10)


def test_volume_ratio_compares_last_day_with_previous_average():
    assert ind.volume_ratio([100] * 20 + [300]) == pytest.approx(3)
    assert ind.volume_ratio([100] * 5) is None


def test_rsi_extremes():
    assert ind.rsi(list(range(1, 30))) == 100.0
    assert ind.rsi(list(range(30, 1, -1))) == pytest.approx(0)


def test_ma_aligned_on_steady_uptrend():
    assert ind.ma_aligned(list(range(1, 80))) is True
    assert ind.ma_aligned(list(range(80, 1, -1))) is False
    assert ind.ma_aligned(list(range(1, 30))) is None  # 60일 이평을 못 구한다


def test_vcp_needs_shrinking_ranges_near_high_with_drying_volume():
    bars = []
    for spread, vol in ((0.10, 3000), (0.05, 2000), (0.02, 1000)):
        bars += [{"date": "d", "open": 100, "high": 100 * (1 + spread / 2), "low": 100 * (1 - spread / 2), "close": 100, "volume": vol}] * 20
    assert ind.is_vcp(bars) is True
    widening = list(reversed(bars))
    assert ind.is_vcp(widening) is False
    assert ind.is_vcp(bars[:50]) is None


def test_days_since_golden_cross_counts_from_the_crossing_day():
    assert ind.days_since_golden_cross([1, 1, 3, 4], [2, 2, 2, 2]) == 1  # 셋째 날에 뚫었다
    assert ind.days_since_golden_cross([1, 3], [2, 2]) == 0
    assert ind.days_since_golden_cross([3, 1], [2, 2]) is None  # 지금은 아래
    assert ind.days_since_golden_cross([3, 3], [2, 2]) is None  # 내내 위라 교차를 못 봤다


def test_macd_crosses_up_after_a_fall_turns_into_a_rise():
    closes = [float(c) for c in list(range(200, 140, -1)) + list(range(140, 160))]
    line, signal = ind.macd(closes)
    assert len(line) == len(signal) == len(closes) - 33
    days = ind.days_since_golden_cross(line, signal)
    assert days is not None and days < 20
    assert ind.macd(closes[:34]) is None  # 시그널선이 하나뿐이면 교차를 못 본다


def test_stoch_slow_is_high_in_uptrend_and_low_in_downtrend():
    k, d = ind.stoch_slow(_bars(range(100, 140)))
    assert len(k) == len(d) and k[-1] > 70  # 고가가 종가보다 1% 위라 100까지는 못 간다
    k, _ = ind.stoch_slow(_bars(range(140, 100, -1)))
    assert k[-1] < 30
    flat = [{"date": "d", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}] * 20
    assert ind.stoch_slow(flat)[0][-1] == 50.0
    assert ind.stoch_slow(_bars(range(10))) is None


def test_bollinger_pctb_places_close_inside_or_outside_the_band():
    assert ind.bollinger_pctb([100.0, 102.0] * 10) == pytest.approx(75)  # 마지막이 평균 + 1σ, 밴드는 ±2σ
    assert ind.bollinger_pctb([100.0] * 19 + [90.0]) < 0  # 급락은 하단 밖
    assert ind.bollinger_pctb([100.0] * 20) is None
    assert ind.bollinger_pctb([100.0] * 5) is None



def test_series_end_at_the_last_value_the_screener_uses():
    closes = [float(c) for c in list(range(100, 130)) + list(range(130, 110, -1))]
    series = ind.rsi_series(closes)
    assert len(series) == len(closes) - 14 and series[-1] == pytest.approx(ind.rsi(closes))
    assert ind.rsi_series(closes[:14]) == [] and ind.rsi(closes[:14]) is None
    bands = ind.bollinger_series(closes)
    mid, upper, lower = bands[-1]
    assert len(bands) == len(closes) - 19 and mid == pytest.approx(sum(closes[-20:]) / 20)
    assert (closes[-1] - lower) / (upper - lower) * 100 == pytest.approx(ind.bollinger_pctb(closes))


def test_last_cross_reports_direction_and_days_ago():
    assert ind.last_cross([1, 3, 3], [2, 2, 2]) == ("golden", 1)
    assert ind.last_cross([1, 3, 1], [2, 2, 2]) == ("dead", 0)
    assert ind.last_cross([3, 3], [2, 2]) is None

# --- chart filter ---

def test_filter_conditions_are_anded_and_missing_values_fail():
    p = ChartFilterParams(ma_aligned=True, rsi_max=90)
    up = metrics(_bars(range(100, 200)), p)
    assert up["ma_aligned"] is True
    assert passes(up, ChartFilterParams(ma_aligned=True)) is True
    assert passes(up, ChartFilterParams(ma_aligned=True, rsi_max=50)) is False  # 계속 오르면 RSI 100
    assert passes({**up, "rsi": None}, ChartFilterParams(rsi_min=10)) is False
    assert passes(up, ChartFilterParams()) is True  # 켠 조건이 없으면 통과


def test_cross_and_bollinger_conditions():
    m = {"macd_cross": 2, "stoch_cross": 0, "stoch_cross_k": 15.0, "bb_pctb": 5.0}
    assert passes(m, ChartFilterParams(macd_cross_days=3)) is True
    assert passes(m, ChartFilterParams(macd_cross_days=2)) is False  # 1이면 마지막 거래일만
    assert passes(m, ChartFilterParams(stoch_cross_days=1, stoch_cross_below=20)) is True
    assert passes(m, ChartFilterParams(stoch_cross_days=1, stoch_cross_below=10)) is False
    assert passes(m, ChartFilterParams(bb_pctb_max=10)) is True
    assert passes(m, ChartFilterParams(bb_pctb_min=10)) is False
    assert passes({**m, "macd_cross": None}, ChartFilterParams(macd_cross_days=20)) is False


def test_metrics_report_crosses_from_bars():
    m = metrics(_bars(list(range(200, 140, -1)) + list(range(140, 160))), ChartFilterParams())
    assert m["macd_cross"] is not None and m["stoch_k"] > 70 and m["bb_pctb"] > 50
    if m["stoch_cross"] is not None:
        assert m["stoch_cross_k"] is not None


class FakeMarket:
    def __init__(self, bars):
        self._bars = bars

    def bars(self, codes):
        return {c: self._bars[c] for c in codes if c in self._bars}


def _ctx(market=None):
    return FlowContext(user_id=1, session_factory=lambda: None, ai_config=None, market=market or FakeMarket({}), stop=asyncio.Event())


async def _collect(gen):
    return [e async for e in gen]


def test_chart_filter_node_keeps_passing_stocks_and_drops_short_history():
    market = FakeMarket({
        "000001": _bars(range(100, 200)),          # 상승 → 정배열
        "000002": _bars(range(200, 100, -1)),      # 하락
        "000003": _bars(range(100, 130)),          # 30일뿐 → 제외
    })
    source = StockSet(rows={c: {"code": c, "name": c} for c in ("000001", "000002", "000003", "000004")})
    events = asyncio.run(_collect(ChartFilterNode().run(ChartFilterParams(ma_aligned=True), [source], _ctx(market))))
    items = events[-1]["items"]
    assert list(items.rows) == ["000001"]
    assert "ret" in items.fields and items.rows["000001"]["ret"] > 0
    assert any("2종목은 제외" in n for n in items.notes)


# --- combine / result ---

def test_combine_intersection_keeps_first_order_and_merges_values():
    a = StockSet(rows={"A": {"code": "A", "x": 1}, "B": {"code": "B", "x": 2}, "C": {"code": "C", "x": 3}})
    a.add_field("x", "X")
    b = StockSet(rows={"C": {"code": "C", "y": 9}, "A": {"code": "A", "y": 8}})
    b.add_field("y", "Y")
    out = combine([a, b], "intersection")
    assert list(out.rows) == ["A", "C"]
    assert out.rows["A"] == {"code": "A", "x": 1, "y": 8}
    assert list(out.fields) == ["x", "y"]
    assert list(combine([a, b], "union").rows) == ["A", "B", "C"]


def test_result_sorts_with_missing_values_last_and_limits():
    s = StockSet(rows={"A": {"code": "A", "v": 1}, "B": {"code": "B", "v": None}, "C": {"code": "C", "v": 5}})
    s.add_field("v", "V")
    events = asyncio.run(_collect(ResultNode().run(ResultParams(sort_by="v", limit=2), [s], _ctx())))
    assert list(events[-1]["items"].rows) == ["C", "A"]
    with pytest.raises(ValueError, match="정렬할 열"):
        asyncio.run(_collect(ResultNode().run(ResultParams(sort_by="nope"), [s], _ctx())))


# --- executor ---

class FakeSource(Node):
    type = "source"
    label = "가짜 소스"
    category = "source"
    description = ""
    Params = SourceParams
    min_inputs = 0
    max_inputs = 0

    async def run(self, params, inputs, ctx):
        codes = [c.strip() for c in params.codes.split(",") if c.strip()]
        if not codes:
            raise ValueError("종목을 입력하세요")
        yield result(StockSet(rows={c: {"code": c, "name": c} for c in codes}))


@pytest.fixture
def fake_registry(monkeypatch):
    monkeypatch.setitem(ex.REGISTRY, "source", FakeSource)


def _graph(nodes, edges):
    return ex.FlowGraph.model_validate({
        "nodes": [{"id": i, "type": t, "params": p} for i, t, p in nodes],
        "edges": [{"source": s, "target": t} for s, t in edges],
    })


def test_topo_order_rejects_bad_graphs():
    with pytest.raises(ex.FlowGraphError, match="모르는"):
        ex.topo_order(_graph([("a", "nope", {})], []))
    with pytest.raises(ex.FlowGraphError, match="순환"):
        ex.topo_order(_graph([("a", "result", {}), ("b", "result", {})], [("a", "b"), ("b", "a")]))
    with pytest.raises(ex.FlowGraphError, match="없는 노드"):
        ex.topo_order(_graph([("a", "result", {})], [("a", "z")]))
    assert ex.topo_order(_graph([("out", "result", {}), ("src", "source", {})], [("src", "out")])) == ["src", "out"]


def test_run_flow_skips_descendants_of_failed_node_and_runs_other_branches(fake_registry):
    graph = _graph(
        [
            ("bad", "source", {"mode": "codes", "codes": ""}),
            ("bad_out", "result", {}),
            ("good", "source", {"mode": "codes", "codes": "A,B"}),
            ("both", "combine", {"op": "intersection"}),
            ("good_out", "result", {"limit": 1}),
            ("lonely", "result", {}),
        ],
        [("bad", "bad_out"), ("good", "both"), ("good", "good_out")],
    )
    events = asyncio.run(_collect(ex.run_flow(graph, _ctx())))
    by_node = {e["data"]["id"]: e for e in events if "id" in e.get("data", {}) and e["type"] != "node_start"}
    assert by_node["bad"]["type"] == "node_error"
    assert by_node["bad_out"]["type"] == "node_skipped"
    assert by_node["both"]["type"] == "node_error" and "2개 이상" in by_node["both"]["data"]["message"]
    assert by_node["good_out"]["type"] == "node_done" and by_node["good_out"]["data"]["count"] == 1
    assert by_node["lonely"]["data"]["message"] == "입력을 연결하세요"
    assert events[-1]["type"] == "run_done"


def test_run_flow_reports_invalid_params_on_the_node(fake_registry):
    graph = _graph([("src", "source", {"mode": "codes", "codes": "A"}), ("out", "result", {"limit": 0})], [("src", "out")])
    events = asyncio.run(_collect(ex.run_flow(graph, _ctx())))
    error = next(e for e in events if e["type"] == "node_error")
    assert error["data"]["id"] == "out" and "limit" in error["data"]["message"]


# --- catalog / templates ---

def test_catalog_specs_render_every_param():
    specs = {n.type: node_spec(n) for n in REGISTRY.values()}
    source = {p["key"]: p for p in specs["source"]["params"]}
    assert source["mode"]["type"] == "select"
    assert {o["value"] for o in source["mode"]["options"]} == {"all", "etf", "portfolio", "codes"}
    assert source["portfolio_id"]["type"] == "portfolio" and source["portfolio_id"]["nullable"]
    chart = {p["key"]: p for p in specs["chart_filter"]["params"]}
    assert chart["ma_aligned"]["type"] == "bool" and chart["rsi_min"]["type"] == "number"


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t["key"])
def test_templates_are_valid_graphs_with_valid_params(template):
    graph = ex.FlowGraph.model_validate(template["graph"])
    ex.topo_order(graph)
    for n in graph.nodes:
        REGISTRY[n.type].Params.model_validate(n.params)


# --- market data cache ---

def test_market_data_tries_kosdaq_after_kospi_and_remembers_the_market(monkeypatch):
    calls = []

    def fake_download(tickers):
        calls.append(sorted(tickers))
        return {t: _bars([1, 2]) for t in tickers if t in ("A.KS", "B.KQ")}

    md = YFinanceMarketData()
    monkeypatch.setattr(md, "_download", fake_download)
    assert set(md.bars(["A", "B", "C"])) == {"A", "B"}
    assert calls == [["A.KS", "B.KS", "C.KS"], ["B.KQ", "C.KQ"]]
    calls.clear()
    md._cache.clear()  # 캐시가 만료돼도 시장 구분은 기억한다
    md.bars(["B"])
    assert calls == [["B.KQ"]]


# --- AI analysis facts ---

def test_ai_facts_do_not_repeat_values_the_upstream_node_computed():
    from app.services.flow.nodes.ai_analysis import facts

    s = StockSet()
    s.add_field("ret", "20일 수익률", "percent")
    lines = facts({"code": "A", "ret": 12.5}, _bars(range(100, 200)), [{"etf": "KODEX 200", "weight": 3.2}], s.fields)
    labels = [line.split(":")[0] for line in lines]
    assert labels.count("20일 수익률") == 1 and "20일 수익률: 12.50%" in lines
    assert "100일 고가 대비" in labels  # 기간은 실제 일봉 길이로
    assert lines[-1] == "담은 ETF 수: 1개 (비중 큰 순: KODEX 200 3.20%)"


# --- ETF search (EtfPicker) ---

def test_universe_search_requires_every_word_ignoring_spaces(monkeypatch):
    from app.services.graph_service import GraphService

    captured = {}

    def fake_execute(self, query, params=None, raise_errors=False):
        captured["query"], captured["params"] = query, params
        return []

    monkeypatch.setattr(GraphService, "execute_cypher", fake_execute)
    g = GraphService(None)
    assert g.search_etfs_in_universe("반도체  KODEX", 5) == []
    assert captured["params"]["q0"] == "반도체" and captured["params"]["q1"] == "kodex"
    assert captured["query"].count("replace(toLower(e.name), ' ', '') CONTAINS") == 2
    assert "RETURN {code: e.code" in captured["query"]


def test_return_period_is_fixed_and_old_saved_option_is_ignored():
    from app.services.flow.nodes.chart_filter import RETURN_DAYS

    p = ChartFilterParams.model_validate({"return_days": 5, "return_min": 0})  # 예전에 저장한 흐름
    assert not hasattr(p, "return_days")
    closes = list(range(100, 200))
    assert metrics(_bars(closes), p)["ret"] == pytest.approx(round((closes[-1] / closes[-1 - RETURN_DAYS] - 1) * 100, 2))
    keys = [s["key"] for s in node_spec(ChartFilterNode)["params"]]
    assert "return_days" not in keys
