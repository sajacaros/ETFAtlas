import asyncio
import importlib.util
import json
import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.services.answer import orchestrator as orch, refs
from app.services.answer.planner import PlannedSlot, build_plan_model, examples_prompt, layout_tree, to_rows
from app.services.content import DataField, Dataset, LineView
from app.services.answer.skills import REGISTRY, holdings as holdings_mod
from app.services.answer.skills.base import Skill, data_result, empty, text_result
from app.services.answer.skills.etf_profile import percentile
from app.services.answer.skills.period_returns import period_return
from app.services.chat_memory import ConversationContext


# --- planner ---

def _plan(*rows):
    return build_plan_model(REGISTRY).model_validate({"rows": [{"slots": list(r)} for r in rows]})


def test_plan_rejects_display_the_skill_does_not_support():
    with pytest.raises(Exception, match="display"):
        _plan([{"skill": "holdings", "title": "구성", "display": "line", "args": {"etf": "KODEX 200"}}])


def test_plan_requires_display():
    with pytest.raises(Exception, match="display"):
        _plan([{"skill": "holdings", "title": "구성", "args": {"etf": "KODEX 200"}}])


def test_layout_tree_assigns_ids_and_wraps_multi_slot_rows():
    rows = to_rows(_plan(
        [
            {"skill": "price_trend", "title": "추이", "display": "line", "args": {"etfs": ["KODEX 200"]}},
            {"skill": "holdings", "title": "구성", "display": "donut", "args": {"etf": "KODEX 200"}},
        ],
        [{"skill": "narrative", "title": "해설", "display": "text", "args": {"instruction": "요약"}}],
    ))
    assert layout_tree(rows) == {"type": "column", "children": [
        {"type": "row", "children": [
            {"type": "slot", "id": "s1", "slot": "chart", "display": "line", "title": "추이"},
            {"type": "slot", "id": "s2", "slot": "chart", "display": "donut", "title": "구성"},
        ]},
        {"type": "slot", "id": "s3", "slot": "text", "display": "text", "title": "해설"},
    ]}


def test_to_rows_caps_total_slots():
    slot = {"skill": "narrative", "title": "t", "display": "text", "args": {"instruction": "x"}}
    rows = to_rows(_plan(*[[slot, slot, slot]] * 4))
    assert sum(len(r) for r in rows) == 8


# --- schemas / data helpers ---

def test_data_result_fails_when_view_points_to_unknown_field():
    dataset = Dataset(fields=[DataField(key="date", label="날짜", format="date")], rows=[])
    result = data_result(dataset, LineView(x="date", y=["069500"]), "요약")
    assert result.status == "failed"
    assert result.content is None


def test_percentile_is_against_whole_universe_and_respects_direction():
    population = [0.05, 0.15, 0.3, 0.5]
    assert percentile(0.05, population, "low") == 88  # 가장 싸다
    assert percentile(0.05, population, "high") == 12
    assert percentile(None, population, "low") is None


def test_period_return_needs_data_old_enough():
    prices = [{"date": "2026-10-01", "close": 100.0}, {"date": "2026-10-08", "close": 110.0}]
    assert period_return(prices, "1w") == 10.0
    assert period_return(prices, "7d") == 10.0
    assert period_return(prices, "1m") is None


def test_period_accepts_any_asked_period_and_labels_it():
    from datetime import date
    from app.domain.periods import period_label, period_start
    Args = REGISTRY["price_trend"].Args
    assert Args(etfs=["가"]).period == "1m"  # 질문에 기간이 없으면 기본값
    assert [Args(etfs=["가"], period=p).period for p in ("2w", "45d", "2M", "ytd")] == ["2w", "45d", "2m", "ytd"]
    for bad in ("2주", "0d", "1q", "3"):
        with pytest.raises(ValueError, match="기간 표기"):
            Args(etfs=["가"], period=bad)
    assert [period_label(p) for p in ("2w", "45d", "2m", "1y", "ytd")] == ["2주", "45일", "2개월", "1년", "연초 이후"]
    assert period_start("2w", date(2026, 10, 23)) == date(2026, 10, 9)
    assert period_start("ytd", date(2026, 10, 23)) == date(2025, 12, 31)  # 작년 마지막 거래일 대비


class FakeResolver:
    def etf(self, db, name):
        return {"code": "069500", "name": "KODEX 200"}


def test_holdings_donut_groups_the_rest_as_others(monkeypatch):
    weights = [30.0, 20.0, 10.0, 5.0, 5.0, 4.0, 3.0, 2.0, 1.0]
    monkeypatch.setattr(holdings_mod, "node", lambda graph, cypher, params: [
        {"code": f"{i:06d}", "name": f"종목{i}", "weight": w, "date": "2026-10-07"} for i, w in enumerate(weights)
    ])
    skill = REGISTRY["holdings"]
    result = skill.fetch(skill.Args(etf="KODEX 200", top=20), "donut", None, FakeResolver())
    rows = result.content["dataset"]["rows"]
    assert len(rows) == holdings_mod.DONUT_MAX_SLICES
    assert rows[-1] == {"name": "기타", "code": None, "weight": 23.0}  # 100 - 상위 7개 합계
    assert result.content["view"] == {"kind": "donut", "name": "name", "value": "weight"}


# --- orchestrator ---

class NoArgs(BaseModel):
    pass


class DataSkillStub(Skill):
    name = "data"
    description = "데이터"
    Args = NoArgs
    displays = ("table",)

    def __init__(self, summary="A요약"):
        self.summary = summary

    async def run(self, args, display, ctx):
        await asyncio.sleep(0)
        yield text_result(self.summary).event() | {"summary": self.summary}


class BrokenSkill(Skill):
    name = "broken"
    description = "항상 실패"
    Args = NoArgs
    displays = ("table",)

    async def run(self, args, display, ctx):
        raise RuntimeError("boom")
        yield  # pragma: no cover


class EchoNarrative(Skill):
    name = "narr"
    description = "앞 슬롯 요약을 그대로"
    Args = NoArgs
    displays = ("text",)
    after_others = True

    async def run(self, args, display, ctx):
        text = " | ".join(f"{t}:{s}" for t, s in ctx.related)
        for part in (text[:3], text[3:]):
            yield {"type": "delta", "text": part}
        yield text_result(text).event()


class FakePlanner:
    def __init__(self, rows):
        self.rows = rows

    async def plan(self, question, context):
        return self.rows


class FakeMemory:
    def __init__(self, db):
        pass

    def refine(self, message, context):
        return message


class MemoryStore:
    def __init__(self):
        self.saved = {}

    def create(self, chat_log_id, slots):
        self.saved.update({s.id: "pending" for s in slots})

    def replace(self, chat_log_id, slots):
        self.saved.update({s.id: "pending" for s in slots})

    def split(self, chat_log_id, slot_id, parts):
        self.saved.update({s.id: "pending" for s in parts})

    def save(self, chat_log_id, slot_id, result):
        self.saved[slot_id] = result["status"]


def _service(monkeypatch, rows, registry):
    monkeypatch.setattr(orch, "ChatMemory", FakeMemory)
    monkeypatch.setattr(orch, "load_ai_config", lambda db: None)
    service = orch.AnswerService(None, session_factory=lambda: None, registry=registry, planner=FakePlanner(rows))
    service._store = MemoryStore()
    return service


def _collect(service, stop=None):
    async def run():
        return [e async for e in service.stream("질문", ConversationContext(), 7, stop or asyncio.Event())]
    return asyncio.run(run())


def _slot(id, skill, title=""):
    return PlannedSlot(id=id, skill=skill, title=title, display="table", args=NoArgs())


REG = {"data": DataSkillStub(), "broken": BrokenSkill(), "narr": EchoNarrative()}


def test_stream_sends_layout_first_then_fills_slots(monkeypatch):
    rows = [[_slot("s1", "data", "가"), _slot("s2", "broken", "나")], [_slot("s3", "narr", "해설")]]
    service = _service(monkeypatch, rows, REG)
    events = _collect(service)

    kinds = [e["type"] for e in events]
    assert kinds.index("layout") < kinds.index("slot")
    assert events[kinds.index("layout")]["data"]["chat_log_id"] == 7

    final = {e["data"]["id"]: e["data"]["status"] for e in events
             if e["type"] == "slot" and e["data"]["status"] != "running"}
    assert final == {"s1": "complete", "s2": "failed", "s3": "complete"}
    assert service._store.saved == final

    # 해설은 앞 슬롯이 모두 끝난 뒤, 그 요약(실패 문구 포함)을 받아 흘려보낸다
    deltas = "".join(e["data"]["text"] for e in events if e["type"] == "slot_delta")
    assert deltas == "가:A요약 | 나:이 영역을 채우지 못했습니다"
    assert kinds.index("slot_delta") > max(
        i for i, e in enumerate(events) if e["type"] == "slot" and e["data"]["id"] in ("s1", "s2")
    )
    assert events[-1]["type"] == "answer"
    assert "### 가\nA요약" in events[-1]["data"]["answer"]
    assert events[-1]["data"]["result"] == "completed"  # 일부 영역만 실패하면 완료로 본다


class SlowLLMSkill(DataSkillStub):
    """동시에 몇 개가 돌았는지 센다."""
    uses_llm = True
    running = peak = 0

    async def run(self, args, display, ctx):
        SlowLLMSkill.running += 1
        SlowLLMSkill.peak = max(SlowLLMSkill.peak, SlowLLMSkill.running)
        await asyncio.sleep(0.01)
        SlowLLMSkill.running -= 1
        async for e in super().run(args, display, ctx):
            yield e


def test_llm_slots_wait_for_a_free_seat(monkeypatch):
    monkeypatch.setattr(orch, "MAX_LLM_SLOTS", 2)
    SlowLLMSkill.running = SlowLLMSkill.peak = 0
    rows = [[_slot(f"s{i}", "llm") for i in range(1, 4)], [_slot("s4", "llm"), _slot("s5", "data")]]
    events = _collect(_service(monkeypatch, rows, {**REG, "llm": SlowLLMSkill()}))
    final = {e["data"]["id"]: e["data"]["status"] for e in events if e["type"] == "slot" and e["data"]["status"] != "running"}
    assert final == {f"s{i}": "complete" for i in range(1, 6)}
    assert SlowLLMSkill.peak == 2


class TitledSkill(DataSkillStub):
    async def run(self, args, display, ctx):
        yield {"type": "title", "title": "삼성전자 2026년 반기보고서 요약"}
        async for e in super().run(args, display, ctx):
            yield e


