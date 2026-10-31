"""agent 스킬이 쓰는 tool-calling 에이전트. 다른 스킬로 표현할 수 없는 질문을 도구를 불러 가며 마크다운으로 답한다.

도구는 두 가지다. 여기서 정의한 검색·태그·유사 ETF·비중 변화·graph_query와, 답변 화면의 데이터 스킬 중
tool = True인 것(answer/tools.py가 만들어 넘긴다). 가격 추이·기간 수익률·ETF 비교처럼 스킬이 있는 일은
스킬 도구가 맡는다 — 같은 일을 하는 도구를 따로 두지 않는다.
이 모듈은 답변 화면(answer/)을 가져오지 않는다. agent 스킬이 이 모듈을 가져와 스킬 도구를 넣어 준다.
"""
import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence

from pydantic_ai import (
    Agent, AgentRunResultEvent, FunctionToolCallEvent, FunctionToolResultEvent, Tool as AgentTool,
)
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import RetryPromptPart
from pydantic_ai.usage import UsageLimits
from sqlalchemy.orm import Session

from ..domain.format import format_value
from ..models.chat import ChatLogResult
from .ai_config import AIConfig
from .chat_memory import ConversationContext
from .chat_prompt import SYSTEM_PROMPT
from .embedding_service import EmbeddingService
from .graph_service import GraphService
from .llm import build_model

logger = logging.getLogger(__name__)

# 도구 결과의 숫자 열 → 요약 텍스트와 같은 서식(domain.format). LLM이 단위를 헷갈리지 않게 '%'·'억원'을 붙여 넘긴다
FIELD_FORMATS = {
    **{k: "percent" for k in (
        "expense_ratio", "change_rate", "return_1d", "return_1w", "return_1m", "return_3m",
        "market_cap_change_1w", "similarity", "weight", "current_weight", "previous_weight", "weight_change",
    )},
    **{k: "krw" for k in ("market_cap", "net_assets", "latest_market_cap", "latest_net_assets", "trade_value")},
}


def format_fields(row: Dict[str, Any]) -> Dict[str, Any]:
    """숫자 열을 FIELD_FORMATS의 서식 문자열로 바꾼다 (숫자가 아니면 그대로). 1억원보다 작은 금액은 원 단위로."""
    for key, fmt in FIELD_FORMATS.items():
        value = row.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        row[key] = format_value(value, "price" if fmt == "krw" and abs(value) < 1_0000_0000 else fmt)
    return row


def _rows_json(rows: List[Dict[str, Any]]) -> str:
    return json.dumps([format_fields(r) for r in rows], ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Tools — name/description/inputs(JSON 스키마 속성) + forward()
# ---------------------------------------------------------------------------

class ChatTool:
    """챗봇 도구 베이스. inputs는 JSON 스키마 properties 형식, nullable=True면 선택 인자."""
    name: str = ""
    description: str = ""
    inputs: Dict[str, Dict[str, Any]] = {}

    def __init__(self):
        pass

    def forward(self, **kwargs) -> str:
        raise NotImplementedError

    def json_schema(self) -> Dict[str, Any]:
        properties = {
            k: {kk: vv for kk, vv in v.items() if kk != "nullable"}
            for k, v in self.inputs.items()
        }
        required = [k for k, v in self.inputs.items() if not v.get("nullable")]
        return {"type": "object", "properties": properties, "required": required}

    def as_agent_tool(self) -> AgentTool:
        def run(**kwargs) -> str:
            # 선택 인자에 null이 오면 forward 기본값 사용
            try:
                return self.forward(**{k: v for k, v in kwargs.items() if v is not None})
            except Exception:
                # DB 오류를 "결과 없음"으로 숨기지 않고, 에이전트 전체를 멈추지도 않는다
                logger.exception("Chat tool %s failed", self.name)
                return f"도구 실행 오류: {self.name} 조회에 실패했습니다. 같은 도구를 다시 부르지 말고 다른 방법을 쓰세요."

        # 도구들이 하나의 DB 세션을 공유하므로 병렬 실행하지 않는다
        return AgentTool.from_schema(
            run, name=self.name, description=self.description,
            json_schema=self.json_schema(), sequential=True,
        )


class ETFSearchTool(ChatTool):
    name = "etf_search"
    description = """ETF를 이름이나 코드로 검색합니다. ETF(KODEX, TIGER, ARIRANG 등 상장지수펀드) 전용이며, 주식 종목(삼성전자 등) 검색은 stock_search를 사용하세요.
예: 'KODEX' 검색 → KODEX가 포함된 ETF 목록 (code, name, expense_ratio)
사용자가 "다 찾아줘", "전부", "모두" 등 전체 결과를 요청하면 limit을 50으로 설정하세요."""
    inputs = {
        "query": {
            "type": "string",
            "description": "검색 키워드 (ETF 이름 또는 코드)"
        },
        "limit": {
            "type": "integer",
            "description": "최대 결과 수 (기본값 10, 전체 조회 시 50)",
            "nullable": True,
        }
    }

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, query: str, limit: int = 10) -> str:
        limit = max(1, min(limit, 50))
        graph_service = GraphService(self.db)
        cypher = f"""
        MATCH (e:ETF)
        WHERE toLower(e.name) CONTAINS toLower($query) OR e.code CONTAINS $query
        RETURN {{code: e.code, name: e.name, expense_ratio: e.expense_ratio}}
        ORDER BY e.name
        LIMIT {limit}
        """
        rows = graph_service.execute_cypher(cypher, {"query": query})
        if not rows:
            return "검색 결과 없음"
        return _rows_json([GraphService.parse_agtype(row["result"]) for row in rows])


