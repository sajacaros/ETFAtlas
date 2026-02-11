import json
from typing import List, Dict
from sqlalchemy.orm import Session
from smolagents import Tool, CodeAgent, LiteLLMModel
from ..config import get_settings
from .graph_service import GraphService
from .etf_service import ETFService


class CypherQueryTool(Tool):
    name = "cypher_query"
    description = """Apache AGE 그래프 데이터베이스에서 Cypher 쿼리를 실행합니다.

## 그래프 스키마

### 노드
- ETF: code(종목코드), name(ETF명), expense_ratio(보수율), updated_at
- Stock: code(종목코드), name(종목명), is_etf(ETF여부)
- Company: name(회사명, 운용사)
- Sector: name(섹터명)
- Market: name(시장명)
- Tag: name(태그명)

### 관계
- (ETF)-[:HOLDS {date, weight, shares}]->(Stock) : ETF가 종목 보유
- (ETF)-[:MANAGED_BY]->(Company) : ETF 운용사
- (Stock)-[:BELONGS_TO]->(Sector) : 종목의 섹터
- (Stock)-[:PART_OF]->(Market) : 종목의 시장
- (ETF)-[:TAGGED]->(Tag) : ETF의 태그/테마
- (ETF)-[:HAS_CHANGE {date, change_type}]->(Stock) : 보유 변동

## 중요 규칙
1. RETURN은 반드시 단일 맵으로 반환: `RETURN {key1: val1, key2: val2}`
2. 노드/관계 라벨의 콜론(:ETF, [:HOLDS])은 자동 이스케이프되므로 그대로 사용
3. 파라미터($param)는 사용하지 말고, 값을 직접 쿼리에 포함
4. 문자열 값은 작은따옴표로 감싸기: {code: '005930'}
5. 최신 보유 정보를 조회할 때는 date 기준 내림차순 정렬 후 head(collect(h))로 최신 것만 사용

## 쿼리 예시
- 특정 종목을 보유한 ETF 조회:
  MATCH (e:ETF)-[h:HOLDS]->(s:Stock {code: '005930'})
  WITH e, h ORDER BY h.date DESC
  WITH e, head(collect(h)) as latest
  RETURN {etf_code: e.code, etf_name: e.name, weight: latest.weight}
  ORDER BY latest.weight DESC

- 특정 태그의 ETF 조회:
  MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '반도체'})
  RETURN {code: e.code, name: e.name}

- 특정 ETF의 상위 보유종목 조회:
  MATCH (e:ETF {code: '069500'})-[h:HOLDS]->(s:Stock)
  WITH s, h ORDER BY h.date DESC
  WITH s, head(collect(h)) as latest
  RETURN {stock_code: s.code, stock_name: s.name, weight: latest.weight}
  ORDER BY latest.weight DESC
  LIMIT 10
"""
    inputs = {
        "query": {
            "type": "string",
            "description": "실행할 Cypher 쿼리"
        }
    }
    output_type = "string"

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, query: str) -> str:
        graph_service = GraphService(self.db)
        rows = graph_service.execute_cypher(query)
        if not rows:
            return "결과 없음"
        results = []
        for row in rows:
            parsed = GraphService.parse_agtype(row.get("result", ""))
            results.append(parsed)
        return json.dumps(results, ensure_ascii=False, default=str)


class ETFSearchTool(Tool):
    name = "etf_search"
    description = """그래프 DB에서 ETF를 이름이나 코드로 검색합니다. ETF 코드를 모를 때 이름으로 검색하여 코드를 찾을 수 있습니다.
예: 'KODEX' 검색 → KODEX가 포함된 ETF 목록 (code, name, expense_ratio)"""
    inputs = {
        "query": {
            "type": "string",
            "description": "검색 키워드 (ETF 이름 또는 코드)"
        }
    }
    output_type = "string"

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, query: str) -> str:
        graph_service = GraphService(self.db)
        lower_query = query.lower()
        cypher = f"""
        MATCH (e:ETF)
        WHERE toLower(e.name) CONTAINS '{lower_query}' OR e.code CONTAINS '{query}'
        RETURN {{code: e.code, name: e.name, expense_ratio: e.expense_ratio}}
        ORDER BY e.name
        LIMIT 10
        """
        rows = graph_service.execute_cypher(cypher)
        if not rows:
            return "검색 결과 없음"
        results = [GraphService.parse_agtype(row["result"]) for row in rows]
        return json.dumps(results, ensure_ascii=False, default=str)


