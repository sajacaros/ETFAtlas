"""종목 스크리너의 기록·채점·자동 실행·ETF 신호 노드."""
import asyncio
from datetime import date, datetime

import pytest

from app.services.flow import scheduler
from app.services.flow.base import FlowContext, StockSet
from app.services.flow.executor import FlowGraph
from app.services.flow.market_data import FreshMarketData, YFinanceMarketData
from app.services.flow.nodes import etf_signal
from app.services.flow.nodes.etf_signal import ETFSignalNode, ETFSignalParams
from app.services.flow.performance import evaluate, score_run, summarize
from app.services.flow.records import PickCollector, same_graph

DAYS = [f"2026-10-{d:02d}" for d in (1, 2, 5, 6, 7, 8, 12, 13, 14, 15, 16)]


def _graph(nodes, edges=(), positions=None):
    return FlowGraph.model_validate({
        "nodes": [{"id": i, "type": t, "params": p, "position": (positions or {}).get(i)} for i, t, p in nodes],
        "edges": [{"id": f"x-{s}-{t}", "source": s, "target": t} for s, t in edges],
    })


# --- 채점 ---

def test_score_enters_at_next_trading_day_close_and_compares_with_benchmark(monkeypatch):
    monkeypatch.setattr("app.services.flow.performance.HORIZONS", (5,))
    bench = {d: 100 + i for i, d in enumerate(DAYS)}  # 10-02 101 → 5거래일 뒤 10-12 106
    closes = {
        "A": {d: 50 * (1 + 0.02 * i) for i, d in enumerate(DAYS)},
        "B": {d: 10 for d in DAYS},
        "C": {"2026-10-02": 1},  # 청산일 종가가 없으면 뺀다
    }
    picks = [{"code": c, "name": c} for c in ("A", "B", "C")]
    s = score_run(picks, "2026-10-01", DAYS, bench, closes)  # 10-01 장 마감 뒤에 골랐다
    assert s["entry_date"] == "2026-10-02"
    h = s["horizons"][5]
    assert h["exit_date"] == "2026-10-12" and h["n"] == 2
    a_ret = (1.12 / 1.02 - 1) * 100
    assert h["ret"] == pytest.approx(round(a_ret / 2, 2))
    assert h["bench"] == pytest.approx(round((106 / 101 - 1) * 100, 2))
    assert h["hit"] == 50.0  # A만 지수보다 많이 올랐다


def test_score_waits_until_the_horizon_has_passed():
    bench = {d: 100 for d in DAYS}
    s = score_run([{"code": "A", "name": "A"}], "2026-10-13", DAYS, bench, {"A": bench})
    assert s["entry_date"] == "2026-10-14"
    assert s["horizons"][5] is None and s["so_far"]["exit_date"] == "2026-10-16"
    last = score_run([{"code": "A", "name": "A"}], "2026-10-16", DAYS, bench, {"A": bench})
    assert last["entry_date"] is None and last["so_far"] is None  # 다음 거래일 종가가 아직 없다


def test_summary_averages_only_matured_runs():
    runs = [
        {"horizons": {5: {"ret": 2, "excess": 1, "hit": 60}, 20: None, 60: None}},
        {"horizons": {5: {"ret": -1, "excess": -2, "hit": 20}, 20: None, 60: None}},
        {"horizons": {5: None, 20: None, 60: None}},
    ]
    s = summarize(runs)
    assert s[5] == {"runs": 2, "ret": 0.5, "excess": -0.5, "hit": 40.0, "beat_runs": 50.0}
    assert s[20] is None


def test_evaluate_reads_benchmark_and_picks_from_market_data():
    class Market:
        def bars(self, codes):
            self.codes = list(codes)
            return {c: [{"date": d, "close": 100 + i} for i, d in enumerate(DAYS)] for c in self.codes}

    m = Market()
    out = evaluate([{"run_date": "2026-10-01", "trigger": "manual", "picks": [{"code": "A", "name": "A"}]}], m)
    assert m.codes == ["069500", "A"]
    assert out["as_of"] == "2026-10-16" and out["runs"][0]["count"] == 1
    assert out["runs"][0]["horizons"][5]["excess"] == 0


# --- 기록 ---

def test_same_graph_ignores_positions_edge_ids_and_default_params():
    a = _graph([("s", "source", {"mode": "all"}), ("o", "result", {})], [("s", "o")], {"s": {"x": 0, "y": 0}})
    b = _graph([("o", "result", {"limit": 50}), ("s", "source", {})], [("s", "o")], {"s": {"x": 9, "y": 9}})
    assert same_graph(a, b)
    c = _graph([("s", "source", {}), ("o", "result", {"limit": 10})], [("s", "o")])
    assert not same_graph(a, c)


def test_pick_collector_merges_result_nodes_and_needs_all_of_them():
    graph = _graph([("s", "source", {}), ("o1", "result", {}), ("o2", "result", {})], [("s", "o1"), ("s", "o2")])

    def done(node_id, codes):
        return {"type": "node_done", "data": {"id": node_id, "dataset": {"rows": [{"code": c, "name": c.lower()} for c in codes]}}}

    c = PickCollector(graph)
    c.feed(done("s", ["X"]))
    c.feed(done("o1", ["A", "B"]))
    assert c.picks() is None  # o2가 끝나지 않았다
    c.feed(done("o2", ["B", "C"]))
    assert c.picks() == [{"code": "A", "name": "a"}, {"code": "B", "name": "b"}, {"code": "C", "name": "c"}]
    assert PickCollector(_graph([("s", "source", {})])).picks() is None