def test_skill_can_retitle_its_slot_and_the_layout_is_sent_again(monkeypatch):
    rows = [[_slot("s1", "titled", "삼성전자 보고서 요약")], [_slot("s2", "narr", "해설")]]
    service = _service(monkeypatch, rows, {**REG, "titled": TitledSkill()})
    events = _collect(service)

    layouts = [e["data"]["layout"] for e in events if e["type"] == "layout"]
    assert [l["children"][0]["title"] for l in layouts] == ["삼성전자 보고서 요약", "삼성전자 2026년 반기보고서 요약"]
    assert not any(e["type"] == "slot_title" for e in events)  # 화면에는 레이아웃으로만 알린다
    # 해설과 답변 텍스트도 바뀐 제목을 쓴다
    assert "### 삼성전자 2026년 반기보고서 요약\nA요약" in events[-1]["data"]["answer"]
    assert "삼성전자 2026년 반기보고서 요약:A요약" in "".join(e["data"]["text"] for e in events if e["type"] == "slot_delta")


class SplittingSkill(DataSkillStub):
    """결과를 보고 차트 영역과 설명 영역으로 나눈다."""
    async def run(self, args, display, ctx):
        yield {"type": "split", "parts": [{"id": "chart", "title": "매출 구성", "display": "donut"},
                                          {"id": "text", "title": "보고서 요약", "display": "markdown"}]}
        async for e in super().run(args, display, ctx):
            yield {**e, "part": "chart"}
        yield {"type": "delta", "text": "요약 본문", "part": "text"}
        yield {**text_result("요약 본문", kind="markdown").event(), "part": "text"}


def test_skill_can_split_its_slot_into_a_chart_and_a_text(monkeypatch):
    rows = [[_slot("s1", "data", "가"), _slot("s2", "split", "보고서")], [_slot("s3", "narr", "해설")]]
    service = _service(monkeypatch, rows, {**REG, "split": SplittingSkill()})
    events = _collect(service)

    last = [e["data"]["layout"] for e in events if e["type"] == "layout"][-1]
    # 나눈 자리에 차트, 그 아래 설명 — 원래 줄 배치는 그대로
    assert last["children"][0]["children"][1] == {"type": "column", "children": [
        {"type": "slot", "id": "s2-1", "slot": "chart", "display": "donut", "title": "매출 구성"},
        {"type": "slot", "id": "s2-2", "slot": "markdown", "display": "markdown", "title": "보고서 요약"},
    ]}
    shown = {e["data"]["id"]: e["data"]["status"] for e in events if e["type"] == "slot" and e["data"]["status"] != "running"}
    assert shown == {"s1": "complete", "s2-1": "complete", "s2-2": "complete", "s3": "complete"}  # 원래 영역은 화면에 없다
    assert service._store.saved["s2"] == "complete"  # 원래 슬롯에는 나눈 영역들을 합친 결과
    assert {"id": "s2-2", "text": "요약 본문"} in [e["data"] for e in events if e["type"] == "slot_delta"]
    # 해설과 답변 텍스트는 나눈 영역을 각각 받는다
    narration = "".join(e["data"]["text"] for e in events if e["type"] == "slot_delta" and e["data"]["id"] == "s3")
    assert narration == "가:A요약 | 매출 구성:A요약 | 보고서 요약:요약 본문"
    answer = events[-1]["data"]["answer"]
    assert "### 매출 구성\nA요약" in answer and "### 보고서 요약\n요약 본문" in answer


class HalfSplit(Skill):
    """나눈 뒤 차트 하나만 내고 실패한다."""
    name = "half"
    description = "차트만 내고 끝난다"
    Args = NoArgs
    displays = ("markdown",)

    async def run(self, args, display, ctx):
        yield {"type": "split", "parts": [{"id": "a", "title": "A", "display": "table"},
                                          {"id": "b", "title": "B", "display": "markdown"}]}
        async for e in DataSkillStub().run(args, display, ctx):
            yield {**e, "part": "a"}
        raise RuntimeError("boom")


def test_split_parts_without_a_result_are_closed(monkeypatch):
    service = _service(monkeypatch, [[_slot("s1", "half", "보고서")]], {**REG, "half": HalfSplit()})
    _collect(service)
    assert service._store.saved == {"s1": "complete", "s1-1": "complete", "s1-2": "failed"}


def test_layout_tree_puts_split_charts_side_by_side_above_the_text():
    rows = [[_slot("s1", "data", "보고서")]]
    parts = [PlannedSlot(id=f"s1-{i}", skill="data", title=t, display=d, args=NoArgs())
             for i, (t, d) in enumerate([("가", "donut"), ("나", "bar"), ("요약", "markdown")], 1)]
    tree = layout_tree(rows, {"s1": parts})
    node = tree["children"][0]
    assert node["type"] == "column"
    assert [c["id"] for c in node["children"][0]["children"]] == ["s1-1", "s1-2"]
    assert node["children"][1]["id"] == "s1-3"


def test_stop_skips_slots_that_wait_for_others(monkeypatch):
    stop = asyncio.Event()

    class StoppingData(DataSkillStub):
        async def run(self, args, display, ctx):
            ctx.stop.set()
            async for e in super().run(args, display, ctx):
                yield e

    registry = {**REG, "data": StoppingData()}
    service = _service(monkeypatch, [[_slot("s1", "data")], [_slot("s2", "narr")]], registry)
    events = _collect(service, stop)
    assert service._store.saved == {"s1": "complete", "s2": "stopped"}
    assert not any(e["type"] == "slot_delta" for e in events)
    assert events[-1]["data"]["result"] == "cancelled"


def test_stop_before_planning_is_cancelled(monkeypatch):
    stop = asyncio.Event()
    stop.set()
    service = _service(monkeypatch, [[_slot("s1", "data")]], REG)
    events = _collect(service, stop)
    assert events[-1]["data"] == {"answer": orch.STOPPED_ANSWER, "result": "cancelled"}


def test_answer_fails_only_when_every_slot_fails(monkeypatch):
    service = _service(monkeypatch, [[_slot("s1", "broken"), _slot("s2", "broken")]], REG)
    assert _collect(service)[-1]["data"]["result"] == "failed"


def test_answer_that_asks_back_is_clarifying(monkeypatch):
    class AskingData(DataSkillStub):
        async def run(self, args, display, ctx):
            yield text_result("어느 쪽인가요?").event() | {"clarify": True}

    registry = {**REG, "data": AskingData()}
    service = _service(monkeypatch, [[_slot("s1", "data")]], registry)
    assert _collect(service)[-1]["data"]["result"] == "clarifying"


# --- 종목 스킬 / 해석기 ---

def test_resolver_strips_characters_that_could_break_the_query():
    from app.services.entities import _normalize
    assert _normalize("KODEX 미국S&P500(H)") == "kodex미국s&p500(h)"
    assert _normalize("x' OR 1=1 $$ ;\\") == "xor11"


class FakeStockResolver:
    STOCKS = {"삼성전자": {"code": "005930", "name": "삼성전자"},
              "테스": {"code": "095610", "name": "테스"}, "원익IPS": {"code": "240810", "name": "원익IPS"}}

    def stocks(self, db, names):
        found = [self.STOCKS[n] for n in names if n in self.STOCKS]
        return found, [n for n in names if n not in self.STOCKS]


def test_stock_holders_ranks_etfs_by_weight(monkeypatch):
    from app.services.answer.skills import stock_holders as mod
    calls = []

    def fake_node(graph, cypher, params):
        calls.append(cypher)
        return [{"code": "448100", "name": "WON 200", "stock": "005930", "weight": 35.21, "expense_ratio": 0.05,
                 "date": "2026-10-07"}]

    monkeypatch.setattr(mod, "node", fake_node)
    skill = REGISTRY["stock_holders"]
    result = skill.fetch(skill.Args(stocks=["삼성전자"], top=5), "bar", None, FakeStockResolver())
    assert "IN ['005930']" in calls[0]
    assert result.content["view"] == {"kind": "bar", "x": "name", "y": ["w_005930"], "horizontal": True, "stacked": False}
    assert "WON 200 35.21%" in result.summary


def test_stock_holders_ranks_etfs_by_combined_weight(monkeypatch):
    from app.services.answer.skills import stock_holders as mod
    monkeypatch.setattr(mod, "node", lambda graph, cypher, params: [
        {"code": "A", "name": "한 종목만", "stock": "095610", "weight": 6.0, "expense_ratio": 0.4, "date": "2026-10-07"},
        {"code": "B", "name": "둘 다", "stock": "095610", "weight": 4.0, "expense_ratio": 0.3, "date": "2026-10-07"},
        {"code": "B", "name": "둘 다", "stock": "240810", "weight": 3.5, "expense_ratio": 0.3, "date": "2026-10-07"},
    ])
    skill = REGISTRY["stock_holders"]
    result = skill.fetch(skill.Args(stocks=["테스", "원익IPS"]), "bar", None, FakeStockResolver())
    assert result.exports == [{"code": "B", "name": "둘 다"}, {"code": "A", "name": "한 종목만"}]
    view = result.content["view"]
    assert (view["y"], view["stacked"]) == (["w_095610", "w_240810"], True)
    rows = result.content["dataset"]["rows"]
    assert (rows[0]["total"], rows[1]["w_240810"]) == (7.5, None)
    assert "둘 다 합계 7.50%(테스 4.00%, 원익IPS 3.50%" in result.summary


# --- 포트폴리오 합산 ---

class FakePortfolioResolver:
    ETFS = {"KODEX 200": {"code": "069500", "name": "KODEX 200"}, "KODEX 반도체": {"code": "091160", "name": "KODEX 반도체"}}
    UNMANAGED = {"360750": {"code": "360750", "name": "TIGER 미국S&P500"}}  # 상장 ETF지만 그래프에 없다
    STOCKS = {"삼성전자": {"code": "005930", "name": "삼성전자"}}

    def etf(self, db, name):
        from app.services.entities import UnmanagedETF
        if name in self.UNMANAGED:
            raise UnmanagedETF(self.UNMANAGED[name])
        return self.ETFS.get(name)

    def stock(self, db, name):
        return self.STOCKS.get(name)


@pytest.fixture
def lookthrough(monkeypatch):
    from app.services.answer.skills import portfolio_lookthrough as mod
    queries = []

    def fake_node(graph, cypher, params):
        queries.append(cypher)
        return [
            {"etf": "069500", "stock_code": "005930", "stock_name": "삼성전자", "weight": 30.0, "date": "2026-10-07"},
            {"etf": "069500", "stock_code": "000660", "stock_name": "SK하이닉스", "weight": 20.0, "date": "2026-10-07"},
            {"etf": "091160", "stock_code": "005930", "stock_name": "삼성전자", "weight": 25.0, "date": "2026-10-06"},
            {"etf": "091160", "stock_code": "000660", "stock_name": "SK하이닉스", "weight": 25.0, "date": "2026-10-06"},
            {"etf": "091160", "stock_code": "042700", "stock_name": "한미반도체", "weight": 50.0, "date": "2026-10-06"},
        ]

    monkeypatch.setattr(mod, "node", fake_node)
    skill = REGISTRY["portfolio_lookthrough"]

    def run(items, display="table", top=15):
        args = skill.Args(items=[{"asset": a, "allocation": w} for a, w in items], top=top)
        return skill.fetch(args, display, None, FakePortfolioResolver())

    run.queries = queries
    return run


