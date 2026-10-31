import asyncio
import json

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from app.services import chat_service as cs


class FakePriceTool(cs.ChatTool):
    name = "get_price"
    description = "ETF 종가"
    inputs = {
        "code": {"type": "string", "description": "ETF 코드"},
        "period": {"type": "string", "description": "기간", "nullable": True},
    }

    def forward(self, code: str, period: str = "1d") -> str:
        return json.dumps({"code": code, "period": period, "close": 35000})


def test_json_schema_marks_nullable_optional():
    schema = FakePriceTool().json_schema()
    assert schema["required"] == ["code"]
    assert "nullable" not in schema["properties"]["period"]


def test_format_tool_call():
    assert cs.format_tool_call("holdings", {"etf": "069500"}) == 'holdings(etf="069500")'
    assert cs.format_tool_call("list_tags", {}) == "list_tags()"


def test_tool_results_use_the_summary_formats():
    """남은 도구도 요약 텍스트와 같은 서식(domain.format)으로 숫자를 넘긴다."""
    row = cs.format_fields({"code": "069500", "expense_ratio": 0.15, "net_assets": 12_3456_0000_0000,
                            "trade_value": 5_000_000, "weight": "12.3", "similarity": None, "name": "KODEX 200"})
    assert row == {"code": "069500", "expense_ratio": "0.15%", "net_assets": "12조 3,456억원",
                   "trade_value": "5,000,000원", "weight": "12.30%", "similarity": None, "name": "KODEX 200"}


def test_examples_calling_removed_tools_are_skipped():
    examples = [{"id": 1, "code": 'etf_search(query="<ETF명>")\nholdings(etf="<ETF의 code>")'},
                {"id": 2, "code": 'etf_search(query="<ETF명>")\nget_etf_info(etf_code="<ETF의 code>")'}]
    assert [ex["id"] for ex in cs.usable_examples(examples, ["etf_search", "holdings"])] == [1]


def _scripted_model(messages, info: AgentInfo) -> ModelResponse:
    # 1턴: 도구 두 개 병렬 호출, 2턴: 최종 답변
    if not any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
        return ModelResponse(parts=[
            ToolCallPart("get_price", {"code": "069500"}, tool_call_id="c1"),
            ToolCallPart("get_price", {"code": "229200", "period": None}, tool_call_id="c2"),
        ])
    return ModelResponse(parts=[TextPart("| ETF | 종가 |\n|---|---|\n| 069500 | 35,000 |")])


async def _scripted_stream(messages, info: AgentInfo):
    response = _scripted_model(messages, info)
    if isinstance(response.parts[0], TextPart):
        yield response.parts[0].content
        return
    yield {
        i: DeltaToolCall(name=p.tool_name, json_args=json.dumps(p.args), tool_call_id=p.tool_call_id)
        for i, p in enumerate(response.parts)
    }


def _service(model, stream):
    svc = cs.ChatService.__new__(cs.ChatService)
    svc._tag_names = []
    svc._tools = {"get_price": FakePriceTool()}
    svc._skill_tools = []
    svc._build_prompt = lambda question, context: (question, [])
    from pydantic_ai import Agent
    svc.agent = Agent(FunctionModel(model, stream_function=stream), tools=[t.as_agent_tool() for t in svc._tools.values()])
    return svc


@pytest.fixture
def service():
    return _service(_scripted_model, _scripted_stream)


@pytest.mark.asyncio
async def test_chat_stream_emits_steps_and_answer(service):
    events = [e async for e in service.chat_stream("종가 알려줘")]
    steps = [e["data"] for e in events if e["type"] == "step"]
    answers = [e["data"]["answer"] for e in events if e["type"] == "answer"]

    assert [s["code"] for s in steps] == ['get_price(code="069500")', 'get_price(code="229200", period=null)']
    assert json.loads(steps[1]["observations"])["period"] == "1d"  # null → forward 기본값
    assert all(s["error"] is None for s in steps)
    assert answers == ["| ETF | 종가 |\n|---|---|\n| 069500 | 35,000 |"]
    assert events[-1]["data"]["result"] == "completed"