class StockSearchTool(ChatTool):
    name = "stock_search"
    description = """주식 종목(삼성전자, SK하이닉스 등 개별 주식)을 이름이나 코드로 검색합니다. ETF 검색은 etf_search를 사용하세요.
예: '삼성전자' 검색 → code: '005930'. 찾은 코드를 graph_query 등에서 사용하세요 (분석 도구는 이름을 그대로 받습니다).
사용자가 "다 찾아줘", "전부", "모두" 등 전체 결과를 요청하면 limit을 50으로 설정하세요."""
    inputs = {
        "query": {
            "type": "string",
            "description": "검색 키워드 (종목 이름 또는 코드)"
        },
        "limit": {
            "type": "integer",
            "description": "최대 결과 수 (기본값 10, 전체 조회 시 50)",
            "nullable": True,
        }
    }

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, query: str, limit: int = 10) -> str:
        limit = max(1, min(limit, 50))
        graph_service = GraphService(self.db)
        cypher = f"""
        MATCH (s:Stock)
        WHERE toLower(s.name) CONTAINS toLower($query) OR s.code CONTAINS $query
        RETURN {{code: s.code, name: s.name}}
        ORDER BY s.name
        LIMIT {limit}
        """
        rows = graph_service.execute_cypher(cypher, {"query": query})
        if not rows:
            return "검색 결과 없음"
        return _rows_json([GraphService.parse_agtype(row["result"]) for row in rows])


class ListTagsTool(ChatTool):
    name = "list_tags"
    description = """그래프 DB에 등록된 모든 태그(테마) 목록과 각 태그에 속한 ETF 수를 조회합니다.
사용자가 특정 테마/섹터의 ETF를 질문할 때, 먼저 이 도구로 정확한 태그명을 확인하세요."""
    inputs = {}

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self) -> str:
        graph_service = GraphService(self.db)
        tags = graph_service.get_all_tags()
        if not tags:
            return "태그 없음"
        return _rows_json(tags)


class FindSimilarETFsTool(ChatTool):
    name = "find_similar_etfs"
    description = """특정 ETF와 보유종목이 유사한 ETF를 찾습니다. 보유종목 비중 겹침(overlap) 기반 유사도로 계산합니다.
etf_search로 ETF 코드를 먼저 확인한 후 사용하세요.
결과: etf_code, name, overlap(공통종목수), similarity(유사도 %)"""
    inputs = {
        "etf_code": {
            "type": "string",
            "description": "ETF 종목코드 (예: '069500')"
        }
    }

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, etf_code: str) -> str:
        graph_service = GraphService(self.db)
        results = graph_service.find_similar_etfs(etf_code)
        if not results:
            return "유사 ETF 없음"
        return _rows_json(results)