def test_lookthrough_sums_etf_holdings_and_direct_stocks(lookthrough):
    result = lookthrough([("KODEX 200", 40), ("360750", 30), ("KODEX 반도체", 20), ("삼성전자", 10)])
    rows = {r["name"]: r for r in result.content["dataset"]["rows"]}

    assert len(lookthrough.queries) == 1  # ETF가 여러 개여도 구성종목 조회는 한 번
    # 40×30% + 20×25% + 직접 10
    assert rows["삼성전자"]["weight"] == 27.0
    assert rows["삼성전자"]["via"] == "KODEX 200 12.00 · 직접 10.00 · KODEX 반도체 5.00"
    assert rows["SK하이닉스"]["weight"] == 13.0
    assert rows["TIGER 미국S&P500 (구성 미확인)"] == {
        "name": "TIGER 미국S&P500 (구성 미확인)", "code": None, "weight": 30.0, "via": "구성 미확인 30.00"}
    # KODEX 200의 나머지 50%(30위 밖·현금) × 40%
    assert rows["기타"]["weight"] == 20.0
    assert sum(r["weight"] for r in rows.values()) == pytest.approx(100)
    assert any("TIGER 미국S&P500(360750)" in n for n in result.content["notes"])
    assert not any(n.startswith("이름으로 찾은 항목") for n in result.content["notes"])  # 이름·코드가 그대로 맞았다
    assert "삼성전자 27.00%" in result.summary


def test_lookthrough_normalizes_weights_and_reports_missing(lookthrough):
    result = lookthrough([("KODEX 반도체", 15), ("삼성전자", 5), ("없는ETF", 10)])
    rows = {r["name"]: r["weight"] for r in result.content["dataset"]["rows"]}

    # 찾은 항목만 100%로 환산: 반도체 75%, 삼성전자 25%
    assert rows["삼성전자"] == pytest.approx(75 * 0.25 + 25)
    assert "기타" not in rows
    notes = result.content["notes"]
    assert "찾지 못해 계산에서 뺀 항목: 없는ETF" in notes
    assert "입력 비중 합계 20.00%를 100%로 맞춰 계산했습니다" in notes


def test_lookthrough_donut_folds_the_tail_into_others(lookthrough, monkeypatch):
    from app.services.answer.skills import portfolio_lookthrough as mod
    monkeypatch.setattr(mod, "node", lambda graph, cypher, params: [
        {"etf": "091160", "stock_code": f"{i:06d}", "stock_name": f"종목{i}", "weight": 10.0, "date": "2026-10-06"}
        for i in range(10)
    ])
    rows = lookthrough([("KODEX 반도체", 100)], display="donut").content["dataset"]["rows"]
    assert len(rows) == mod.DONUT_MAX_SLICES
    assert rows[-1]["name"] == "기타" and rows[-1]["weight"] == 30.0


def test_lookthrough_notes_names_resolved_to_a_different_etf(lookthrough, monkeypatch):
    # 'K반도체TOP2+'처럼 접두어가 빠진 이름은 다른 운용사 ETF로 잡힐 수 있어 사용자에게 보여준다
    monkeypatch.setitem(FakePortfolioResolver.ETFS, "반도체", {"code": "091160", "name": "KODEX 반도체"})
    notes = lookthrough([("반도체", 100)]).content["notes"]
    assert "이름으로 찾은 항목: 반도체 → KODEX 반도체(091160)" in notes


def test_lookthrough_is_empty_when_nothing_resolves(lookthrough):
    result = lookthrough([("없는ETF", 100)])
    assert result.status == "empty"


# --- 대상을 정하지 못할 때 되묻기 ---

@pytest.fixture
def fake_etf_graph(monkeypatch):
    """resolver가 ETF 이름 후보를 찾을 때 쓰는 그래프. 순자산 큰 순으로 돌려준다."""
    import json
    from app.services import graph_service
    from app.services import entities as resolver_mod
    etfs = [
        {"code": "396500", "name": "TIGER 반도체TOP10", "net_assets": 9_5642_0000_0000},
        {"code": "091160", "name": "KODEX 반도체", "net_assets": 2_0000_0000_0000},
        {"code": "0210A0", "name": "ACE K반도체TOP2+", "net_assets": 5000_0000_0000},
        {"code": "0182R0", "name": "1Q K반도체TOP2+", "net_assets": 1000_0000_0000},
    ]
    calls = []

    class FakeGraph:
        parse_agtype = staticmethod(graph_service.GraphService.parse_agtype)

        def __init__(self, db):
            pass

        def execute_cypher(self, cypher, params, raise_errors=False):
            calls.append(params)
            if "code" in params:
                return [{"result": json.dumps(e)} for e in etfs if e["code"] == params["code"]]
            return [{"result": json.dumps(e)} for e in etfs
                    if params["query"] in e["name"].replace(" ", "").lower()]

    monkeypatch.setattr(resolver_mod, "GraphService", FakeGraph)
    # 상장 ETF 목록(RDB)에만 있는 ETF — 관리하지 않는다
    unmanaged = {"122630": {"code": "122630", "name": "KODEX 레버리지"}}
    monkeypatch.setattr(resolver_mod, "_unmanaged_etf", lambda db, code, query: unmanaged.get(code) or next(
        (e for e in unmanaged.values() if e["name"].replace(" ", "").lower() == query), None))
    monkeypatch.setattr(resolver_mod, "_dart_corp", lambda db, code, query: None)  # DART 고유번호 목록은 비어 있다
    return calls


def test_resolver_asks_instead_of_guessing_between_etfs(fake_etf_graph):
    from app.services.entities import AmbiguousETF, EntityResolver
    r = EntityResolver()
    with pytest.raises(AmbiguousETF) as exc:
        r.etf(None, "K반도체TOP2+")
    assert [c["code"] for c in exc.value.candidates] == ["0210A0", "0182R0"]
    # 정확히 같은 이름이나 후보 하나, 코드는 그대로 정한다
    assert r.etf(None, "1Q K반도체TOP2+") == {"code": "0182R0", "name": "1Q K반도체TOP2+"}
    assert r.etf(None, "TOP10") == {"code": "396500", "name": "TIGER 반도체TOP10"}
    assert r.etf(None, "091160")["name"] == "KODEX 반도체"
    # 애매하다는 판단도 캐시해 같은 답변의 다른 슬롯은 다시 조회하지 않는다
    calls = len(fake_etf_graph)
    with pytest.raises(AmbiguousETF):
        r.etf(None, "K반도체TOP2+")
    assert len(fake_etf_graph) == calls


def test_resolver_tells_unmanaged_etfs_apart_from_unknown_names(fake_etf_graph):
    from app.services.entities import EntityResolver, UnmanagedETF
    r = EntityResolver()
    for name in ("kodex 레버리지", "122630"):
        with pytest.raises(UnmanagedETF) as exc:
            r.etf(None, name)
        assert exc.value.etf == {"code": "122630", "name": "KODEX 레버리지"}
    assert r.etf(None, "없는ETF") is None
    found, missing = r.etfs(None, ["091160", "KODEX 레버리지", "없는ETF"])
    assert [e["code"] for e in found] == ["091160"]
    assert missing == ["KODEX 레버리지(관리하지 않는 ETF)", "없는ETF"]
    with pytest.raises(UnmanagedETF):  # 하나만 물었으면 단일 ETF와 같은 안내
        r.etfs(None, ["KODEX 레버리지"])


def test_data_skill_says_an_etf_is_not_managed(fake_etf_graph):
    from app.services.entities import EntityResolver
    from app.services.answer.skills.base import SkillContext

    async def run():
        ctx = SkillContext(question="q", conversation=ConversationContext(), session_factory=lambda: _Closable(),
                           resolver=EntityResolver(), ai_config=None, stop=asyncio.Event())
        skill = REGISTRY["holdings"]
        return [e async for e in skill.run(skill.Args(etf="KODEX 레버리지"), "treemap", ctx)]

    result = asyncio.run(run())[-1]
    assert result["status"] == "empty"
    assert result["message"].startswith("ETF Atlas에서 관리하지 않는 ETF입니다: KODEX 레버리지(122630)")


def test_data_skill_turns_an_ambiguous_etf_into_a_question(fake_etf_graph):
    from app.services.entities import EntityResolver
    from app.services.answer.skills.base import SkillContext

    async def run():
        ctx = SkillContext(question="q", conversation=ConversationContext(), session_factory=lambda: _Closable(),
                           resolver=EntityResolver(), ai_config=None, stop=asyncio.Event())
        skill = REGISTRY["holdings"]
        return [e async for e in skill.run(skill.Args(etf="반도체"), "treemap", ctx)]

    result = asyncio.run(run())[-1]
    assert result["clarify"] is True
    assert result["content"]["type"] == "markdown"
    text = result["summary"]
    assert "'반도체'에 해당하는 ETF가 여러 개입니다" in text
    # 번호를 붙여 다음 턴의 "두 번째 거"를 풀 수 있게 한다
    assert "| 1 | TIGER 반도체TOP10 | 396500 | 9조 5,642억원 |" in text
    assert "| 4 | 1Q K반도체TOP2+ | 0182R0 |" in text


class _Closable:
    def close(self):
        pass


def test_stream_waits_for_the_answer_instead_of_narrating(monkeypatch):
    from app.services.answer.skills.base import choice_result

    class Asking(DataSkillStub):
        async def run(self, args, display, ctx):
            yield choice_result("어느 ETF인가요?", ["ETF"], [["A"], ["B"]]).event()

    service = _service(monkeypatch, [[_slot("s1", "ask")], [_slot("s2", "narr", "해설")]], {**REG, "ask": Asking()})
    events = _collect(service)
    assert service._store.saved == {"s1": "complete", "s2": "empty"}
    assert not any(e["type"] == "slot_delta" for e in events)
    assert "| 2 | B |" in events[-1]["data"]["answer"]


def test_object_particle_follows_the_last_syllable():
    from app.services.answer.skills.common import object_particle
    assert [object_particle(w) for w in ("구성종목", "수익률 추이", "가격", "원익IPS")] == ["을", "를", "을", "을(를)"]


def test_etf_choice_lists_holders_and_asks(monkeypatch):
    from app.services.answer.skills import etf_choice as mod
    monkeypatch.setattr(mod, "node", lambda graph, cypher, params: [
        {"code": f"{i:06d}", "name": f"ETF{i}", "weight": 20.0 - i} for i in range(12)
    ])

    class Resolver:
        def stock(self, db, name):
            return {"code": "240810", "name": "원익IPS"}

    skill = REGISTRY["etf_choice"]
    result = skill.fetch(skill.Args(by="stock", condition="원익IPS", purpose="구성종목"), "markdown", None, Resolver())
    assert result.clarify
    assert "원익IPS을(를) 담은 ETF가 12개입니다. 어느 ETF의 구성종목을 볼까요?" in result.summary
    assert "| 1 | ETF0 | 000000 | 20.00% |" in result.summary
    assert "| 11 |" not in result.summary  # 상위 10개만
    assert "비중 상위 10개입니다" in result.summary


