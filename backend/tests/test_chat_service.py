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


@pytest.fixture
def service(monkeypatch):
    svc = cs.ChatService.__new__(cs.ChatService)
    svc._tag_names = []
    svc._tools = {"get_price": FakePriceTool()}
    svc._build_prompt = lambda message, history: (message, [])
    from pydantic_ai import Agent
    svc.agent = Agent(FunctionModel(_scripted_model, stream_function=_scripted_stream),
                      tools=[t.as_agent_tool() for t in svc._tools.values()])
    return svc


@pytest.mark.asyncio
async def test_chat_stream_emits_steps_and_answer(service):
    events = [e async for e in service.chat_stream("종가 알려줘", [])]
    steps = [e["data"] for e in events if e["type"] == "step"]
    answers = [e["data"]["answer"] for e in events if e["type"] == "answer"]

    assert [s["code"] for s in steps] == ['get_price(code="069500")', 'get_price(code="229200", period=null)']
    assert json.loads(steps[1]["observations"])["period"] == "1d"  # null → forward 기본값
    assert all(s["error"] is None for s in steps)
    assert answers == ["| ETF | 종가 |\n|---|---|\n| 069500 | 35,000 |"]


@pytest.mark.asyncio
async def test_chat_collects_result(service):
    result = await service.chat("종가 알려줘", [])
    assert len(result["steps"]) == 2
    assert result["answer"].startswith("| ETF")