class GetHoldingsChangesTool(ChatTool):
    name = "get_holdings_changes"
    description = """ETF의 보유종목 비중 변화를 조회합니다. 전거래일/1주/1개월 전 대비 변동을 확인합니다.
내부적으로 두 시점의 보유종목을 비교하여 added(신규편입), removed(제외), increased(비중증가), decreased(비중감소)를 계산합니다.
etf_search로 ETF 코드를 먼저 확인한 후 사용하세요."""
    inputs = {
        "etf_code": {
            "type": "string",
            "description": "ETF 종목코드 (예: '069500')"
        },
        "period": {
            "type": "string",
            "description": "비교 기간: '1d'(전거래일), '1w'(1주), '1m'(1개월). 기본값 '1d'",
            "nullable": True,
        }
    }

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, etf_code: str, period: str = "1d") -> str:
        graph_service = GraphService(self.db)
        changes, _, _ = graph_service.get_etf_holdings_changes(etf_code, period)
        filtered = [c for c in changes if c["change_type"] != "unchanged"]
        if not filtered:
            return "변동 없음"
        return _rows_json(filtered)


class GraphQueryTool(ChatTool):
    name = "graph_query"
    description = """그래프 DB에 Cypher 쿼리를 직접 실행합니다. 다른 전용 도구로 해결할 수 없는 그래프 관계 질문에 사용하세요.
예: '삼성전자를 가장 많이 보유한 ETF', '반도체 태그 ETF 중 보수율 낮은 순', '삼성자산운용의 ETF 목록' 등

## 그래프 스키마
노드: ETF(code, name, expense_ratio, base_index, listed_date, description, dividend_cycle, dividend_yield, dividend_per_share, net_assets, close_price, return_1d, return_1w, return_1m, market_cap_change_1w, updated_at), Stock(code, name, is_etf, listed_shares(상장주식수), kis_per, kis_eps, kis_pbr(KIS 제공, quote_date 종가 기준), quote_date), Company(name), Tag(name), Price(date, open, high, low, close, volume, nav, market_cap, net_assets, trade_value, change_rate), User(user_id)
관계: (ETF)-[:CURRENT_HOLDS {date, weight, shares}]->(Stock) = 현재 구성종목(ETF당 비중 상위 30개), (ETF)-[:HOLDS {date, weight, shares}]->(Stock) = 날짜별 구성종목 이력(비중 변화 비교에만 사용), (ETF)-[:MANAGED_BY]->(Company), (ETF)-[:TAGGED]->(Tag), (ETF)-[:HAS_PRICE]->(Price), (Stock)-[:HAS_PRICE]->(Price), (User)-[:WATCHES {added_at}]->(ETF)

## Cypher 작성 규칙
1. MATCH로 시작하는 읽기 전용 쿼리만 가능 (CREATE/MERGE/DELETE/SET 불가, '$$'와 ';' 사용 불가)
2. RETURN은 반드시 단일 맵으로 감싸세요: RETURN {key1: val1, key2: val2}
3. 문자열 값은 작은따옴표: {code: '005930'}
4. 집계 함수와 ORDER BY를 함께 쓸 때 WITH 절로 분리하세요
5. weight, expense_ratio, dividend_yield, return_*, net_assets는 숫자로 저장되어 있습니다(비중·보수율·수익률은 % 단위, 순자산은 원). 결과에 '%'나 '억원'이 붙어 보이는 건 표시용 서식이니, 조건은 숫자로 쓰세요 (예: h.weight >= 10, e.expense_ratio <= 0.1)
6. dividend_cycle은 분배 주기 개월 수입니다 (1=월배당, 3=분기배당, 0=분배 없음(TR)). 월배당 ETF는 e.dividend_cycle = 1. dividend_yield는 최근 12개월 분배율(%, 12개월 분배금 ÷ 현재가), dividend_per_share는 최근 12개월 주당 분배금(원)입니다. '배당 5% 이상'은 e.dividend_yield >= 5
7. CURRENT_HOLDS는 ETF당 비중 상위 30개뿐이라, 엣지가 없으면 미보유이거나 30위 밖(사실상 0)입니다. 특정 종목 비중이 '낮은/적은' ETF는 후보 ETF(태그 등)에서 MATCH로 출발하고 종목은 OPTIONAL MATCH + coalesce(sum(h.weight), 0)로 붙이세요. MATCH로 붙이면 미보유 ETF가 결과에서 빠집니다

## 쿼리 패턴 예시

ETF의 현재 보유종목 (현재 구성종목은 항상 CURRENT_HOLDS 사용):
MATCH (e:ETF {code: '069500'})-[h:CURRENT_HOLDS]->(s:Stock)
RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight}
ORDER BY h.weight DESC LIMIT 10

특정 종목을 보유한 ETF:
MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: '삼성전자'})
RETURN {etf_code: e.code, etf_name: e.name, weight: h.weight}
ORDER BY h.weight DESC

특정 종목의 ETF 내 비중 이력 (HOLDS는 이력 비교에만):
MATCH (e:ETF {code: '069500'})-[h:HOLDS]->(s:Stock {name: '삼성전자'})
RETURN {date: h.date, weight: h.weight} ORDER BY h.date

태그별 ETF 조회:
MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '반도체'})
RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio}

운용사별 ETF:
MATCH (e:ETF)-[:MANAGED_BY]->(c:Company)
WHERE c.name CONTAINS '삼성'
RETURN {code: e.code, name: e.name, company: c.name}"""
    inputs = {
        "cypher": {
            "type": "string",
            "description": "실행할 Cypher 쿼리 (MATCH로 시작, RETURN은 단일 맵으로 감싸기)"
        }
    }

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, cypher: str) -> str:
        # 쓰기 차단은 읽기 전용 트랜잭션이 맡는다 (키워드 필터는 우회 가능해서 쓰지 않는다)
        try:
            rows = GraphService(self.db).execute_cypher_readonly(cypher)
        except ValueError as e:
            return f"오류: {e}"
        except Exception as e:
            cause = getattr(e, "pgerror", None) or str(e)
            if "read-only transaction" in cause:
                return "오류: 읽기 전용 쿼리만 허용됩니다 (MATCH ... RETURN 형태로 작성하세요)"
            if "statement timeout" in cause:
                return "오류: 쿼리 실행 시간(10초)을 넘었습니다. 조건을 좁히거나 LIMIT을 쓰세요"
            return "쿼리 오류: " + cause.strip().splitlines()[0][:300]
        if not rows:
            return "조회 결과 없음"
        return _rows_json([GraphService.parse_agtype(row["result"]) for row in rows])