class StockSearchTool(Tool):
    name = "stock_search"
    description = """그래프 DB에서 종목(주식)을 이름이나 코드로 검색합니다. 종목코드를 모를 때 이름으로 검색하여 코드를 찾을 수 있습니다.
예: '삼성전자' 검색 → code: '005930'. 찾은 코드를 cypher_query에서 사용하세요."""
    inputs = {
        "query": {
            "type": "string",
            "description": "검색 키워드 (종목 이름 또는 코드)"
        }
    }
    output_type = "string"

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, query: str) -> str:
        graph_service = GraphService(self.db)
        lower_query = query.lower()
        cypher = f"""
        MATCH (s:Stock)
        WHERE toLower(s.name) CONTAINS '{lower_query}' OR s.code CONTAINS '{query}'
        RETURN {{code: s.code, name: s.name}}
        ORDER BY s.name
        LIMIT 10
        """
        rows = graph_service.execute_cypher(cypher)
        if not rows:
            return "검색 결과 없음"
        results = [GraphService.parse_agtype(row["result"]) for row in rows]
        return json.dumps(results, ensure_ascii=False, default=str)


class ListTagsTool(Tool):
    name = "list_tags"
    description = """그래프 DB에 등록된 모든 태그(테마) 목록과 각 태그에 속한 ETF 수를 조회합니다.
사용자가 특정 테마/섹터의 ETF를 질문할 때, 먼저 이 도구로 정확한 태그명을 확인한 후 cypher_query에서 사용하세요."""
    inputs = {}
    output_type = "string"

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self) -> str:
        graph_service = GraphService(self.db)
        tags = graph_service.get_all_tags()
        if not tags:
            return "태그 없음"
        return json.dumps(tags, ensure_ascii=False, default=str)


class FindSimilarETFsTool(Tool):
    name = "find_similar_etfs"
    description = """특정 ETF와 보유종목이 유사한 ETF를 찾습니다. TF-IDF 가중 유사도로 계산합니다.
etf_search로 ETF 코드를 먼저 확인한 후 사용하세요.
결과: etf_code, name, overlap(공통종목수), similarity(유사도 %)"""
    inputs = {
        "etf_code": {
            "type": "string",
            "description": "ETF 종목코드 (예: '069500')"
        }
    }
    output_type = "string"

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, etf_code: str) -> str:
        graph_service = GraphService(self.db)
        results = graph_service.find_similar_etfs(etf_code)
        if not results:
            return "유사 ETF 없음"
        return json.dumps(results, ensure_ascii=False, default=str)


class GetETFInfoTool(Tool):
    name = "get_etf_info"
    description = """ETF의 메타 정보를 종합 조회합니다. 기본 정보(코드, 이름, 보수율(expense_ratio)), 운용사, 태그, 상위 보유종목 10개를 한번에 반환합니다.
보수율 비교, ETF 상세 정보 확인 시 이 도구를 사용하세요.
etf_search로 ETF 코드를 먼저 확인한 후 사용하세요."""
    inputs = {
        "etf_code": {
            "type": "string",
            "description": "ETF 종목코드 (예: '069500')"
        }
    }
    output_type = "string"

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, etf_code: str) -> str:
        graph_service = GraphService(self.db)
        # 기본 정보 + 운용사
        basic = graph_service.execute_cypher(
            f"MATCH (e:ETF {{code: '{etf_code}'}}) "
            f"OPTIONAL MATCH (e)-[:MANAGED_BY]->(c:Company) "
            f"RETURN {{code: e.code, name: e.name, expense_ratio: e.expense_ratio, company: c.name}}"
        )
        if not basic:
            return "해당 ETF를 찾을 수 없습니다"
        info = GraphService.parse_agtype(basic[0]["result"])
        # 태그
        tags = graph_service.execute_cypher(
            f"MATCH (e:ETF {{code: '{etf_code}'}})-[:TAGGED]->(t:Tag) RETURN {{tag: t.name}}"
        )
        info["tags"] = [GraphService.parse_agtype(t["result"])["tag"] for t in tags] if tags else []
        # 상위 보유종목
        holdings = graph_service.execute_cypher(
            f"MATCH (e:ETF {{code: '{etf_code}'}})-[h:HOLDS]->(s:Stock) "
            f"WITH s, h ORDER BY h.date DESC "
            f"WITH s, head(collect(h)) as latest "
            f"RETURN {{stock_code: s.code, stock_name: s.name, weight: latest.weight}} "
            f"ORDER BY latest.weight DESC LIMIT 10"
        )
        info["top_holdings"] = [GraphService.parse_agtype(h["result"]) for h in holdings] if holdings else []
        return json.dumps(info, ensure_ascii=False, default=str)