def test_etf_choice_by_theme_prefers_the_tag_then_names(monkeypatch):
    from app.services.answer.skills import etf_choice as mod
    queries = []

    def fake_node(graph, cypher, params):
        queries.append((cypher.split()[1], params))
        if "Tag" in cypher:
            return [] if params["query"] == "ai" else [{"code": "396500", "name": "TIGER 반도체TOP10", "net_assets": 9_5642_0000_0000}]
        return [{"code": "0093A0", "name": "RISE AI반도체TOP10", "net_assets": 1000_0000_0000}]

    monkeypatch.setattr(mod, "node", fake_node)
    skill = REGISTRY["etf_choice"]
    result = skill.fetch(skill.Args(by="theme", condition="반도체 ETF", purpose="구성종목"), "markdown", None, None)
    assert queries[0][1] == {"query": "반도체"}  # 'ETF'는 떼고 찾는다
    assert "'반도체' ETF가 1개입니다." in result.summary
    assert "| 1 | TIGER 반도체TOP10 | 396500 | 9조 5,642억원 |" in result.summary
    # 태그가 없으면 이름에 든 단어로
    result = skill.fetch(skill.Args(by="theme", condition="AI", purpose="수익률 추이"), "markdown", None, None)
    assert "'AI' ETF가 1개입니다. 어느 ETF의 수익률 추이를 볼까요?" in result.summary


def test_etf_choice_requires_the_kind_of_condition():
    # 둘 중 하나를 고르는 제약을 스키마로 드러내 플래너가 빈 인자를 내지 않게 한다
    with pytest.raises(Exception):
        REGISTRY["etf_choice"].Args(condition="반도체", purpose="구성종목")
    assert REGISTRY["etf_choice"].Args.model_json_schema()["required"] == ["by", "condition", "purpose"]


def test_lookthrough_asks_about_an_ambiguous_etf_but_takes_an_exact_stock(lookthrough, monkeypatch):
    from app.services.entities import AmbiguousETF
    from app.services.answer.skills import portfolio_lookthrough as mod

    def ambiguous_etf(self, db, name):
        if name in ("반도체", "삼성전자"):
            raise AmbiguousETF(name, [{"code": "091160", "name": "KODEX 반도체"}])
        return FakePortfolioResolver.ETFS.get(name)

    monkeypatch.setattr(FakePortfolioResolver, "etf", ambiguous_etf)
    # 'KODEX 삼성전자…'처럼 이름에 종목명이 든 ETF가 여럿이어도 같은 이름의 종목이면 종목이다
    rows = {r["name"]: r["weight"] for r in lookthrough([("삼성전자", 100)]).content["dataset"]["rows"]}
    assert rows == {"삼성전자": 100}
    with pytest.raises(AmbiguousETF):
        lookthrough([("반도체", 50), ("삼성전자", 50)])


# --- 슬롯 간 참조 ---

def test_refs_resolve_ranks_and_expand_ranges_in_lists():
    from app.services.answer import refs
    exports = {"rank": [{"code": "448100", "name": "WON 200"}, {"code": "069500", "name": "KODEX 200"},
                        {"code": "102110", "name": "TIGER 200"}]}
    args = {"etf": "@rank.1", "etfs": ["@rank.2-3", "KODEX 반도체"], "top": 10, "note": "rank.1"}
    assert refs.refs_in(args) == {"rank"}
    assert refs.resolve(args, exports) == {
        "etf": "448100", "etfs": ["069500", "102110", "KODEX 반도체"], "top": 10, "note": "rank.1"}
    assert refs.describe({"etf": "@rank.1"}, exports, {"rank": "삼성전자 비중 순위"}) == [
        "'삼성전자 비중 순위' 1위: WON 200(448100)"]
    with pytest.raises(refs.RefError, match="하나만"):
        refs.resolve({"etf": "@rank.1-2"}, exports)
    with pytest.raises(refs.RefError, match="3개뿐"):
        refs.resolve({"etf": "@rank.4"}, exports)
    # 범위가 결과를 넘으면 있는 만큼만, 통째로 넘으면 다시 설계할 일이 아닌 오류
    assert refs.resolve({"etfs": ["@rank.2-5"]}, exports) == {"etfs": ["069500", "102110"]}
    with pytest.raises(refs.RefPastEnd, match="3개뿐"):
        refs.resolve({"etfs": ["@rank.4-5"]}, exports)
    assert not issubclass(refs.RefError, refs.RefPastEnd)


def _plan_steps(*slots):
    return build_plan_model(REGISTRY).model_validate({"rows": [{"slots": list(slots)}]})


RANK = {"skill": "stock_holders", "name": "rank", "title": "순위", "display": "bar", "args": {"stocks": ["삼성전자"]}}


def test_plan_turns_references_into_dependencies():
    rows = to_rows(_plan_steps(RANK, {"skill": "holdings", "title": "구성", "display": "table",
                                      "args": {"etf": "@rank.1"}}))
    rank, holdings = rows[0]
    assert (rank.name, rank.depends_on) == ("rank", [])
    assert holdings.depends_on == ["s1"]


@pytest.mark.parametrize("slots, error", [
    ([{"skill": "holdings", "title": "구성", "display": "table", "args": {"etf": "@nope.1"}}], "name이 'nope'인 슬롯이 없습니다"),
    ([{**RANK, "skill": "etf_compare", "display": "table", "args": {"etfs": ["A", "B"]}},
      {"skill": "holdings", "title": "구성", "display": "table", "args": {"etf": "@rank.1"}}], "내보내지 않습니다"),
    ([{"skill": "holdings", "name": "a", "title": "가", "display": "table", "args": {"etf": "@b.1"}},
      {"skill": "holdings", "name": "b", "title": "나", "display": "table", "args": {"etf": "@a.1"}}], "순환"),
    # 펼치면 인자 개수 제한(최대 5개)을 넘는다
    ([RANK, {"skill": "period_returns", "title": "수익률", "display": "bar", "args": {"etfs": ["@rank.1-10"]}}],
     "'etfs' 인자가 맞지 않습니다"),
    ([RANK, {"skill": "period_returns", "title": "수익률", "display": "bar", "args": {"etfs": ["@rank.1-3", "@rank.4-6"]}}],
     "'etfs' 인자가 맞지 않습니다"),
    ([RANK, {"skill": "holdings", "title": "구성", "display": "table", "args": {"etf": "@rank.1-3"}}], "하나만 들어가는 인자"),
    ([RANK, {"skill": "holdings", "title": "구성", "display": "table", "args": {"etf": "@rank.3-1"}}], "범위가 잘못됐습니다"),
    # 목록 최소 개수는 참조를 펼친 뒤에 원래 Args로 본다 — 참조가 없는 슬롯도 마찬가지
    ([{"skill": "etf_compare", "title": "비교", "display": "table", "args": {"etfs": ["KODEX 200"]}}], "'etfs' 인자가 맞지 않습니다"),
    ([RANK, {"skill": "etf_compare", "title": "비교", "display": "table", "args": {"etfs": ["@rank.1"]}}],
     "'etfs' 인자가 맞지 않습니다"),
])
def test_plan_rejects_bad_references(slots, error):
    with pytest.raises(Exception, match=error):
        _plan_steps(*slots)


def test_plan_rejects_references_of_the_wrong_kind_and_names_the_bridge():
    """종목을 받는 인자에 ETF 목록을 넣으면 거절하고, ETF → 종목으로 잇는 스킬을 알려 준다 (eval에서 실제로 나온 계획)."""
    with pytest.raises(Exception) as e:
        _plan_steps(RANK, {"skill": "stock_trend", "title": "주가", "display": "line", "args": {"stocks": ["@rank.1"]}})
    message = str(e.value)
    assert "'stocks' 인자는 종목을 받는데 '@rank'(stock_holders)은 ETF 목록을 내보냅니다" in message
    assert "holdings 또는 overlap" in message
    with pytest.raises(Exception, match="종목에서 ETF로 이으려면 그 사이에 stock_holders"):
        _plan_steps({"skill": "holdings", "name": "top", "title": "구성", "display": "table", "args": {"etf": "KODEX 200"}},
                    {"skill": "period_returns", "title": "수익률", "display": "bar", "args": {"etfs": ["@top.1"]}})
    # 사이에 holdings를 두면 통과한다
    _plan_steps(RANK, {"skill": "holdings", "name": "top", "title": "구성", "display": "table", "args": {"etf": "@rank.1"}},
                {"skill": "stock_technical", "title": "차트", "display": "candlestick", "args": {"stock": "@top.1"}})


def test_rank_kind_decides_what_it_takes_and_exports():
    stock_rank = {"skill": "rank", "name": "best", "title": "순위", "display": "bar",
                  "args": {"kind": "stock", "targets": ["@top.1-30"], "by": "return"}}
    holdings = {"skill": "holdings", "name": "top", "title": "구성", "display": "table", "args": {"etf": "KODEX 200"}}
    _plan_steps(holdings, stock_rank, {"skill": "stock_trend", "title": "주가", "display": "line", "args": {"stocks": ["@best.1"]}})
    with pytest.raises(Exception, match="'targets' 인자는 ETF를 받는데"):
        _plan_steps(holdings, {**stock_rank, "args": {**stock_rank["args"], "kind": "etf"}},
                    {"skill": "period_returns", "title": "수익률", "display": "bar", "args": {"etfs": ["@best.1"]}})


def test_skill_metadata_is_consistent():
    """참조를 내보내면 종류가 있고, 참조를 받는 인자는 Args에 있다. 카탈로그는 무엇에 관한 스킬인지로 묶는다."""
    from app.services.answer.planner import skill_catalog
    for skill in REGISTRY.values():
        assert set(skill.entity_args) <= set(skill.Args.model_fields), skill.name
        if skill.exports and skill.name != "rank":
            assert skill.exports_kind, skill.name
    catalog = skill_catalog(REGISTRY)
    assert catalog.index("### ETF") < catalog.index("- holdings:") < catalog.index("### 개별 종목")
    assert catalog.index("### 개별 종목") < catalog.index("- company_financials:") < catalog.index("### 공통")
    assert "내보내는 결과(참조 가능, 종목): 종목 목록, ETF 내 비중 높은 순" in catalog
    assert len(re.findall(r"^- \w+:", catalog, re.M)) == len(REGISTRY)



def test_plan_reports_all_reference_errors_at_once():
    """재시도 한 번에 모두 고칠 수 있게 — name 누락과 범위 초과를 함께 알려 준다."""
    no_name = {**RANK, "name": None}
    with pytest.raises(Exception) as e:
        _plan_steps(no_name, {"skill": "period_returns", "title": "수익률", "display": "bar", "args": {"etfs": ["@rank.1-10"]}},
                    {"skill": "holdings", "title": "구성", "display": "table", "args": {"etf": "@rank.1-2"}})
    message = str(e.value)
    assert "오류 4개를 모두 고치세요" in message
    assert message.count("name이 'rank'인 슬롯이 없습니다") == 2
    assert "'etfs' 인자가 맞지 않습니다" in message
    assert "하나만 들어가는 인자" in message


