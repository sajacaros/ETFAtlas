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
    assert cs.format_tool_call("get_etf_info", {"etf_code": "069500"}) == 'get_etf_info(etf_code="069500")'
    assert cs.format_tool_call("list_tags", {}) == "list_tags()"


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


class FakeMemory:
    def refine(self, question, context):
        return question if context.is_empty() else f"KODEX 200(069500)의 {question}"


@pytest.fixture
def service(monkeypatch):
    svc = cs.ChatService.__new__(cs.ChatService)
    svc._tag_names = []
    svc._tools = {"get_price": FakePriceTool()}
    svc._build_prompt = lambda question, context, original: (question, [])
    svc.memory = FakeMemory()
    from pydantic_ai import Agent
    svc.agent = Agent(FunctionModel(_scripted_model, stream_function=_scripted_stream),
                      tools=[t.as_agent_tool() for t in svc._tools.values()])
    return svc


@pytest.mark.asyncio
async def test_chat_stream_emits_steps_and_answer(service):
    events = [e async for e in service.chat_stream("종가 알려줘")]
    steps = [e["data"] for e in events if e["type"] == "step"]
    answers = [e["data"]["answer"] for e in events if e["type"] == "answer"]

    assert [s["code"] for s in steps] == ['get_price(code="069500")', 'get_price(code="229200", period=null)']
    assert json.loads(steps[1]["observations"])["period"] == "1d"  # null → forward 기본값
    assert all(s["error"] is None for s in steps)
    assert answers == ["| ETF | 종가 |\n|---|---|\n| 069500 | 35,000 |"]


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


@pytest.mark.asyncio
async def test_chat_stream_stop_before_agent_runs(service):
    stop = asyncio.Event()
    stop.set()
    events = [e async for e in service.chat_stream("종가 알려줘", stop=stop)]
    assert [e["type"] for e in events] == ["answer"]
    assert events[0]["data"]["answer"] == cs.STOPPED_ANSWER


@pytest.mark.asyncio
async def test_chat_collects_result(service):
    result = await service.chat("종가 알려줘")
    assert len(result["steps"]) == 2
    assert result["answer"].startswith("| ETF")
    assert result["refined_question"] == "종가 알려줘"


@pytest.mark.asyncio
async def test_chat_stream_refines_with_context(service):
    from app.services.chat_memory import ConversationContext, Turn
    context = ConversationContext(turns=[Turn("KODEX 200 정보 알려줘", "KODEX 200(069500)은 ...")])
    events = [e async for e in service.chat_stream("종가 알려줘", context)]
    assert events[0] == {"type": "refined_question", "data": {"question": "KODEX 200(069500)의 종가 알려줘"}}
    result = await service.chat("종가 알려줘", context)
    assert result["refined_question"] == "KODEX 200(069500)의 종가 알려줘"


@pytest.mark.parametrize("cypher", [
    "MATCH (n) RETURN n $$) as (r agtype); SELECT 1; --",
    "MATCH (n) RETURN n; DROP TABLE users",
])
def test_graph_query_rejects_sql_escape(cypher):
    # DB에 닿기 전에 거부되어야 한다 (db=None이라 실행되면 AttributeError)
    assert cs.GraphQueryTool(db=None).forward(cypher).startswith("오류:")


def test_execute_cypher_rejects_dollar_quote_in_params():
    from app.services.graph_service import GraphService
    with pytest.raises(ValueError):
        GraphService(db=None).execute_cypher(
            "MATCH (e:ETF {code: $code}) RETURN e", {"code": "x$$) as (r agtype); SELECT 1; --"},
        )


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
    assert _save_chat_log(db, 1, session, "그거 보수율은?", "KODEX 200의 보수율은?", "0.15%", steps) == 7
    log = db.added
    assert log.session_id == 3 and log.steps == steps
    assert log.generated_code == 'etf_search(query="KODEX 200")'  # 실패한 호출은 예시에서 뺀다
    assert log.refined_question == "KODEX 200의 보수율은?"
    assert session.updated_at is not None

    _save_chat_log(db, 1, session, "안녕", "안녕", "범위 밖", [])
    assert db.added.steps is None and db.added.refined_question is None