@pytest.mark.asyncio
async def test_chat_stream_announces_step_before_result(service):
    events = [e for e in [e async for e in service.chat_stream("종가 알려줘")] if e["type"] in ("step_start", "step")]
    for n in (1, 2):
        kinds = [e["type"] for e in events if e["data"]["step_number"] == n]
        assert kinds == ["step_start", "step"]
    starts = {e["data"]["step_number"]: e["data"] for e in events if e["type"] == "step_start"}
    for e in events:
        if e["type"] == "step":
            assert e["data"]["code"] == starts[e["data"]["step_number"]]["code"]
    assert "observations" not in starts[1]


@pytest.mark.asyncio
async def test_chat_stream_stop_waits_for_running_tools(service):
    stop = asyncio.Event()
    tool = service._tools["get_price"]
    original = tool.forward

    def forward_then_stop(**kwargs):
        stop.set()  # 첫 도구가 실행되는 도중 중지 요청
        return original(**kwargs)

    tool.forward = forward_then_stop
    events = [e async for e in service.chat_stream("종가 알려줘", stop=stop)]
    steps = [e["data"] for e in events if e["type"] == "step"]
    answers = [e["data"]["answer"] for e in events if e["type"] == "answer"]

    assert [s["step_number"] for s in steps] == [1, 2]  # 같이 실행 중이던 도구는 결과까지 받는다
    assert all(s["error"] is None for s in steps)
    assert answers == [cs.STOPPED_ANSWER]  # 다음 모델 요청(최종 답변)은 쓰지 않는다
    assert events[-1]["data"]["result"] == "cancelled"


@pytest.mark.asyncio
async def test_chat_stream_stop_before_agent_runs(service):
    stop = asyncio.Event()
    stop.set()
    events = [e async for e in service.chat_stream("종가 알려줘", stop=stop)]
    assert [e["type"] for e in events] == ["status", "answer"]  # 예시 검색까지만 하고 에이전트는 돌리지 않는다
    assert events[-1]["data"] == {"answer": cs.STOPPED_ANSWER, "result": "cancelled"}


@pytest.mark.asyncio
async def test_chat_stream_reports_stages(service):
    # 질문은 답변 화면이 이미 재작성해 넘긴다 — 맥락이 있어도 재작성 단계가 없다
    from app.services.chat_memory import ConversationContext, Turn
    context = ConversationContext(turns=[Turn("KODEX 200 정보 알려줘", "KODEX 200(069500)은 ...")])
    stages = [e["data"]["stage"] async for e in service.chat_stream("종가 알려줘", context) if e["type"] == "status"]
    assert stages == ["searching_examples", "thinking"]
    assert not [e async for e in service.chat_stream("종가 알려줘", context) if e["type"] == "refined_question"]


def _always_calls_tool(messages, info):
    return ModelResponse(parts=[ToolCallPart("get_price", {"code": "069500"}, tool_call_id=f"c{len(messages)}")])


async def _always_calls_tool_stream(messages, info):
    yield {0: DeltaToolCall(name="get_price", json_args='{"code": "069500"}', tool_call_id=f"c{len(messages)}")}


@pytest.mark.asyncio
async def test_chat_stream_fails_without_dumping_tool_results_when_the_limit_is_hit(monkeypatch):
    """요청 한도를 넘기면 실패로 마치고, 마지막 도구 결과(원시 JSON)를 답으로 내지 않는다."""
    monkeypatch.setattr(cs, "MAX_MODEL_REQUESTS", 2)
    svc = _service(_always_calls_tool, _always_calls_tool_stream)
    events = [e async for e in svc.chat_stream("종가 알려줘")]
    assert any(e["type"] == "step" for e in events)
    assert events[-1]["data"] == {"answer": cs.FALLBACK_ANSWER, "result": "failed"}


@pytest.mark.asyncio
async def test_chat_stream_fails_when_the_model_errors():
    def broken(messages, info):
        raise RuntimeError("LLM down")

    async def broken_stream(messages, info):
        raise RuntimeError("LLM down")
        yield ""  # pragma: no cover

    events = [e async for e in _service(broken, broken_stream).chat_stream("종가 알려줘")]
    assert events[-1]["data"] == {"answer": cs.FALLBACK_ANSWER, "result": "failed"}