@pytest.mark.parametrize("etfs", [["@rank.1-5"], ["@rank.1-2", "KODEX 200", "@rank.3-4"], ["@rank.1"]])
def test_plan_accepts_references_that_fit_after_expansion(etfs):
    _plan_steps(RANK, {"skill": "period_returns", "title": "수익률", "display": "bar", "args": {"etfs": etfs}})


def test_plan_accepts_a_range_that_fills_a_list_needing_several_items():
    _plan_steps(RANK, {"skill": "etf_compare", "title": "비교", "display": "table", "args": {"etfs": ["@rank.1-3"]}})


class EtfArgs(BaseModel):
    etf: str


class Exporting(DataSkillStub):
    exports = "ETF 목록"

    async def run(self, args, display, ctx):
        yield {**data_result(Dataset(fields=[DataField(key="a", label="a")], rows=[{"a": 1}]), LineView(x="a", y=["a"]),
                             "순위요약", exports=[{"code": "448100", "name": "WON 200"}]).event(),
               "exports": [{"code": "448100", "name": "WON 200"}]}


class Receiving(Skill):
    name = "recv"
    description = "받은 인자를 그대로 요약"
    Args = EtfArgs
    displays = ("table",)
    seen = []

    async def run(self, args, display, ctx):
        Receiving.seen.append((args.etf, list(ctx.related)))
        yield data_result(Dataset(fields=[DataField(key="a", label="a")], rows=[{"a": 1}]), LineView(x="a", y=["a"]),
                          f"받음 {args.etf}").event()


def _ref_slot(id, skill, args, name=None, depends_on=(), title=""):
    return PlannedSlot(id=id, skill=skill, title=title or id, display="table", args=args, name=name,
                       depends_on=list(depends_on))


def test_stream_runs_a_referencing_slot_after_its_target_with_the_code(monkeypatch):
    Receiving.seen = []
    rows = [[_ref_slot("s1", "exp", NoArgs(), name="rank", title="순위"),
             _ref_slot("s2", "recv", EtfArgs(etf="@rank.1"), depends_on=["s1"])]]
    service = _service(monkeypatch, rows, {"exp": Exporting(), "recv": Receiving()})
    events = _collect(service)

    assert Receiving.seen == [("448100", [("순위", "순위요약")])]
    assert service._store.saved == {"s1": "complete", "s2": "complete"}
    order = [e["data"]["id"] for e in events if e["type"] == "slot" and e["data"]["status"] == "running"]
    assert order == ["s1", "s2"]


def test_stream_skips_a_referencing_slot_when_its_target_has_nothing(monkeypatch):
    Receiving.seen = []
    rows = [[_ref_slot("s1", "broken", NoArgs(), name="rank", title="순위"),
             _ref_slot("s2", "recv", EtfArgs(etf="@rank.1"), depends_on=["s1"])]]
    service = _service(monkeypatch, rows, {**REG, "recv": Receiving()})
    events = _collect(service)
    assert Receiving.seen == []
    assert service._store.saved == {"s1": "failed", "s2": "empty"}
    assert any(e["type"] == "slot" and e["data"].get("message") == "'순위' 영역의 결과가 없어 채우지 못했습니다"
               for e in events)


class ListArgs(BaseModel):
    etfs: list


class ReceivingList(Receiving):
    Args = ListArgs

    async def run(self, args, display, ctx):
        Receiving.seen.append(args.etfs)
        yield text_result("받음").event()


def test_range_past_a_filtered_result_is_left_empty_without_replanning(monkeypatch):
    Receiving.seen = []
    rows = [[_ref_slot("s1", "exp", NoArgs(), name="rank", title="순위")],
            [_ref_slot("s2", "recv", ListArgs(etfs=["@rank.1-5"]), depends_on=["s1"]),
             _ref_slot("s3", "recv", ListArgs(etfs=["@rank.6-10"]), depends_on=["s1"])]]
    service = _service(monkeypatch, rows, {"exp": Exporting(), "recv": ReceivingList()})
    service._planner = ReplanningPlanner(rows, rows)
    _collect(service)
    assert Receiving.seen == [["448100"]]
    assert service._store.saved == {"s1": "complete", "s2": "complete", "s3": "empty"}
    assert service._planner.replanned_with is None


def test_stock_holders_exports_etfs_in_rank_order(monkeypatch):
    from app.services.answer.skills import stock_holders as mod
    monkeypatch.setattr(mod, "node", lambda graph, cypher, params: [
        {"code": "448100", "name": "WON 200", "stock": "005930", "weight": 35.24, "expense_ratio": 0.05, "date": "2026-10-08"},
        {"code": "069500", "name": "KODEX 200", "stock": "005930", "weight": 34.9, "expense_ratio": 0.15, "date": "2026-10-08"},
    ])
    skill = REGISTRY["stock_holders"]
    result = skill.fetch(skill.Args(stocks=["삼성전자"]), "bar", None, FakeStockResolver())
    assert result.exports == [{"code": "448100", "name": "WON 200"}, {"code": "069500", "name": "KODEX 200"}]


# --- 레이아웃 예시 ---

LAYOUT_SEED_MIGRATIONS = ("0013_layout_examples.py", "0021_layout_examples_rank_overlap.py", "0025_layout_examples_company.py",
                          "0026_report_summaries.py", "0029_layout_example_customers.py",
                          "0030_revenue_mix_skill.py")


