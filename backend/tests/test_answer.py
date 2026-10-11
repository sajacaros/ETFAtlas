import asyncio

import pytest
from pydantic import BaseModel

from app.services.answer import orchestrator as orch
from app.services.answer.planner import PlannedSlot, build_plan_model, layout_tree, to_rows
from app.services.answer.schemas import DataField, Dataset, LineView
from app.services.answer.skills import REGISTRY
from app.services.answer.skills import holdings as holdings_mod
from app.services.answer.skills.base import Skill, data_result, text_result
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
    assert period_return(prices, 7) == 10.0
    assert period_return(prices, 30) is None


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