def test_agent_skill_judges_failure_by_the_result(monkeypatch):
    """agent 스킬은 답 문구가 아니라 에이전트가 낸 result로 실패를 본다. 스킬 도구는 이 답변의 레지스트리에서 만든다."""
    from app.services.answer.skills import REGISTRY, agent as agent_mod
    from app.services.answer.skills.base import SkillContext
    from app.services.chat_memory import ConversationContext
    from app.services.entities import EntityResolver
    built = {}

    class FakeService:
        def __init__(self, db, config, tools):
            built["tools"] = [t.name for t in tools]

        async def chat_stream(self, question, context, stop):
            yield {"type": "step", "data": {"step_number": 1}}
            yield {"type": "answer", "data": FakeService.answer}

    class DB:
        def close(self):
            pass

    monkeypatch.setattr(agent_mod, "ChatService", FakeService)

    def run(answer):
        FakeService.answer = answer
        ctx = SkillContext(question="q", conversation=ConversationContext(), session_factory=DB, resolver=EntityResolver(),
                           ai_config=None, stop=asyncio.Event(), registry=REGISTRY)
        skill = REGISTRY["agent"]

        async def go():
            return [e async for e in skill.run(skill.Args(question="q"), "markdown", ctx)]
        return asyncio.run(go())

    events = run({"answer": "| 표 |", "result": "completed"})
    assert events[0]["type"] == "step" and events[-1]["status"] == "complete"
    assert "holdings" in built["tools"] and "rank" in built["tools"] and "narrative" not in built["tools"]
    assert run({"answer": cs.FALLBACK_ANSWER, "result": "failed"})[-1]["status"] == "failed"
    assert run({"answer": cs.STOPPED_ANSWER, "result": "cancelled"})[-1]["status"] == "complete"  # 중지는 그 문구를 보여 준다


@pytest.mark.asyncio
async def test_with_heartbeat_pings_while_idle():
    from app.utils.sse import with_heartbeat as _with_heartbeat

    async def slow():
        yield "data: 1\n\n"
        await asyncio.sleep(0.05)
        yield "data: 2\n\n"

    chunks = [c async for c in _with_heartbeat(slow(), interval=0.02)]
    assert chunks[0] == "data: 1\n\n" and chunks[-1] == "data: 2\n\n"
    assert ": ping\n\n" in chunks[1:-1]


@pytest.mark.asyncio
async def test_with_heartbeat_raises_producer_error():
    from app.utils.sse import with_heartbeat as _with_heartbeat

    async def broken():
        yield "data: 1\n\n"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        [c async for c in _with_heartbeat(broken(), interval=1)]


@pytest.mark.parametrize("cypher", [
    "MATCH (n) RETURN n $$) as (r agtype); SELECT 1; --",
    "MATCH (n) RETURN n; DROP TABLE users",
])
def test_graph_query_rejects_sql_escape(cypher):
    # DB에 닿기 전에 거부되어야 한다 (db=None이라 실행되면 AttributeError)
    assert cs.GraphQueryTool(db=None).forward(cypher).startswith("오류:")


def test_save_chat_log_keeps_steps_and_refined_question():
    from types import SimpleNamespace
    from app.routers.chat import _save_chat_log

    class FakeDB:
        def add(self, obj): self.added = obj
        def commit(self): pass
        def refresh(self, obj): obj.id = 7

    db, session = FakeDB(), SimpleNamespace(id=3, updated_at=None)
    steps = [
        {"step_number": 1, "code": 'etf_search(query="KODEX 200")', "error": None},
        {"step_number": 2, "code": "get_etf_info()", "error": "etf_code 누락"},
    ]
    assert _save_chat_log(db, 1, session, "그거 보수율은?", "KODEX 200의 보수율은?", "0.15%", steps, "completed") == 7
    log = db.added
    assert log.session_id == 3 and log.steps == steps and log.result == "completed"
    assert log.generated_code == 'etf_search(query="KODEX 200")'  # 실패한 호출은 예시에서 뺀다
    assert log.refined_question == "KODEX 200의 보수율은?"
    assert session.updated_at is not None

    _save_chat_log(db, 1, session, "안녕", "안녕", "범위 밖", [], "completed")
    assert db.added.steps is None and db.added.refined_question is None