class GetHoldingsChangesTool(Tool):
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
    output_type = "string"

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, etf_code: str, period: str = "1d") -> str:
        graph_service = GraphService(self.db)
        changes = graph_service.get_etf_holdings_changes(etf_code, period)
        filtered = [c for c in changes if c["change_type"] != "unchanged"]
        if not filtered:
            return "변동 없음"
        return json.dumps(filtered, ensure_ascii=False, default=str)


class GetETFPricesTool(Tool):
    name = "get_etf_prices"
    description = """ETF의 과거 종가(가격) 데이터를 조회합니다. 기간별 종가, 거래량, 수익률 등을 확인할 수 있습니다.
etf_search로 ETF 코드를 먼저 확인한 후 사용하세요.
결과: 기간 내 일별 종가 목록 + 요약 통계(시작가, 최종가, 최고가, 최저가, 등락률)"""
    inputs = {
        "etf_code": {
            "type": "string",
            "description": "ETF 종목코드 (예: '069500')"
        },
        "period": {
            "type": "string",
            "description": "조회 기간: '1w', '1m', '3m', '6m', '1y'. 기본값 '1m'",
            "nullable": True,
        }
    }
    output_type = "string"

    PERIOD_DAYS = {
        "1w": 7,
        "1m": 30,
        "3m": 90,
        "6m": 180,
        "1y": 365,
    }

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, etf_code: str, period: str = "1m") -> str:
        days = self.PERIOD_DAYS.get(period, 30)
        etf_service = ETFService(self.db)
        prices = etf_service.get_etf_prices(etf_code, days=days)
        if not prices:
            return "해당 기간의 가격 데이터가 없습니다"

        closes = [p["close"] for p in prices if p["close"] is not None]
        volumes = [p["volume"] for p in prices if p["volume"] is not None]

        summary = {
            "etf_code": etf_code,
            "period": period,
            "data_count": len(prices),
            "start_date": prices[0]["date"],
            "end_date": prices[-1]["date"],
            "start_close": closes[0] if closes else None,
            "end_close": closes[-1] if closes else None,
            "high": max(closes) if closes else None,
            "low": min(closes) if closes else None,
            "change_rate": round((closes[-1] - closes[0]) / closes[0] * 100, 2) if len(closes) >= 2 else None,
            "avg_volume": round(sum(volumes) / len(volumes)) if volumes else None,
        }

        daily = [{"date": p["date"], "close": p["close"], "volume": p["volume"]} for p in prices]

        return json.dumps({"summary": summary, "daily": daily}, ensure_ascii=False, default=str)


SYSTEM_PROMPT = """당신은 ETF Atlas의 AI 어시스턴트입니다. 한국 ETF 시장에 대한 질문에 답변합니다.

주어진 도구를 활용하여 사용자의 질문에 정확하게 답변하세요:
- stock_search: 종목 이름으로 종목코드를 검색 (예: '삼성전자' → '005930')
- list_tags: 사용 가능한 태그/테마 목록 조회 (정확한 태그명 확인용)
- etf_search: ETF 이름/코드 검색 (예: 'KODEX' → KODEX ETF 목록)
- cypher_query: 그래프 DB에서 ETF 보유종목, 태그, 관계 등을 Cypher로 조회
- get_etf_info: ETF 메타 정보 종합 조회 (기본정보, 운용사, 태그, 상위 보유종목)
- find_similar_etfs: 특정 ETF와 유사한 ETF 조회 (TF-IDF 유사도)
- get_holdings_changes: ETF 보유종목 비중 변화 조회 (전거래일/1주/1개월 비교)
- get_etf_prices: ETF 종가/가격 추이 조회 (기간별 종가, 수익률, 거래량)

사용 순서:
1. 종목명이 나오면 stock_search로 코드를 먼저 확인
2. 태그/테마가 나오면 list_tags로 정확한 태그명을 먼저 확인
3. ETF명이 나오면 etf_search로 코드를 먼저 확인
4. 확인된 코드/태그명으로 적절한 도구 실행

답변 규칙:
1. 한국어로 답변하세요
2. 데이터를 조회한 후 결과를 보기 좋게 정리해서 답변하세요
3. 조회 결과가 없으면 솔직하게 데이터가 없다고 알려주세요
4. 비중(weight)은 퍼센트(%)로 표시하세요
5. 반드시 final_answer()를 호출하여 최종 답변을 반환하세요. 절대 print()로 답변하지 마세요.
"""