def _layout_seeds():
    seeds = []
    for name in LAYOUT_SEED_MIGRATIONS:
        path = Path(__file__).parent.parent / "migrations/versions" / name
        spec = importlib.util.spec_from_file_location(f"layout_examples_{name[:4]}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        seeds += module.SEEDS
    return seeds


@pytest.mark.parametrize("seed", _layout_seeds(), ids=lambda s: s["question"])
def test_layout_seed_plans_pass_planner_validation(seed):
    rows = to_rows(build_plan_model(REGISTRY).model_validate(seed["plan"]))
    assert rows


def test_examples_prompt_uses_generalized_question_and_one_line_plan():
    plan = {"rows": [{"slots": [{"skill": "stock_holders", "title": "t", "display": "bar",
                                 "args": {"stocks": ["<종목1>", "<종목2>"]}}]}]}
    text = examples_prompt([{"id": 1, "question": "테스와 원익IPS를 많이 담은 ETF", "question_generalized": "특정 종목 2개를 많이 담은 ETF",
                             "plan": json.dumps(plan, indent=2)}])
    assert "Q: 특정 종목 2개를 많이 담은 ETF\n" in text
    assert json.dumps(plan, ensure_ascii=False) in text
    assert "테스" not in text


def test_planner_plans_without_examples_when_search_fails(monkeypatch):
    from app.services.answer import planner as planner_mod

    class FakeAgent:
        prompt = None

        async def run(self, prompt):
            FakeAgent.prompt = prompt
            raise RuntimeError("stop here")

    def broken_search(question):
        raise RuntimeError("embedding down")

    planner = planner_mod.Planner.__new__(planner_mod.Planner)
    planner._agent, planner._find_examples = FakeAgent(), broken_search
    rows = asyncio.run(planner.plan("질문", ConversationContext()))
    assert FakeAgent.prompt == "## 질문\n질문"
    assert rows[0][0].skill == "agent"


@pytest.mark.parametrize("items, hint", [
    (["@rank.1-10"], '슬롯 2개에 각각 ["@rank.1-5"], ["@rank.6-10"]'),
    (["KODEX 200", "@rank.1-10"], '슬롯당 순위는 4개까지입니다. 이 스킬 슬롯들이 받는 1~10위를 모두 합쳐, 기존 슬롯 대신 슬롯 3개에 각각 '
                                  '["KODEX 200", "@rank.1-4"], ["KODEX 200", "@rank.5-8"], ["KODEX 200", "@rank.9-10"]'),
    (["@rank.1-3", "@rank.4-6"], '슬롯 2개에 각각 ["@rank.1-5"], ["@rank.6"]'),
    (["A", "B", "C", "D", "E", "@rank.1"], "자리가 없습니다"),
    (["@a.1-3", "@b.1-3"], "여럿으로 나눠"),
])
def test_split_hint_counts_named_items(items, hint):
    assert hint in refs.split_hint(items, 5)


def test_range_error_suggests_split_that_fits():
    with pytest.raises(Exception, match=re.escape('["KODEX 200", "@rank.1-4"], ["KODEX 200", "@rank.5-8"], ["KODEX 200", "@rank.9-10"]')):
        _plan_steps(RANK, {"skill": "period_returns", "title": "수익률", "display": "bar",
                           "args": {"etfs": ["KODEX 200", "@rank.1-10"]}})


def test_range_error_splits_ranks_of_all_slots_of_the_skill():
    """첫 슬롯만 보고 '@rank.1-4', '@rank.5'를 제안하면 5위가 옆 슬롯으로 밀려 또 넘친다 — 전체 1~10위를 다시 나눈다."""
    with pytest.raises(Exception, match=re.escape('1~10위를 모두 합쳐, 기존 슬롯 대신 슬롯 3개에 각각 ["KODEX 200", "@rank.1-4"]')):
        _plan_steps(RANK,
                    {"skill": "period_returns", "title": "가", "display": "bar", "args": {"etfs": ["@rank.1-5", "KODEX 200"]}},
                    {"skill": "period_returns", "title": "나", "display": "bar", "args": {"etfs": ["@rank.6-10"]}})


@pytest.mark.parametrize("slots", [
    # KODEX 200이 넘친 슬롯이 아니라 옆 슬롯에 있어도, 어느 슬롯이 넘쳐도 같은 안내
    [["@rank.1-4", "KODEX 200"], ["@rank.5-10"]],
    [["@rank.1-5"], ["@rank.6-10", "KODEX 200"]],
    # 5위가 빠진 채 넘쳐도 1~10위를 빠짐없이 나눈다
    [["@rank.1-4", "KODEX 200"], ["@rank.6-10", "KODEX 200"]],
])
def test_range_error_hint_is_the_same_whichever_slot_overflows(slots):
    steps = [{"skill": "period_returns", "title": f"t{i}", "display": "bar", "args": {"etfs": etfs}} for i, etfs in enumerate(slots)]
    with pytest.raises(Exception, match=re.escape('슬롯 3개에 각각 ["KODEX 200", "@rank.1-4"], ["KODEX 200", "@rank.5-8"], ["KODEX 200", "@rank.9-10"]')):
        _plan_steps(RANK, *steps)


def _returns(*etf_lists):
    return [{"skill": "period_returns", "title": f"t{i}", "display": "bar", "args": {"etfs": etfs}} for i, etfs in enumerate(etf_lists)]


def test_plan_rejects_ranks_skipped_between_ranges():
    with pytest.raises(Exception, match="5위를 빠뜨렸습니다"):
        _plan_steps(RANK, *_returns(["@rank.1-4", "KODEX 200"], ["@rank.6-10"]))


@pytest.mark.parametrize("etf_lists", [
    (["@rank.1", "@rank.3"],),              # 한 순위씩 고른 건 일부러 고른 것
    (["@rank.1-4", "KODEX 200"], ["@rank.5-8"]),
])
def test_plan_accepts_ranks_without_gaps_or_picked_one_by_one(etf_lists):
    _plan_steps(RANK, *_returns(*etf_lists))


def test_related_text_carries_notes_to_the_narrative():
    result = {"summary": "KODEX 200: 1일 -3.83%", "content": {"notes": ["찾지 못한 ETF: ACE KRX금현물(관리하지 않는 ETF)"]}}
    assert orch._related_text(result) == "KODEX 200: 1일 -3.83%\n(참고) 찾지 못한 ETF: ACE KRX금현물(관리하지 않는 ETF)"
    assert orch._related_text({"message": "결과 없음"}) == "결과 없음"


def _choice(condition, by="theme"):
    return {"skill": "etf_choice", "title": "선택", "display": "markdown",
            "args": {"by": by, "condition": condition, "purpose": "구성종목"}}


@pytest.mark.parametrize("slot, errors", [
    (_choice("PLUS K방산"), 1),          # 상품 이름을 테마로 되물으면 안 된다
    (_choice("방산"), 0),
    (_choice("PLUS K방산", by="stock"), 0),  # 종목 조건은 이름 검사 대상이 아니다
])
def test_planner_rejects_a_theme_that_is_an_etf_name(slot, errors):
    from app.services.answer.planner import data_errors
    found = data_errors(_plan_steps(slot), lambda name: name == "PLUS K방산")
    assert len(found) == errors
    if errors:
        assert "ETF 상품 이름입니다" in found[0]


def test_plan_rejects_a_name_nobody_references():
    with pytest.raises(Exception, match="name 'rank'을 붙였지만 '@rank.순위'로 받는 슬롯이 없습니다"):
        _plan_steps(RANK)


# --- 실행 결과를 보고 다시 설계 ---

class Lookup(Skill):
    """이름이 '맞는이름'일 때만 찾는다. 못 찾으면 고칠 수 있는 실패."""
    name = "lookup"
    description = "이름으로 찾기"
    Args = EtfArgs
    displays = ("table",)
    runs = []

    async def run(self, args, display, ctx):
        from app.services.answer.skills.base import not_found
        Lookup.runs.append(args.etf)
        if args.etf != "맞는이름":
            yield not_found(f"찾지 못했습니다: {args.etf}").event()
            return
        yield text_result(f"찾음 {args.etf}").event()


class ReplanningPlanner(FakePlanner):
    def __init__(self, rows, fixed_rows):
        super().__init__(rows)
        self.fixed_rows = fixed_rows
        self.replanned_with = None

    async def replan(self, question, context, rows, results):
        self.replanned_with = {i: (r["status"], r.get("retryable", False)) for i, r in results.items()}
        return self.fixed_rows


def _lookup(id, etf, title="찾기"):
    return PlannedSlot(id=id, skill="lookup", title=title, display="table", args=EtfArgs(etf=etf))


REPLAN_REG = {"lookup": Lookup(), "data": DataSkillStub(), "narr": EchoNarrative()}


def _replan_service(monkeypatch, rows, fixed_rows):
    service = _service(monkeypatch, rows, REPLAN_REG)
    service._planner = ReplanningPlanner(rows, fixed_rows)
    return service


def test_replans_a_slot_that_can_be_fixed_before_the_narrative(monkeypatch):
    Lookup.runs = []
    rows = [[_lookup("s1", "틀린이름"), _slot("s2", "data", "다른")], [_slot("s3", "narr", "해설")]]
    fixed = [[_lookup("s1", "맞는이름"), _slot("s2", "data", "다른")], [_slot("s3", "narr", "해설")]]
    service = _replan_service(monkeypatch, rows, fixed)
    events = _collect(service)

    # 해설은 다시 설계하기 전에 돌지 않았고, 그대로인 슬롯(s2)은 다시 돌지 않는다
    assert service._planner.replanned_with == {"s1": ("empty", True), "s2": ("complete", False)}
    assert Lookup.runs == ["틀린이름", "맞는이름"]
    kinds = [e["type"] for e in events]
    assert kinds.count("layout") == 2
    assert {"stage": "replanning"} in [e["data"] for e in events if e["type"] == "status"]
    narrative = next(e for e in events if e["type"] == "answer")["data"]["answer"]
    assert "찾음 맞는이름" in narrative and service._store.saved["s1"] == "complete"
    assert sum(1 for e in events if e["type"] == "slot" and e["data"] == {"id": "s2", "status": "running"}) == 1


def test_replan_keeps_a_title_the_skill_set_on_a_slot_that_does_not_rerun(monkeypatch):
    rows = [[_lookup("s1", "틀린이름"), _slot("s2", "titled", "보고서 요약")], [_slot("s3", "narr", "해설")]]
    fixed = [[_lookup("s1", "맞는이름"), _slot("s2", "titled", "보고서 요약")], [_slot("s3", "narr", "해설")]]
    service = _service(monkeypatch, rows, {**REPLAN_REG, "titled": TitledSkill()})
    service._planner = ReplanningPlanner(rows, fixed)
    events = _collect(service)
    last = [e["data"]["layout"] for e in events if e["type"] == "layout"][-1]
    assert last["children"][0]["children"][1]["title"] == "삼성전자 2026년 반기보고서 요약"


def test_does_not_replan_failures_that_a_new_plan_cannot_fix(monkeypatch):
    rows = [[_slot("s1", "data", "가")], [_slot("s2", "narr", "해설")]]
    service = _replan_service(monkeypatch, rows, rows)
    _collect(service)
    assert service._planner.replanned_with is None


def test_keeps_the_first_results_when_replanning_gives_nothing(monkeypatch):
    Lookup.runs = []
    rows = [[_lookup("s1", "틀린이름")], [_slot("s2", "narr", "해설")]]
    service = _replan_service(monkeypatch, rows, None)
    events = _collect(service)
    assert Lookup.runs == ["틀린이름"]
    assert [e["type"] for e in events].count("layout") == 1
    # 데이터 영역이 모두 같은 안내로 비었으니 해설도 그 안내만 남긴다
    assert service._store.saved == {"s1": "empty", "s2": "empty"}


def test_replan_must_keep_the_layout_and_the_slots_that_worked():
    from app.services.answer.planner import ReplanDeps, editable_slots, replan_errors

    rank = {**RANK, "args": {"stocks": ["삼성전자"], "top": 10}}
    holdings = {"skill": "holdings", "title": "구성", "display": "table", "args": {"etf": "@rank.1", "top": 10}}
    first = _plan_steps(rank, holdings)
    slots = to_rows(first)[0]
    results = {"s1": {"status": "empty", "retryable": True}, "s2": {"status": "empty"}}
    editable = editable_slots(slots, results, REGISTRY)
    assert editable == {"s1", "s2"}  # 고칠 수 있는 슬롯과 그 결과를 받는 슬롯
    previous = [[s.model_dump() for s in row.slots] for row in first.rows]

    deps = ReplanDeps(previous=previous, editable={"s1"})
    changed = {**holdings, "args": {"etf": "@rank.2", "top": 10}}
    assert "이전 계획 그대로 두세요" in replan_errors(_plan_steps(rank, changed), deps)[0]
    assert replan_errors(_plan_steps({**rank, "args": {"stocks": ["삼성전자우"], "top": 10}}, holdings), deps) == []
    assert "배치" in replan_errors(build_plan_model(REGISTRY).model_validate(
        {"rows": [{"slots": [rank]}, {"slots": [holdings]}]}), deps)[0]


def test_a_stock_name_in_an_etf_slot_is_a_fixable_failure_not_a_question(fake_etf_graph, monkeypatch):
    from app.services.entities import EntityResolver
    from app.services.answer.skills.base import SkillContext

    resolver = EntityResolver()
    monkeypatch.setattr(resolver, "stock", lambda db, name: {"code": "005380", "name": "반도체"} if name == "반도체" else None)

    async def run():
        ctx = SkillContext(question="q", conversation=ConversationContext(), session_factory=lambda: _Closable(),
                           resolver=resolver, ai_config=None, stop=asyncio.Event())
        skill = REGISTRY["holdings"]
        return [e async for e in skill.run(skill.Args(etf="반도체"), "treemap", ctx)]

    result = asyncio.run(run())[-1]
    assert (result["status"], result["retryable"], result["clarify"]) == ("empty", True, False)
    assert "ETF가 아니라 개별 종목입니다" in result["message"]


def _selector_planner(choose):
    from app.services.answer import planner as planner_mod

    class FakeSelector:
        async def run(self, prompt):
            ids = choose(prompt)

            class Result:
                output = planner_mod.ExampleChoice(ids=ids)
            return Result()

    planner = planner_mod.Planner.__new__(planner_mod.Planner)
    planner._selector = FakeSelector()
    return planner


CANDIDATES = [{"id": 10 + i, "question": f"q{i}", "question_generalized": f"g{i}", "description": "",
               "plan": json.dumps({"rows": [{"slots": [{"skill": "holdings", "args": {"etf": "<ETF>"}}]}]}),
               "distance": d} for i, d in enumerate([0.10, 0.12, 0.30, 0.40])]


def test_example_selector_keeps_valid_unique_choices_up_to_the_limit():
    planner = _selector_planner(lambda prompt: [4, 4, 9, 2, 1, 3])
    picked = asyncio.run(planner._select("질문", CANDIDATES))
    assert [ex["id"] for ex in picked] == [13, 11, 10]  # 범위 밖 번호·중복은 버리고 최대 3개


def test_example_selector_lists_candidates_with_their_skills():
    seen = []
    planner = _selector_planner(lambda prompt: seen.append(prompt) or [])
    assert asyncio.run(planner._select("질문", CANDIDATES)) == []
    assert "[1] g0" in seen[0] and "스킬: holdings" in seen[0]


def test_example_selector_falls_back_to_distance_when_it_fails():
    def broken(prompt):
        raise RuntimeError("LLM down")
    picked = asyncio.run(_selector_planner(broken)._select("질문", CANDIDATES))
    assert [ex["id"] for ex in picked] == [10, 11]  # 0.35 안이고 1위와 0.05 차이 안


def test_stream_skips_refine_when_user_asks_for_the_original(monkeypatch):
    class RewritingMemory(FakeMemory):
        def refine(self, message, context):
            return "다시 쓴 질문"

    service = _service(monkeypatch, [[_slot("s1", "data")]], REG)
    service.memory = RewritingMemory(None)
    context = ConversationContext(summary="이전 대화")

    async def run(refine):
        return [e async for e in service.stream("질문", context, 7, asyncio.Event(), refine=refine)]

    assert any(e["type"] == "refined_question" for e in asyncio.run(run(True)))
    events = asyncio.run(run(False))
    assert not any(e["type"] == "refined_question" for e in events)
    assert {"type": "status", "data": {"stage": "refining"}} not in events


# --- 수치로 다시 고르기·비중 조건·구성 겹침 ---

def test_stock_holders_keeps_only_etfs_above_the_weight(monkeypatch):
    from app.services.answer.skills import stock_holders as mod
    monkeypatch.setattr(mod, "node", lambda graph, cypher, params: [
        {"code": "A", "name": "많이", "stock": "005930", "weight": 24.0, "expense_ratio": 0.4, "date": "2026-10-07"},
        {"code": "B", "name": "조금", "stock": "005930", "weight": 9.5, "expense_ratio": 0.3, "date": "2026-10-07"},
    ])
    skill = REGISTRY["stock_holders"]
    result = skill.fetch(skill.Args(stocks=["삼성전자"], min_weight=10), "bar", None, FakeStockResolver())
    assert result.exports == [{"code": "A", "name": "많이"}]
    assert "10% 이상" in result.summary
    empty = skill.fetch(skill.Args(stocks=["삼성전자"], min_weight=30), "bar", None, FakeStockResolver())
    assert (empty.status, empty.retryable) == ("empty", False)
    cut = skill.fetch(skill.Args(stocks=["삼성전자"], min_weight=5, top=3), "bar", None, FakeStockResolver())
    assert "조건에 맞는 ETF" not in " ".join(cut.content["notes"])  # 2개 모두 보인다


def test_holdings_keeps_only_stocks_above_the_weight(monkeypatch):
    monkeypatch.setattr(holdings_mod, "node", lambda graph, cypher, params: [
        {"code": "005930", "name": "삼성전자", "weight": 30.0, "date": "2026-10-07"},
        {"code": "000660", "name": "SK하이닉스", "weight": 2.0, "date": "2026-10-07"},
    ])
    skill = REGISTRY["holdings"]
    result = skill.fetch(skill.Args(etf="KODEX 200", min_weight=5), "table", None, FakeResolver())
    assert result.exports == [{"code": "005930", "name": "삼성전자"}]
    assert [r["name"] for r in result.content["dataset"]["rows"]] == ["삼성전자"]
    cut = skill.fetch(skill.Args(etf="KODEX 200", min_weight=1, top=3), "table", None, FakeResolver())
    assert cut.content["notes"] == []


def test_lookthrough_keeps_only_stocks_above_the_combined_weight(lookthrough, monkeypatch):
    skill = REGISTRY["portfolio_lookthrough"]
    args = skill.Args(items=[{"asset": "KODEX 200", "allocation": 50}, {"asset": "KODEX 반도체", "allocation": 50}],
                      min_weight=25)
    result = skill.fetch(args, "table", None, FakePortfolioResolver())
    # 삼성전자 27.5, 한미반도체 25, SK하이닉스 22.5
    assert result.exports == [{"code": "005930", "name": "삼성전자"}, {"code": "042700", "name": "한미반도체"}]


class FakeRankResolver:
    ETFS = {n: {"code": c, "name": n} for n, c in [("가", "000001"), ("나", "000002"), ("다", "000003")]}

    def etfs(self, db, names):
        found = [self.ETFS[n] for n in names if n in self.ETFS]
        return found, [n for n in names if n not in self.ETFS]

    def stocks(self, db, names):
        return self.etfs(db, names)


def test_rank_args_need_one_source_and_etf_only_metrics_for_etfs():
    Args = REGISTRY["rank"].Args
    assert Args(kind="etf", by="dividend_yield").targets == []  # 후보를 비우면 ETF 전체
    with pytest.raises(ValueError, match="targets로"):
        Args(kind="stock", by="return_1w")
    with pytest.raises(ValueError, match="ETF에만"):
        Args(kind="stock", targets=["가"], by="dividend_yield")
    with pytest.raises(ValueError, match="하나만"):
        Args(kind="etf", targets=["가"], theme="반도체", by="net_assets")
    with pytest.raises(ValueError, match="ETF에만"):
        Args(kind="stock", targets=["가"], by="expense_ratio")
    # 예전 계획의 return_1m은 by=return + period로 읽는다
    legacy = Args(kind="etf", by="return_3m")
    assert (legacy.by, legacy.period) == ("return", "3m")
    assert Args(kind="etf", by="return").period == "1m"


def test_rank_orders_filters_and_exports_by_the_metric(monkeypatch):
    from app.services.answer.skills import rank as mod
    queries = []

    def fake_node(graph, cypher, params):
        queries.append(cypher)
        return [{"code": "000001", "value": 0.45}, {"code": "000002", "value": 0.05}, {"code": "000003", "value": None}]

    monkeypatch.setattr(mod, "node", fake_node)
    monkeypatch.setattr(mod, "GraphService", lambda db: None)
    skill = REGISTRY["rank"]
    args = skill.Args(kind="etf", targets=["가", "나", "다", "없음"], by="expense_ratio", order="asc", top=5)
    result = skill.fetch(args, "table", None, FakeRankResolver())
    assert "IN ['000001', '000002', '000003']" in queries[0]
    assert result.exports == [{"code": "000002", "name": "나"}, {"code": "000001", "name": "가"}]
    assert "총보수 낮은 순" in result.summary
    assert any("데이터가 없어 뺀 ETF: 다" in n for n in result.content["notes"])
    assert any("찾지 못한 ETF: 없음" in n for n in result.content["notes"])

    filtered = skill.fetch(skill.Args(kind="etf", targets=["가", "나"], by="expense_ratio", max_value=0.1),
                           "table", None, FakeRankResolver())
    assert filtered.exports == [{"code": "000002", "name": "나"}]


def test_rank_without_candidates_filters_every_etf_by_dividend_yield(monkeypatch):
    from app.services.answer.skills import rank as mod
    queries = []

    def fake_node(graph, cypher, params):
        queries.append(cypher)
        if "e.dividend_yield" in cypher:
            return [{"code": "000001", "value": 6.29}, {"code": "000002", "value": 4.65}, {"code": "000003", "value": 0}]
        return [{"code": "000001", "name": "가"}, {"code": "000002", "name": "나"}, {"code": "000003", "name": "다"}]

    monkeypatch.setattr(mod, "node", fake_node)
    monkeypatch.setattr(mod, "GraphService", lambda db: None)
    skill = REGISTRY["rank"]
    result = skill.fetch(skill.Args(kind="etf", by="dividend_yield", min_value=4, top=30), "table", None, FakeRankResolver())
    assert queries[0].startswith("MATCH (e:ETF) RETURN {code: e.code, name: e.name}")
    assert result.exports == [{"code": "000001", "name": "가"}, {"code": "000002", "name": "나"}]
    assert "후보 ETF 3개 중 분배율(최근 12개월) 높은 순(4.00% 이상) 2개" in result.summary
    assert any("최근 12개월 분배금" in n for n in result.content["notes"])


def test_rank_computes_period_returns_from_prices(monkeypatch):
    from app.services.answer.skills import rank as mod
    prices = {"000001": [("2026-10-01", 100), ("2026-10-08", 110)], "000002": [("2026-10-01", 100), ("2026-10-08", 90)]}

    class FakeGraph:
        def get_stock_prices(self, code, days):
            return [{"date": d, "close": c} for d, c in prices.get(code, [])]

    monkeypatch.setattr(mod, "GraphService", lambda db: FakeGraph())
    skill = REGISTRY["rank"]
    result = skill.fetch(skill.Args(kind="stock", targets=["가", "나", "다"], by="return_1w", top=1),
                         "bar", None, FakeRankResolver())
    assert result.exports == [{"code": "000001", "name": "가"}]
    assert result.content["dataset"]["rows"][0]["value"] == 10.0
    assert "후보 종목 3개 중 1주 수익률 높은 순" in result.summary
    assert result.content["notes"][0] == "조회 기간: 2026-10-01 ~ 2026-10-08 (종가 기준)"
    assert result.content["sources"][0]["as_of"] == "2026-10-08"
    asked = skill.fetch(skill.Args(kind="stock", targets=["가", "나"], by="return", period="6d"),
                        "bar", None, FakeRankResolver())
    assert "6일 수익률" in asked.summary and asked.content["dataset"]["fields"][2]["label"] == "6일 수익률"
    no_data = skill.fetch(skill.Args(kind="stock", targets=["다"], by="return_1y"), "bar", None, FakeRankResolver())
    assert no_data.message == "후보 종목 1개 모두 1년 수익률 데이터가 없습니다"


def test_period_returns_adds_asked_period_and_shows_start_dates(monkeypatch):
    from app.services.answer.skills import period_returns as mod
    dates = ["2025-12-30", "2026-09-23", "2026-10-09", "2026-10-16", "2026-10-22", "2026-10-23"]

    class FakeGraph:
        def get_etf_prices(self, code, days):
            return [{"date": d, "close": 100.0 + i} for i, d in enumerate(dates)]

    monkeypatch.setattr(mod, "GraphService", lambda db: FakeGraph())
    skill = REGISTRY["period_returns"]
    result = skill.fetch(skill.Args(etfs=["가"], period="2w"), "bar", None, FakeRankResolver())
    rows = result.content["dataset"]["rows"]
    assert [r["period"] for r in rows] == ["1일", "1주", "2주", "1개월", "3개월", "6개월"]
    assert next(r for r in rows if r["period"] == "2주")["start"] == "2026-10-09"
    assert result.content["notes"][0].startswith("2026-10-23 종가 기준, 시작일: 1일 2026-10-22 · 1주 2026-10-16 · 2주 2026-10-09")
    # 가격 추이도 같은 시작점에서 그려 2주 등락률이 기간 수익률과 같다
    from app.services.answer.skills import price_trend as trend_mod
    monkeypatch.setattr(trend_mod, "GraphService", lambda db: FakeGraph())
    trend = REGISTRY["price_trend"]
    two_weeks = trend.fetch(trend.Args(etfs=["가"], period="2w"), "table", None, FakeRankResolver())
    assert two_weeks.content["dataset"]["rows"][0]["change"] == next(r for r in rows if r["period"] == "2주")["000001"]
    assert two_weeks.content["notes"] == ["조회 기간: 2026-10-09 ~ 2026-10-23 (2주)"]
    too_long = trend.fetch(trend.Args(etfs=["가"], period="2y"), "table", None, FakeRankResolver())
    assert "요청한 기간보다 데이터가 짧습니다: 가 2025-12-30부터" in too_long.content["notes"]
    ytd = skill.fetch(skill.Args(etfs=["가"], period="ytd"), "table", None, FakeRankResolver())
    assert next(r for r in ytd.content["dataset"]["rows"] if r["period"] == "연초 이후")["start"] == "2025-12-30"


def test_overlap_splits_common_and_only_holdings():
    from app.services.answer.skills.overlap import overlap

    def h(code, weight):
        return {"stock_code": code, "stock_name": code, "weight": weight}

    o = overlap([h("A", 30), h("B", 20), h("C", 5)], [h("A", 10), h("B", 25), h("D", 40)])
    assert o["common"] == ["B", "A"]  # 두 비중 합이 큰 순
    assert (o["only_a"], o["only_b"]) == (["C"], ["D"])
    assert (o["overlap"], o["common_a"], o["common_b"]) == (30.0, 50.0, 35.0)


def test_overlap_skill_exports_common_stocks(monkeypatch):
    from app.services.answer.skills import overlap as mod
    monkeypatch.setattr(mod, "_holdings", lambda db, codes: {
        "000001": [{"stock_code": "005930", "stock_name": "삼성전자", "weight": 30.0, "date": "2026-10-07"},
                   {"stock_code": "000660", "stock_name": "SK하이닉스", "weight": 10.0, "date": "2026-10-07"}],
        "000002": [{"stock_code": "005930", "stock_name": "삼성전자", "weight": 20.0, "date": "2026-10-07"}],
    })
    skill = REGISTRY["overlap"]
    result = skill.fetch(skill.Args(etfs=["가", "나"]), "table", None, FakeRankResolver())
    assert result.exports == [{"code": "005930", "name": "삼성전자"}]
    rows = result.content["dataset"]["rows"]
    assert [(r["name"], r["where"], r["a"], r["b"]) for r in rows] == [
        ("삼성전자", "공통", 30.0, 20.0), ("SK하이닉스", "가만", 10.0, None)]
    assert "겹치는 비중 20.00%" in result.summary
    missing = skill.fetch(skill.Args(etfs=["가", "없음"]), "table", None, FakeRankResolver())
    assert (missing.status, missing.retryable) == ("empty", True)


def test_cut_note_tells_how_many_passed_the_filter():
    from app.services.answer.skills.common import cut_note
    assert cut_note(8, 5, "ETF") == ["조건에 맞는 ETF 8개 중 상위 5개만 표시했습니다"]
    assert cut_note(3, 5, "ETF") == []


class Notice(DataSkillStub):
    """분석하지 않는 대상처럼 모든 영역이 같은 문구로 비는 스킬."""

    def __init__(self, message):
        self.message = message

    async def run(self, args, display, ctx):
        yield empty(self.message).event()


def test_narrative_takes_the_shared_notice_instead_of_restating_it(monkeypatch):
    notice = "삼양식품(003230) 종목은 지금 수집하는 ETF 어디에도 담겨 있지 않아 분석할 수 없습니다"
    registry = {"a": Notice(notice), "b": Notice(notice), "narr": EchoNarrative()}
    service = _service(monkeypatch, [[_slot("s1", "a"), _slot("s2", "b")], [_slot("s3", "narr", "해설")]], registry)
    events = _collect(service)
    assert service._store.saved == {"s1": "empty", "s2": "empty", "s3": "empty"}
    narr = [e["data"] for e in events if e["type"] == "slot" and e["data"]["id"] == "s3"]
    assert narr[-1]["message"] == notice
    assert not any(e["type"] == "slot_delta" for e in events)  # 해설 LLM을 부르지 않는다


def test_narrative_still_explains_different_notices(monkeypatch):
    registry = {"a": Notice("가 없음"), "b": Notice("나 없음"), "narr": EchoNarrative()}
    service = _service(monkeypatch, [[_slot("s1", "a"), _slot("s2", "b")], [_slot("s3", "narr", "해설")]], registry)
    _collect(service)
    assert service._store.saved["s3"] == "complete"


def test_stock_technical_draws_indicators_and_states_each_one(monkeypatch):
    from datetime import date, timedelta
    from app.services.answer.skills import stock_technical as mod
    days = [date(2026, 10, 27) - timedelta(days=i) for i in range(400)]
    days = sorted(d for d in days if d.weekday() < 5)[-260:]
    # 오르다가 마지막 60거래일은 내린다
    closes = [100.0 + i for i in range(200)] + [300.0 - 2 * i for i in range(60)]
    bars = [{"date": d.isoformat(), "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1000}
            for d, c in zip(days, closes)]

    class FakeGraph:
        def get_stock_prices(self, code, days):
            return bars

    class FakeResolver:
        def stock(self, db, name):
            return {"code": "005930", "name": "삼성전자"} if name == "삼성전자" else None

    monkeypatch.setattr(mod, "GraphService", lambda db: FakeGraph())
    skill = REGISTRY["stock_technical"]
    result = skill.fetch(skill.Args(stock="삼성전자", first="rsi"), "candlestick", None, FakeResolver())
    view, rows = result.content["view"], result.content["dataset"]["rows"]
    assert [p["label"] for p in view["panels"]] == ["RSI(14)", "MACD(12,26,9)", "스토캐스틱 슬로우(5,3,3)"]
    assert view["overlays"] == ["ma5", "ma20", "ma60", "ma120", "bb_upper", "bb_lower"]
    # 화면에서 고르는 기간마다 시작일, 행은 가장 긴 1년까지 — 질문한 6개월이 처음 보인다
    assert [(r["label"], r["start"]) for r in view["ranges"]] == [
        ("1개월", "2026-09-25"), ("6개월", "2026-04-30"), ("1년", "2025-10-29")]
    # 일봉이 260거래일뿐이라 1년은 처음부터, 짧다고 표시한다
    assert [r["short"] for r in view["ranges"]] == [False, False, True]
    assert view["range"] == 1 and rows[0]["date"] == "2025-10-29"
    # 기간 앞의 일봉까지 넣어 계산해 6개월 첫날부터 120일선이 있다
    assert next(r for r in rows if r["date"] == "2026-04-30")["ma120"] is not None
    assert result.content["notes"][0] == "조회 기간: 2026-04-30 ~ 2026-10-27 (6개월)"
    summary = result.summary
    assert "이평 배열: 정배열도 역배열도 아님" in summary or "역배열" in summary
    for part in ("[MACD(12,26,9)]", "MACD선이 시그널선 아래", "[RSI(14)]", "과매도 기준(30 이하) 구간",
                 "[스토캐스틱 슬로우(5,3,3)]", "[볼린저 밴드(20,2)]"):
        assert part in summary
    assert [sg["key"] for sg in result.content["signals"]] == ["trend", "macd", "rsi", "stochastic"]
    assert "신호(엘더 MACD 히스토그램 기준, 화면에 표시)" in summary
    assert skill.fetch(skill.Args(stock="없는종목"), "candlestick", None, FakeResolver()).retryable


def test_stock_technical_histogram_trend_names_the_side():
    from app.services.answer.skills.stock_technical import _hist_trend
    assert _hist_trend([-5, -4, -3, -2]) == "음(−) 영역에서 폭이 최근 3거래일 연속 줄어듦 (두 선이 좁혀짐)"
    assert _hist_trend([1, 2, 3, 4]) == "양(+) 영역에서 폭이 최근 3거래일 연속 커짐 (두 선이 벌어짐)"
    assert _hist_trend([-1, 1, 2, 3]).startswith("최근 3거래일 사이 0을 지남")
    assert _hist_trend([1, 2]) == "판단할 데이터 부족"


def test_stock_technical_signals_follow_the_masters_rules():
    from app.domain import indicators as ind, signals as sig
    from app.services.answer.skills.stock_technical import _pad
    # 엘더: 히스토그램 기울기 — 0 아래에서 위로 꺾이면 ▲▲, 0 위에서 아래로 꺾이면 ▼▼
    assert sig.macd_signal([-3, -4, -2]).level == 2
    assert sig.macd_signal([3, 4, 2]).level == -2
    assert sig.macd_signal([-4, -3, -2]).state == "히스토그램이 0 아래에서 올라가는 중"
    assert sig.macd_signal([1, 2]).level is None
    # 카드웰: 범위와 범위 전환
    assert sig.rsi_signal([45.0] * 60).level == 1
    assert sig.rsi_signal([65.0] * 60).level == 2
    assert sig.rsi_signal([55.0] * 60).level == 1
    assert sig.rsi_signal([35.0] * 60).level == -2
    assert sig.rsi_signal([50.0] * 50 + [38.0] * 10).state.startswith("범위 전환: 강세 범위에서 40 붕괴")
    assert sig.rsi_signal([30.0, 70.0] * 30).level == 0
    # 와인스타인: 오르는 150일선 위 2단계, 내리는 150일선 아래 4단계
    up = [100.0 + i for i in range(300)]
    ma = {p: _pad(ind.rolling_mean(up, p), len(up)) for p in (50, 150, 200)}
    bars = [{"high": c + 1, "low": c - 1, "close": c} for c in up]
    trend = sig.trend_signal(up, bars, ma)
    assert trend.level == 2 and "미너비니 조건 7/7" in trend.state
    down = up[::-1]
    ma = {p: _pad(ind.rolling_mean(down, p), len(down)) for p in (50, 150, 200)}
    assert sig.trend_signal(down, bars[::-1], ma).level == -2
    # 스토캐스틱은 화살표 없이 추세 안의 위치만
    stoch = sig.stoch_signal([10.0], [15.0], (2, "2단계"))
    assert stoch.level is None and stoch.state.startswith("상승 추세 속 눌림")


def test_skills_marked_as_tools_reach_the_agent_with_the_slot_summary():
    """tool을 켠 데이터 스킬만 agent 도구가 되고, 결과는 슬롯과 같은 요약과 주석이다. 인자가 틀리면 모델에게 돌려준다."""
    from pydantic import BaseModel
    from pydantic_ai import ModelRetry
    from app.services.answer import tools
    from app.services.answer.skills.base import DataSkill, data_result, empty

    class FakeArgs(BaseModel):
        stock: str

    class Fake(DataSkill):
        name, description, Args, displays, tool = "fake", "가짜 스킬", FakeArgs, ("table",), True

        def fetch(self, args, display, db, resolver):
            if args.stock == "없음":
                return empty("데이터가 없습니다")
            dataset = Dataset(fields=[DataField(key="v", label="값")], rows=[{"v": 1}])
            return data_result(dataset, LineView(x="v", y=["v"]), f"{args.stock} 요약", notes=["주석 하나"])

    class Off(Fake):
        name, tool = "off", False

    sessions = []
    built = tools.skill_tools({"fake": Fake(), "off": Off(), "narrative": REGISTRY["narrative"]},
                              lambda: sessions.append(object()) or type("S", (), {"close": lambda self: None})())
    assert [t.name for t in built] == ["fake"]
    run = built[0].function
    assert run(stock="삼성전자") == "삼성전자 요약\n주석: 주석 하나"
    assert run(stock="없음") == "데이터가 없습니다"
    assert len(sessions) == 2  # 부를 때마다 세션을 따로 연다 (도구끼리 병렬로 돈다)
    with pytest.raises(ModelRetry):
        run(code="005930")
    assert "참조를 쓸 수 없다" in built[0].description
    assert {s.name for s in REGISTRY.values() if s.tool} == {
        "company_financials", "company_valuation", "company_disclosures", "stock_technical", "period_returns", "rank",
        "overlap", "portfolio_lookthrough"}
