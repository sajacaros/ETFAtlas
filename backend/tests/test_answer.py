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


# --- 종목 스킬 / 해석기 ---

def test_resolver_strips_characters_that_could_break_the_query():
    from app.services.answer.resolver import _normalize
    assert _normalize("KODEX 미국S&P500(H)") == "kodex미국s&p500(h)"
    assert _normalize("x' OR 1=1 $$ ;\\") == "xor11"


class FakeStockResolver:
    def stock(self, db, name):
        return {"code": "005930", "name": "삼성전자"}


def test_stock_holders_ranks_etfs_by_weight(monkeypatch):
    from app.services.answer.skills import stock_holders as mod
    calls = []

    def fake_node(graph, cypher, params):
        calls.append(params)
        return [{"code": "448100", "name": "WON 200", "weight": 35.21, "expense_ratio": 0.05, "date": "2026-10-07"}]

    monkeypatch.setattr(mod, "node", fake_node)
    skill = REGISTRY["stock_holders"]
    result = skill.fetch(skill.Args(stock="삼성전자", top=5), "bar", None, FakeStockResolver())
    assert calls == [{"code": "005930", "top": 5}]
    assert result.content["view"] == {"kind": "bar", "x": "name", "y": ["weight"], "horizontal": True}
    assert "WON 200 35.21%" in result.summary


# --- 포트폴리오 합산 ---

class FakePortfolioResolver:
    ETFS = {"KODEX 200": {"code": "069500", "name": "KODEX 200"}, "KODEX 반도체": {"code": "091160", "name": "KODEX 반도체"}}
    STOCKS = {"삼성전자": {"code": "005930", "name": "삼성전자"}}

    def etf(self, db, name):
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

    unlisted = {"360750": {"code": "360750", "name": "TIGER 미국S&P500"}}
    monkeypatch.setattr(mod, "node", fake_node)
    monkeypatch.setattr(mod, "_unlisted_etf", lambda db, asset: unlisted.get(asset))
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
    from app.services.answer import resolver as resolver_mod
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
    return calls


def test_resolver_asks_instead_of_guessing_between_etfs(fake_etf_graph):
    from app.services.answer.resolver import AmbiguousETF, EntityResolver
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


def test_data_skill_turns_an_ambiguous_etf_into_a_question(fake_etf_graph):
    from app.services.answer.resolver import EntityResolver
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
    from app.services.answer.resolver import AmbiguousETF
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