class ChatService:
    def __init__(self, db: Session):
        self.db = db
        self._init_agent()

    def _init_agent(self):
        settings = get_settings()
        model = LiteLLMModel(
            model_id="gpt-4.1-mini",
            api_key=settings.openai_api_key,
        )
        self.agent = CodeAgent(
            tools=[
                CypherQueryTool(db=self.db),
                ETFSearchTool(db=self.db),
                StockSearchTool(db=self.db),
                ListTagsTool(db=self.db),
                GetETFInfoTool(db=self.db),
                FindSimilarETFsTool(db=self.db),
                GetHoldingsChangesTool(db=self.db),
                GetETFPricesTool(db=self.db),
            ],
            model=model,
            additional_authorized_imports=["json"],
            max_steps=10,
        )

    def _build_prompt(self, message: str, history: List[Dict[str, str]]) -> str:
        parts = [SYSTEM_PROMPT, ""]
        if history:
            parts.append("## 이전 대화:")
            for msg in history[-10:]:
                role = "사용자" if msg["role"] == "user" else "어시스턴트"
                parts.append(f"{role}: {msg['content']}")
            parts.append("")
        parts.append(f"## 현재 질문:\n{message}")
        return "\n".join(parts)

    def chat(self, message: str, history: List[Dict[str, str]]) -> Dict:
        prompt = self._build_prompt(message, history)
        try:
            result = self.agent.run(prompt)
        except Exception:
            result = None
        steps = self._extract_steps()
        if result is None:
            last_obs = ""
            for s in reversed(steps):
                if s.get("observations"):
                    last_obs = s["observations"]
                    break
            answer = last_obs if last_obs else "죄송합니다. 답변 생성에 실패했습니다. 다시 질문해 주세요."
        else:
            answer = str(result)
        return {"answer": answer, "steps": steps}

    def chat_stream(self, message: str, history: List[Dict[str, str]]):
        from smolagents.memory import ActionStep
        from smolagents.agents import FinalAnswerStep

        prompt = self._build_prompt(message, history)
        got_final_answer = False
        last_observations = ""
        for event in self.agent.run(prompt, stream=True):
            if isinstance(event, ActionStep):
                tool_calls = []
                if event.tool_calls:
                    for tc in event.tool_calls:
                        tool_calls.append({"name": tc.name, "arguments": str(tc.arguments)})
                if event.observations:
                    last_observations = event.observations
                yield {
                    "type": "step",
                    "data": {
                        "step_number": event.step_number,
                        "code": event.code_action or "",
                        "observations": (event.observations or "")[:2000],
                        "tool_calls": tool_calls,
                        "error": str(event.error) if event.error else None,
                    },
                }
            elif isinstance(event, FinalAnswerStep):
                got_final_answer = True
                yield {
                    "type": "answer",
                    "data": {"answer": str(event.output)},
                }
        if not got_final_answer:
            fallback = last_observations[:2000] if last_observations else "죄송합니다. 답변 생성에 실패했습니다. 다시 질문해 주세요."
            yield {
                "type": "answer",
                "data": {"answer": fallback},
            }

    def _extract_steps(self) -> List[Dict]:
        from smolagents.memory import ActionStep
        steps = []
        for step in self.agent.memory.steps:
            if not isinstance(step, ActionStep):
                continue
            tool_calls = []
            if step.tool_calls:
                for tc in step.tool_calls:
                    tool_calls.append({"name": tc.name, "arguments": str(tc.arguments)})
            steps.append({
                "step_number": step.step_number,
                "code": step.code_action or "",
                "observations": (step.observations or "")[:2000],
                "tool_calls": tool_calls,
                "error": str(step.error) if step.error else None,
            })
        return steps