# --- 자동 실행 ---

def test_window_is_weekday_after_close():
    assert scheduler.in_window(datetime(2026, 10, 19, 16, 30))  # 월요일
    assert not scheduler.in_window(datetime(2026, 10, 19, 15, 0))
    assert not scheduler.in_window(datetime(2026, 10, 19, 20, 0))
    assert not scheduler.in_window(datetime(2026, 10, 18, 17, 0))  # 일요일


def test_change_message_lists_new_and_dropped_and_skips_no_change():
    day = date(2026, 10, 19)
    picks = [{"code": "A", "name": "가"}, {"code": "B", "name": "나"}]
    first = scheduler.change_message("흐름", "민", day, picks, None)
    assert "첫 기록" in first and "가, 나" in first
    assert scheduler.change_message("흐름", "민", day, picks, list(reversed(picks))) is None
    msg = scheduler.change_message("흐름", "민", day, picks, [{"code": "B", "name": "나"}, {"code": "C", "name": "다"}])
    assert "새로 들어옴 (1): 가" in msg and "빠짐 (1): 다" in msg and "유지 1종목" in msg


def test_change_message_shortens_long_lists():
    picks = [{"code": f"{i:06d}", "name": f"종목{i}"} for i in range(40)]
    msg = scheduler.change_message("흐름", "민", date(2026, 10, 19), picks, [])
    assert f"외 {40 - scheduler.LIST_NAMES}" in msg and len(msg) <= scheduler.DISCORD_MAX


def test_fresh_market_data_refetches_cache_older_than_the_batch(monkeypatch):
    calls = []
    md = YFinanceMarketData()
    monkeypatch.setattr(md, "_download", lambda tickers: calls.append(tickers) or {t: [{"date": "d", "close": 1}] for t in tickers})
    md.bars(["A"])
    md.bars(["A"])
    assert len(calls) == 1
    fresh = FreshMarketData(md, since=md._cache["A"][0] + 1)
    fresh.bars(["A"])
    assert len(calls) == 2


def test_has_bar_for_checks_the_benchmark_last_date():
    class Market:
        def bars(self, codes):
            return {"069500": [{"date": "2026-10-16"}]}

    assert scheduler.has_bar_for(Market(), date(2026, 10, 16))
    assert not scheduler.has_bar_for(Market(), date(2026, 10, 19))  # 아직 없거나 휴장일


# --- ETF 신호 노드 ---

class _DB:
    def close(self):
        pass


def _ctx():
    return FlowContext(user_id=1, session_factory=_DB, ai_config=None, market=None, stop=asyncio.Event())


def _run(params, source):
    async def go():
        return [e async for e in ETFSignalNode().run(params, [source], _ctx())]
    return asyncio.run(go())[-1]["items"]


@pytest.fixture
def signal_data(monkeypatch):
    monkeypatch.setattr(etf_signal, "held_by", lambda db, codes: {"A": [{}] * 6, "B": [{}] * 2, "C": [{}] * 9})
    monkeypatch.setattr(etf_signal, "recent_dates", lambda db, days: ["2026-10-12", "2026-10-08"][:days])
    captured = {}

    def buys(db, codes, dates, mode, min_change):
        captured.update(mode=mode, min_change=min_change, dates=dates)
        return {"A": {"etfs": ["가", "나"], "change": 3.456}, "B": {"etfs": ["가"], "change": 1.0}}

    monkeypatch.setattr(etf_signal, "active_buys", buys)
    return captured


def test_etf_signal_filters_by_holder_count_and_active_buys(signal_data):
    source = StockSet(rows={c: {"code": c, "name": c} for c in "ABC"})
    items = _run(ETFSignalParams(min_etfs=5, active="buy", min_active_etfs=2, days=2, min_change=1), source)
    assert list(items.rows) == ["A"]
    assert items.rows["A"]["etf_count"] == 6 and items.rows["A"]["active_etfs"] == 2 and items.rows["A"]["active_change"] == 3.46
    assert items.notes[-1].startswith("조건(ETF 신호)") and "2026-10-08~2026-10-12" in items.notes[-1]
    assert signal_data == {"mode": "buy", "min_change": 1, "dates": ["2026-10-12", "2026-10-08"]}


def test_etf_signal_with_conditions_off_only_adds_columns(signal_data):
    source = StockSet(rows={c: {"code": c, "name": c} for c in "ABC"})
    items = _run(ETFSignalParams(active="off"), source)
    assert list(items.rows) == ["A", "B", "C"]
    assert set(items.fields) == {"etf_count"} and "active_etfs" not in items.rows["A"]


def test_etf_signal_needs_weight_change_history(monkeypatch, signal_data):
    monkeypatch.setattr(etf_signal, "recent_dates", lambda db, days: [])
    with pytest.raises(ValueError, match="비중 변화 기록"):
        _run(ETFSignalParams(), StockSet(rows={"A": {"code": "A", "name": "A"}}))
