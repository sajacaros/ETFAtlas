from types import SimpleNamespace

import pytest

from app.models.portfolio import CHAT_KEY_PREFIX, generate_chat_key
from app.services import chat_service as cs
from app.services.portfolio_chat import PortfolioCommand, can_access, parse_portfolio_command

# chat_stream 시나리오는 test_chat_service의 픽스처를 그대로 쓴다
from tests.test_chat_service import service  # noqa: F401


def test_generate_chat_key():
    key = generate_chat_key()
    assert key.startswith(CHAT_KEY_PREFIX) and len(key) == len(CHAT_KEY_PREFIX) + 10
    assert key[len(CHAT_KEY_PREFIX):].isalnum()
    assert generate_chat_key() != key


@pytest.mark.parametrize("message, expected", [
    ("/portfolio pf_abc 구성 종목을 정리해줘", PortfolioCommand("pf_abc", "구성 종목을 정리해줘")),
    ("  /portfolio pf_abc\n반도체 비중은?\n표로", PortfolioCommand("pf_abc", "반도체 비중은?\n표로")),
    ("/portfolio pf_abc", PortfolioCommand("pf_abc", "")),
    ("/portfolio", PortfolioCommand("", "")),
    ("KODEX 200 정보 /portfolio pf_abc", None),
    ("/portfolios pf_abc", None),
])
def test_parse_portfolio_command(message, expected):
    assert parse_portfolio_command(message) == expected


def test_can_access_owner_or_shared_only():
    mine = SimpleNamespace(user_id=1, is_shared=False)
    shared = SimpleNamespace(user_id=2, is_shared=True)
    private = SimpleNamespace(user_id=2, is_shared=False)
    assert can_access(mine, 1)
    assert can_access(shared, 1)
    assert not can_access(private, 1)  # 키를 알아도 남의 비공개 포트폴리오는 못 본다
    assert not can_access(shared, None)  # 로그인하지 않으면 공유 포트폴리오도 못 본다


@pytest.mark.asyncio
async def test_chat_stream_portfolio_command_without_key(service):
    events = [e async for e in service.chat_stream("/portfolio")]
    assert events == [{"type": "answer", "data": {"answer": cs.PORTFOLIO_USAGE_ANSWER}}]


@pytest.mark.asyncio
async def test_chat_stream_portfolio_command_denied(service, monkeypatch):
    seen = {}

    def find(db, user_id, key):
        seen.update(user_id=user_id, key=key)
        return None

    monkeypatch.setattr(cs, "find_accessible_portfolio", find)
    events = [e async for e in service.chat_stream("/portfolio pf_other 정리해줘")]
    assert seen == {"user_id": 1, "key": "pf_other"}
    assert [e["type"] for e in events] == ["answer"]  # 에이전트를 돌리지 않는다
    assert "pf_other" in events[0]["data"]["answer"]


@pytest.mark.asyncio
async def test_chat_stream_portfolio_command_attaches_portfolio(service, monkeypatch):
    portfolio = SimpleNamespace(name="연금", chat_key="pf_mine")
    monkeypatch.setattr(cs, "find_accessible_portfolio", lambda db, user_id, key: portfolio)
    calls = []

    def build_prompt(question, context, original, portfolio=None):
        calls.append((question, original, portfolio))
        return question, []

    service._build_prompt = build_prompt
    events = [e async for e in service.chat_stream("/portfolio pf_mine")]
    assert calls == [(cs.DEFAULT_PORTFOLIO_QUESTION, cs.DEFAULT_PORTFOLIO_QUESTION, portfolio)]
    assert events[-1]["type"] == "answer"

    from app.services.chat_memory import ConversationContext, Turn
    context = ConversationContext(turns=[Turn("KODEX 200 정보 알려줘", "...")])
    events = [e async for e in service.chat_stream("/portfolio pf_mine 종가 알려줘", context)]
    refined = [e["data"]["question"] for e in events if e["type"] == "refined_question"]
    # 재작성된 질문에도 명령을 남겨 다음 턴 맥락에서 키가 보이게 한다
    assert refined == ["/portfolio pf_mine KODEX 200(069500)의 종가 알려줘"]
    assert calls[-1][1] == "종가 알려줘"


def test_build_prompt_keeps_current_question_after_examples():
    svc = cs.ChatService.__new__(cs.ChatService)
    svc._embedding_service = SimpleNamespace(
        generalize_question=lambda q: q,
        find_similar_code_examples=lambda q, top_k: [{"question": "예시 질문", "code": "list_tags()"}],
    )
    from app.services.chat_memory import ConversationContext
    portfolio = SimpleNamespace(name="연금", chat_key="pf_mine")
    prompt, _ = svc._build_prompt("반도체 비중은?", ConversationContext(), "반도체 비중은?", portfolio)
    assert prompt.endswith("## 현재 질문 (이 질문의 조건만 따르세요):\n반도체 비중은?")
    assert 'get_portfolio(portfolio_key="pf_mine")' in prompt


def test_describe_portfolio_excludes_cash_and_untracked_etfs(monkeypatch):
    from app.services import portfolio_chat as pc

    holdings = {
        "069500": [{"stock_code": "005930", "stock_name": "삼성전자", "weight": 30.0, "recorded_at": "2026-10-06"}],
        "091160": [
            {"stock_code": "005930", "stock_name": "삼성전자", "weight": 20.0, "recorded_at": "2026-10-07"},
            {"stock_code": "000660", "stock_name": "SK하이닉스", "weight": 25.0, "recorded_at": "2026-10-07"},
        ],
    }
    monkeypatch.setattr(pc, "GraphService", lambda db: SimpleNamespace(get_etf_holdings_full=lambda code: holdings.get(code, [])))
    monkeypatch.setattr(pc, "PriceService", lambda db: SimpleNamespace(
        get_etf_names=lambda tickers: {"069500": "KODEX 200", "091160": "KODEX 반도체", "CASH": "현금"},
    ))
    portfolio = SimpleNamespace(name="연금", user_id=2, target_allocations=[
        SimpleNamespace(ticker="069500", target_weight=40),
        SimpleNamespace(ticker="091160", target_weight=40),
        SimpleNamespace(ticker="CASH", target_weight=10),
        SimpleNamespace(ticker="QQQ", target_weight=10),  # 구성종목을 관리하지 않는 해외 ETF
    ])

    data = pc.describe_portfolio(None, portfolio, user_id=1)

    assert data["kind"] == "공유 포트폴리오"
    assert [e["code"] for e in data["etfs"]] == ["069500", "091160", "CASH", "QQQ"]
    assert data["excluded_from_stocks"] == ["현금", "QQQ"]
    # 069500·091160을 50:50으로 환산: 삼성전자 = 15 + 10, SK하이닉스 = 12.5
    assert [(s["stock_name"], s["weight"]) for s in data["stocks"]] == [("삼성전자", 25.0), ("SK하이닉스", 12.5)]
    assert [e["code"] for e in data["stocks"][0]["via"]] == ["069500", "091160"]
    assert data["holdings_as_of"] == "2026-10-07"