# ---------------------------------------------------------------------------
# ChatService
# ---------------------------------------------------------------------------

MAX_MODEL_REQUESTS = 15
OBSERVATION_CHARS = 2000  # step 이벤트에 싣는 도구 결과 길이 (실행 과정 패널·로그용, 모델에는 전부 간다)
ERROR_CHARS = 500
FALLBACK_ANSWER = "죄송합니다. 답변 생성에 실패했습니다. 다시 질문해 주세요."
STOPPED_ANSWER = "요청하신 대로 중지했습니다. 지금까지 실행한 단계는 '실행 과정'에서 확인할 수 있어요."
EXAMPLES_TOP_K = 3
_CALL_RE = re.compile(r"^\s*(\w+)\(", re.M)


def format_tool_call(name: str, args: Dict[str, Any]) -> str:
    """도구 호출을 `name(key="value", ...)` 표기로 직렬화 (few-shot 예시/로그 공용 포맷)."""
    params = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())
    return f"{name}({params})"


def _step_call(step_number: int, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """step 이벤트 중 호출 시점에 정해지는 부분 (step_start와 step이 공유)."""
    return {
        "step_number": step_number,
        "code": format_tool_call(name, args),
        "tool_calls": [{"name": name, "arguments": json.dumps(args, ensure_ascii=False)}],
    }


def _analysis_tools_prompt(names: Sequence[str]) -> str:
    """답변 화면의 스킬 도구 — 화면과 같은 계산을 텍스트로 돌려준다 (answer/tools.py)."""
    return ("## 분석 도구\n"
            f"{', '.join(names)}: 답변 화면과 같은 계산으로 요약 텍스트를 돌려줍니다. "
            "종목·ETF는 이름이나 6자리 코드를 그대로 넣으세요 (stock_search·etf_search를 먼저 부르지 않아도 됩니다). "
            "결과의 숫자와 날짜를 그대로 옮기고, 결과에 없는 수치는 만들지 마세요.")


def usable_examples(examples: List[Dict[str, Any]], tool_names: Sequence[str]) -> List[Dict[str, Any]]:
    """지금 없는 도구를 부르는 해결 절차 예시는 뺀다 (도구를 스킬로 옮기기 전에 쌓인 예시가 없는 도구를 부르게 한다)."""
    known = set(tool_names)
    usable = [ex for ex in examples if set(_CALL_RE.findall(ex.get("code") or "")) <= known]
    if len(usable) < len(examples):
        logger.info("Skipped code examples calling removed tools: %s",
                    [ex.get("id") for ex in examples if ex not in usable])
    return usable


class ChatService:
    def __init__(self, db: Session, config: AIConfig, skill_tools: Sequence[AgentTool] = ()):
        """skill_tools: 답변 화면의 스킬 도구 (agent 스킬이 answer/tools.skill_tools로 만들어 넘긴다)."""
        self.db = db
        self._tag_names = self._load_tag_names()
        self._embedding_service = EmbeddingService(db, config)
        self._tools = self._create_tools()
        self._skill_tools = list(skill_tools)
        self.agent = Agent(
            build_model(config),
            instructions=self._instructions(),
            tools=[t.as_agent_tool() for t in self._tools.values()] + self._skill_tools,
        )

    def _load_tag_names(self) -> List[str]:
        """그래프 DB에서 태그 목록을 미리 로드한다."""
        try:
            graph_service = GraphService(self.db)
            tags = graph_service.get_all_tags()
            return [t["name"] for t in tags] if tags else []
        except Exception:
            return []

    def _create_tools(self) -> Dict[str, ChatTool]:
        """도구 인스턴스를 생성하고 이름→도구 딕셔너리로 반환한다."""
        tools = [
            ETFSearchTool(db=self.db),
            StockSearchTool(db=self.db),
            ListTagsTool(db=self.db),
            FindSimilarETFsTool(db=self.db),
            GetHoldingsChangesTool(db=self.db),
            GraphQueryTool(db=self.db),
        ]
        return {t.name: t for t in tools}

    def tool_names(self) -> List[str]:
        return [*self._tools, *(t.name for t in self._skill_tools)]

    def _instructions(self) -> str:
        parts = [SYSTEM_PROMPT]
        if self._skill_tools:
            parts.append(_analysis_tools_prompt([t.name for t in self._skill_tools]))
        if self._tag_names:
            parts.append(f"## 사용 가능한 태그 목록\n{', '.join(self._tag_names)}")
        return "\n\n".join(parts)

    def _build_prompt(self, question: str, context: ConversationContext) -> tuple:
        """사용자 프롬프트(참고 예시 + 대화 맥락 + 현재 질문)와 매칭된 예시를 반환한다.

        question은 답변 화면이 맥락으로 재작성한 독립 질문이다.
        """
        parts = []
        # 예시는 일반화된 질문으로 임베딩되어 있으므로 검색 질의도 같은 방식으로 일반화한다
        search_query = self._embedding_service.generalize_question(question)
        code_examples = usable_examples(
            self._embedding_service.find_similar_code_examples(search_query, top_k=EXAMPLES_TOP_K), self.tool_names())
        if code_examples:
            parts.append("## 참고 해결 절차 예시")
            parts.append("비슷한 유형의 질문을 해결한 도구 호출 순서입니다. "
                         "<종목명>, <ETF명>, <운용사> 같은 자리표시자는 현재 질문의 값으로 바꾸고, "
                         "<…의 code>는 앞 호출 결과의 값을 쓰세요. 쿼리 구조(특히 Cypher)는 그대로 따르세요:")
            for ex in code_examples:
                example_question = ex.get("question_generalized") or ex["question"]
                parts.append(f"Q: {example_question}\n```\n{ex['code']}\n```")
            parts.append("")
        if not context.is_empty():
            parts.append("## 이전 대화 (참고용)")
            parts.append("아래는 이전 대화 내용입니다. 맥락 파악에만 참고하세요.")
            parts.append("현재 질문은 이미 맥락을 반영해 다시 쓴 것이니, 이전 대화의 조건(개수, 필터 등)을 덧붙이지 마세요.")
            parts.append(context.render())
            parts.append("")
        parts.append(f"## 현재 질문 (이 질문의 조건만 따르세요):\n{question}")
        return "\n".join(parts), code_examples

    async def chat_stream(
        self, question: str, context: Optional[ConversationContext] = None, stop: Optional[asyncio.Event] = None,
    ) -> AsyncIterator[Dict]:
        """도구 호출을 step_start로, 그 결과를 step 이벤트로, 최종 응답을 answer 이벤트로 스트리밍한다.

        question은 이미 맥락으로 재작성된 질문이다 (재작성은 답변 화면 오케스트레이터가 한다).
        step_start: {step_number, code(도구 호출 표기), tool_calls}
        step: step_start 필드 + {observations, error}
        status: {stage} — 도구 실행 전 준비 단계(searching_examples → thinking)를 알린다
        answer: {answer, result} — result가 failed면 answer는 안내 문구다 (도구 결과를 답으로 내지 않는다)
        stop이 설정되면 실행 중인 도구는 결과까지 기다리고, 다음 모델 요청/도구 호출 전에 멈춘다.
        """
        stop = stop or asyncio.Event()
        context = context or ConversationContext()
        # 임베딩·예시 검색(동기 HTTP/DB)은 이벤트 루프를 막지 않도록 스레드에서 실행
        yield {"type": "status", "data": {"stage": "searching_examples"}}
        prompt, matched_examples = await asyncio.to_thread(self._build_prompt, question, context)
        if matched_examples:
            yield {"type": "matched_examples", "data": {"examples": matched_examples}}

        pending: Dict[str, Dict[str, Any]] = {}
        step_number = 0
        answer = None
        if stop.is_set():
            yield {"type": "answer", "data": {"answer": STOPPED_ANSWER, "result": ChatLogResult.CANCELLED.value}}
            return
        yield {"type": "status", "data": {"stage": "thinking"}}
        try:
            async with self.agent.run_stream_events(
                prompt, usage_limits=UsageLimits(request_limit=MAX_MODEL_REQUESTS),
            ) as stream:
                async for event in stream:
                    if isinstance(event, FunctionToolCallEvent):
                        if stop.is_set() and not pending:
                            break  # 중지 요청 뒤의 새 도구 호출은 실행하지 않는다
                        # 실행 전에 무엇을 하는지 먼저 알리고, 결과는 같은 step_number의 step 이벤트로 채운다
                        part = event.part
                        step_number += 1
                        call = _step_call(step_number, part.tool_name, part.args_as_dict())
                        pending[part.tool_call_id] = call
                        yield {"type": "step_start", "data": call}
                    elif isinstance(event, FunctionToolResultEvent):
                        call = pending.pop(event.tool_call_id, None)
                        if call is None:
                            step_number += 1
                            call = _step_call(step_number, "unknown", {})
                        is_error = isinstance(event.part, RetryPromptPart)
                        content = event.part.model_response() if is_error else str(event.part.content)
                        yield {
                            "type": "step",
                            "data": {
                                **call,
                                "observations": content[:OBSERVATION_CHARS],
                                "error": content[:ERROR_CHARS] if is_error else None,
                            },
                        }
                        if stop.is_set() and not pending:
                            break  # 실행 중이던 도구가 모두 끝났으니 다음 모델 요청 전에 멈춘다
                    elif isinstance(event, AgentRunResultEvent):
                        answer = str(event.result.output).strip()
        except UsageLimitExceeded:
            logger.warning("Chat agent hit request limit (%d)", MAX_MODEL_REQUESTS)
        except Exception:
            logger.exception("Chat agent failed")

        # 답을 쓰지 못하고 끝났으면(한도 초과·오류) 실패다. 마지막 도구 결과(원시 JSON)를 답으로 내지 않는다
        if stop.is_set():
            result, answer = ChatLogResult.CANCELLED, answer or STOPPED_ANSWER
        elif answer:
            result = ChatLogResult.COMPLETED
        else:
            result, answer = ChatLogResult.FAILED, FALLBACK_ANSWER
        yield {"type": "answer", "data": {"answer": answer, "result": result.value}}
