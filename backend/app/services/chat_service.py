import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic_ai import (
    Agent, AgentRunResultEvent, FunctionToolCallEvent, FunctionToolResultEvent, Tool as AgentTool,
)
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import RetryPromptPart
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits
from sqlalchemy.orm import Session

from ..config import get_settings
from .graph_service import GraphService
from .embedding_service import EmbeddingService
from .chat_prompt import SYSTEM_PROMPT
from .chat_memory import ChatMemory, ConversationContext

logger = logging.getLogger(__name__)


def _format_expense_ratio(results: list[dict]) -> list[dict]:
    """expense_ratio를 '0.80%' 형식 문자열로 변환하여 LLM의 단위 혼동을 방지한다."""
    for r in results:
        if r.get("expense_ratio") is not None:
            r["expense_ratio"] = f'{float(r["expense_ratio"]):.2f}%'
    return results


def _format_korean_money(n) -> str:
    """숫자를 한국식 단위(억, 만)로 포맷."""
    n = int(float(n))
    abs_n = abs(n)
    sign = "-" if n < 0 else ""
    if abs_n >= 1_0000_0000:
        eok = abs_n // 1_0000_0000
        return f"{sign}{eok:,}억원"
    if abs_n >= 1_0000:
        man = abs_n // 1_0000
        return f"{sign}{man:,}만원"
    if abs_n >= 1000:
        return f"{sign}{abs_n:,}원"
    return f"{sign}{abs_n}원"


_MONETARY_FIELDS = {"market_cap", "net_assets", "latest_market_cap", "latest_net_assets", "trade_value"}


def _format_monetary_fields(data: dict) -> dict:
    """딕셔너리의 금액 필드를 한국식 단위로 포맷."""
    for k in _MONETARY_FIELDS:
        if k in data and data[k] is not None:
            data[k] = _format_korean_money(data[k])
    return data


_PERCENT_FIELDS = {
    "change_rate", "return_1d", "return_1w", "return_1m", "return_3m",
    "market_cap_change_1w", "similarity",
    "weight", "current_weight", "previous_weight", "weight_change",
}


def _format_percent_fields(data: dict) -> dict:
    """백분율 필드에 '%' 접미사를 추가하여 LLM의 단위 혼동을 방지한다."""
    for k in _PERCENT_FIELDS:
        if k in data and data[k] is not None:
            data[k] = f'{float(data[k]):.2f}%'
    return data


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
            return self.forward(**{k: v for k, v in kwargs.items() if v is not None})

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
        results = _format_expense_ratio([GraphService.parse_agtype(row["result"]) for row in rows])
        results = [_format_monetary_fields(r) for r in results]
        return json.dumps(results, ensure_ascii=False, default=str)


class StockSearchTool(ChatTool):
    name = "stock_search"
    description = """주식 종목(삼성전자, SK하이닉스 등 개별 주식)을 이름이나 코드로 검색합니다. ETF 검색은 etf_search를 사용하세요.
예: '삼성전자' 검색 → code: '005930'. 찾은 코드를 get_stock_prices 등에서 사용하세요.
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
        results = [GraphService.parse_agtype(row["result"]) for row in rows]
        return json.dumps(results, ensure_ascii=False, default=str)


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
        return json.dumps(tags, ensure_ascii=False, default=str)


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
        results = [_format_percent_fields(r) for r in results]
        return json.dumps(results, ensure_ascii=False, default=str)


class GetETFInfoTool(ChatTool):
    name = "get_etf_info"
    description = """ETF의 메타 정보를 종합 조회합니다. 기본 정보(코드, 이름, 보수율, 기초지수, 상장일, 운용사 설명), 운용사, 태그, 상위 보유종목 10개, 최근 수익률(1주/1개월/3개월)을 한번에 반환합니다.
보수율 비교, ETF 상세 정보 확인, "이 ETF는 무엇에 투자하나" 같은 질문에 이 도구를 사용하세요.
etf_search로 ETF 코드를 먼저 확인한 후 사용하세요."""
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
        # 기본 정보 + 운용사
        basic = graph_service.execute_cypher(
            "MATCH (e:ETF {code: $etf_code}) "
            "OPTIONAL MATCH (e)-[:MANAGED_BY]->(c:Company) "
            "RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, company: c.name, "
            "base_index: e.base_index, listed_date: e.listed_date, description: e.description}",
            {"etf_code": etf_code},
        )
        if not basic:
            return "해당 ETF를 찾을 수 없습니다"
        info = _format_expense_ratio([GraphService.parse_agtype(basic[0]["result"])])[0]
        # 태그
        tags = graph_service.execute_cypher(
            "MATCH (e:ETF {code: $etf_code})-[:TAGGED]->(t:Tag) RETURN {tag: t.name}",
            {"etf_code": etf_code},
        )
        info["tags"] = [GraphService.parse_agtype(t["result"])["tag"] for t in tags] if tags else []
        # 상위 보유종목
        holdings = graph_service.execute_cypher(
            "MATCH (e:ETF {code: $etf_code})-[h:CURRENT_HOLDS]->(s:Stock) "
            "RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight} "
            "ORDER BY h.weight DESC LIMIT 10",
            {"etf_code": etf_code},
        )
        info["top_holdings"] = [_format_percent_fields(GraphService.parse_agtype(h["result"])) for h in holdings] if holdings else []
        # 최근 수익률 (1주/1개월/3개월)
        prices = graph_service.get_etf_prices(etf_code, days=90)
        if prices:
            closes = [(p["date"], p["close"]) for p in prices if p["close"] is not None]
            if len(closes) >= 2:
                latest_close = closes[-1][1]
                returns = {}
                for label, days_back in [("1w", 7), ("1m", 30), ("3m", 90)]:
                    target = [c for c in closes if c[0] <= closes[-1][0]]
                    # 가장 가까운 과거 데이터 찾기
                    from datetime import date as dt_date, timedelta
                    target_date = (dt_date.fromisoformat(closes[-1][0]) - timedelta(days=days_back)).isoformat()
                    past = [c for c in closes if c[0] <= target_date]
                    if past:
                        past_close = past[-1][1]
                        returns[label] = f'{round((latest_close - past_close) / past_close * 100, 2):.2f}%'
                if returns:
                    info["returns"] = returns
        return json.dumps(info, ensure_ascii=False, default=str)


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
        filtered = [_format_percent_fields(c) for c in filtered]
        return json.dumps(filtered, ensure_ascii=False, default=str)


class GetETFPricesTool(ChatTool):
    name = "get_etf_prices"
    description = """ETF의 과거 가격 데이터를 조회합니다. 주식 종목이 아닌 ETF 전용입니다. 기간별 종가, 거래량, 수익률, 시가총액, 순자산총액을 확인할 수 있습니다.
etf_search로 ETF 코드를 먼저 확인한 후 사용하세요. 주식 종목 가격은 get_stock_prices를 사용하세요.
결과: 기간 내 일별 종가/시가총액/순자산총액 목록 + 요약 통계"""
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
        graph_service = GraphService(self.db)
        prices = graph_service.get_etf_prices(etf_code, days=days)
        if not prices:
            return "해당 기간의 가격 데이터가 없습니다"

        closes = [p["close"] for p in prices if p["close"] is not None]
        volumes = [p["volume"] for p in prices if p["volume"] is not None]
        market_caps = [p.get("market_cap") for p in prices if p.get("market_cap") is not None]
        net_assets_list = [p.get("net_assets") for p in prices if p.get("net_assets") is not None]

        summary = _format_percent_fields(_format_monetary_fields({
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
            "latest_market_cap": market_caps[-1] if market_caps else None,
            "latest_net_assets": net_assets_list[-1] if net_assets_list else None,
        }))

        daily = [
            _format_monetary_fields({
                "date": p["date"],
                "close": p["close"],
                "volume": p["volume"],
                "market_cap": p.get("market_cap"),
                "net_assets": p.get("net_assets"),
            })
            for p in prices
        ]

        return json.dumps({"summary": summary, "daily": daily}, ensure_ascii=False, default=str)


class GetStockPricesTool(ChatTool):
    name = "get_stock_prices"
    description = """주식 종목(삼성전자, SK하이닉스 등 개별 주식)의 과거 가격 데이터를 조회합니다. ETF가 아닌 주식 전용입니다. 기간별 OHLCV(시/고/저/종/거래량), 등락률을 확인할 수 있습니다.
stock_search로 종목 코드를 먼저 확인한 후 사용하세요. ETF 가격은 get_etf_prices를 사용하세요.
결과: 기간 내 일별 가격 목록 + 요약 통계(시작가, 최종가, 최고가, 최저가, 등락률)"""
    inputs = {
        "stock_code": {
            "type": "string",
            "description": "종목코드 (예: '005930')"
        },
        "period": {
            "type": "string",
            "description": "조회 기간: '1w', '1m', '3m', '6m', '1y'. 기본값 '1m'",
            "nullable": True,
        }
    }

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

    def forward(self, stock_code: str, period: str = "1m") -> str:
        days = self.PERIOD_DAYS.get(period, 30)
        graph_service = GraphService(self.db)
        prices = graph_service.get_stock_prices(stock_code, days=days)
        if not prices:
            return "해당 기간의 가격 데이터가 없습니다"

        closes = [p["close"] for p in prices if p["close"] is not None]
        volumes = [p["volume"] for p in prices if p["volume"] is not None]

        summary = _format_percent_fields({
            "stock_code": stock_code,
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
        })

        daily = [
            _format_percent_fields({
                "date": p["date"],
                "open": p["open"],
                "high": p["high"],
                "low": p["low"],
                "close": p["close"],
                "volume": p["volume"],
                "change_rate": p["change_rate"],
            })
            for p in prices
        ]

        return json.dumps({"summary": summary, "daily": daily}, ensure_ascii=False, default=str)


class CompareETFsTool(ChatTool):
    name = "compare_etfs"
    description = """2~3개 ETF를 한번에 비교합니다. 비교 항목: 기본정보(보수율, 순자산), 태그, 최근 1개월 수익률, 상위 보유종목 5개.
etf_search로 ETF 코드를 먼저 확인한 후 사용하세요."""
    inputs = {
        "etf_codes": {
            "type": "string",
            "description": "비교할 ETF 코드들 (쉼표 구분, 예: '069500,102110,229200')"
        }
    }

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, etf_codes: str) -> str:
        codes = [c.strip() for c in etf_codes.split(",") if c.strip()]
        if len(codes) < 2:
            return "비교하려면 최소 2개의 ETF 코드가 필요합니다"
        if len(codes) > 3:
            codes = codes[:3]

        graph_service = GraphService(self.db)
        results = []

        for code in codes:
            etf_data = {}
            # 기본 정보 + 운용사
            basic = graph_service.execute_cypher(
                "MATCH (e:ETF {code: $etf_code}) "
                "OPTIONAL MATCH (e)-[:MANAGED_BY]->(c:Company) "
                "RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, company: c.name}",
                {"etf_code": code},
            )
            if not basic:
                results.append({"code": code, "error": "ETF를 찾을 수 없습니다"})
                continue
            etf_data = _format_expense_ratio([GraphService.parse_agtype(basic[0]["result"])])[0]

            # 태그
            tags = graph_service.execute_cypher(
                "MATCH (e:ETF {code: $etf_code})-[:TAGGED]->(t:Tag) RETURN {tag: t.name}",
                {"etf_code": code},
            )
            etf_data["tags"] = [GraphService.parse_agtype(t["result"])["tag"] for t in tags] if tags else []

            # 상위 보유종목 5개
            holdings = graph_service.execute_cypher(
                "MATCH (e:ETF {code: $etf_code})-[h:CURRENT_HOLDS]->(s:Stock) "
                "RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight} "
                "ORDER BY h.weight DESC LIMIT 5",
                {"etf_code": code},
            )
            etf_data["top_holdings"] = [_format_percent_fields(GraphService.parse_agtype(h["result"])) for h in holdings] if holdings else []

            # 최근 1개월 수익률 + 순자산
            prices = graph_service.get_etf_prices(code, days=30)
            if prices:
                closes = [p["close"] for p in prices if p["close"] is not None]
                if len(closes) >= 2:
                    etf_data["return_1m"] = f'{round((closes[-1] - closes[0]) / closes[0] * 100, 2):.2f}%'
                net_assets_list = [p.get("net_assets") for p in prices if p.get("net_assets") is not None]
                if net_assets_list:
                    etf_data["latest_net_assets"] = net_assets_list[-1]

            results.append(_format_monetary_fields(etf_data))

        return json.dumps(results, ensure_ascii=False, default=str)


class GraphQueryTool(ChatTool):
    name = "graph_query"
    description = """그래프 DB에 Cypher 쿼리를 직접 실행합니다. 다른 전용 도구로 해결할 수 없는 그래프 관계 질문에 사용하세요.
예: '삼성전자를 가장 많이 보유한 ETF', '반도체 태그 ETF 중 보수율 낮은 순', '삼성자산운용의 ETF 목록' 등

## 그래프 스키마
노드: ETF(code, name, expense_ratio, base_index, listed_date, description, net_assets, close_price, return_1d, return_1w, return_1m, market_cap_change_1w, updated_at), Stock(code, name, is_etf), Company(name), Tag(name), Price(date, open, high, low, close, volume, nav, market_cap, net_assets, trade_value, change_rate), User(user_id)
관계: (ETF)-[:CURRENT_HOLDS {date, weight, shares}]->(Stock) = 현재 구성종목(ETF당 비중 상위 30개), (ETF)-[:HOLDS {date, weight, shares}]->(Stock) = 날짜별 구성종목 이력(비중 변화 비교에만 사용), (ETF)-[:MANAGED_BY]->(Company), (ETF)-[:TAGGED]->(Tag), (ETF)-[:HAS_PRICE]->(Price), (Stock)-[:HAS_PRICE]->(Price), (User)-[:WATCHES {added_at}]->(ETF)

## Cypher 작성 규칙
1. MATCH로 시작하는 읽기 전용 쿼리만 가능 (CREATE/MERGE/DELETE/SET 불가, '$$'와 ';' 사용 불가)
2. RETURN은 반드시 단일 맵으로 감싸세요: RETURN {key1: val1, key2: val2}
3. 문자열 값은 작은따옴표: {code: '005930'}
4. 집계 함수와 ORDER BY를 함께 쓸 때 WITH 절로 분리하세요
5. weight, expense_ratio, return_*, net_assets는 숫자로 저장되어 있습니다(비중·보수율·수익률은 % 단위, 순자산은 원). 결과에 '%'나 '억원'이 붙어 보이는 건 표시용 서식이니, 조건은 숫자로 쓰세요 (예: h.weight >= 10, e.expense_ratio <= 0.1)

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
        results = _format_expense_ratio([GraphService.parse_agtype(row["result"]) for row in rows])
        results = [_format_percent_fields(_format_monetary_fields(r)) for r in results]
        return json.dumps(results, ensure_ascii=False, default=str)



# ---------------------------------------------------------------------------
# ChatService
# ---------------------------------------------------------------------------

MAX_MODEL_REQUESTS = 15
FALLBACK_ANSWER = "죄송합니다. 답변 생성에 실패했습니다. 다시 질문해 주세요."


def format_tool_call(name: str, args: Dict[str, Any]) -> str:
    """도구 호출을 `name(key="value", ...)` 표기로 직렬화 (few-shot 예시/로그 공용 포맷)."""
    params = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())
    return f"{name}({params})"


class ChatService:
    def __init__(self, db: Session):
        self.db = db
        self._settings = get_settings()
        self._tag_names = self._load_tag_names()
        self._embedding_service = EmbeddingService(db)
        self.memory = ChatMemory(db)
        self._tools = self._create_tools()
        self._init_agent()

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
            GetETFInfoTool(db=self.db),
            FindSimilarETFsTool(db=self.db),
            GetHoldingsChangesTool(db=self.db),
            GetETFPricesTool(db=self.db),
            GetStockPricesTool(db=self.db),
            CompareETFsTool(db=self.db),
            GraphQueryTool(db=self.db),
        ]
        return {t.name: t for t in tools}

    def _init_agent(self):
        """tool-calling 에이전트 초기화 (LiteLLM 프록시, OpenAI 호환 API)."""
        model = OpenAIChatModel(
            self._settings.llm_model,
            provider=OpenAIProvider(
                base_url=self._settings.llm_api_base,
                api_key=self._settings.llm_api_key,
            ),
        )
        self.agent = Agent(
            model,
            instructions=self._instructions(),
            tools=[t.as_agent_tool() for t in self._tools.values()],
        )

    def _instructions(self) -> str:
        parts = [SYSTEM_PROMPT]
        if self._tag_names:
            parts.append(f"## 사용 가능한 태그 목록\n{', '.join(self._tag_names)}")
        return "\n\n".join(parts)

    def _build_prompt(self, question: str, context: ConversationContext, original: str) -> tuple:
        """사용자 프롬프트(참고 예시 + 대화 맥락 + 현재 질문)와 매칭된 예시를 반환한다.

        question은 맥락으로 재작성된 독립 질문, original은 사용자가 입력한 원문.
        """
        parts = []
        # 예시는 일반화된 질문으로 임베딩되어 있으므로 검색 질의도 같은 방식으로 일반화한다
        search_query = self._embedding_service.generalize_question(question)
        code_examples = self._embedding_service.find_similar_code_examples(search_query, top_k=3)
        if code_examples:
            parts.append("## 참고 해결 절차 예시")
            parts.append("비슷한 유형의 질문을 해결한 도구 호출 순서입니다. "
                         "<종목명>, <ETF명>, <운용사> 같은 자리표시자는 현재 질문의 값으로 바꾸고, "
                         "<…의 code>는 앞 호출 결과의 값을 쓰세요. 쿼리 구조(특히 Cypher)는 그대로 따르세요:")
            for ex in code_examples:
                question = ex.get("question_generalized") or ex["question"]
                parts.append(f"Q: {question}\n```\n{ex['code']}\n```")
            parts.append("")
        if not context.is_empty():
            parts.append("## 이전 대화 (참고용)")
            parts.append("아래는 이전 대화 내용입니다. 맥락 파악에만 참고하세요.")
            parts.append("현재 질문은 이미 맥락을 반영해 다시 쓴 것이니, 이전 대화의 조건(개수, 필터 등)을 덧붙이지 마세요.")
            parts.append(context.render())
            parts.append("")
        parts.append(f"## 현재 질문 (이 질문의 조건만 따르세요):\n{question}")
        if question != original:
            parts.append(f"(사용자 원문: {original})")
        return "\n".join(parts), code_examples

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat(self, message: str, context: Optional[ConversationContext] = None) -> Dict:
        answer = FALLBACK_ANSWER
        refined_question = message
        steps: List[Dict] = []
        matched_examples: List[Dict] = []
        async for event in self.chat_stream(message, context):
            if event["type"] == "refined_question":
                refined_question = event["data"]["question"]
            elif event["type"] == "step":
                steps.append(event["data"])
            elif event["type"] == "answer":
                answer = event["data"]["answer"]
            elif event["type"] == "matched_examples":
                matched_examples = event["data"]["examples"]
        return {
            "answer": answer, "refined_question": refined_question,
            "steps": steps, "matched_examples": matched_examples,
        }

    async def chat_stream(
        self, message: str, context: Optional[ConversationContext] = None,
    ) -> AsyncIterator[Dict]:
        """도구 호출/결과를 step 이벤트로, 최종 응답을 answer 이벤트로 스트리밍한다.

        맥락이 있으면 먼저 질문을 독립 질문으로 재작성하고, 바뀌었으면 refined_question 이벤트를 보낸다.
        step: {step_number, code(도구 호출 표기), observations, tool_calls, error}
        """
        context = context or ConversationContext()
        # LLM/임베딩 호출(동기 HTTP/DB)은 이벤트 루프를 막지 않도록 스레드에서 실행
        question = await asyncio.to_thread(self.memory.refine, message, context)
        if question != message:
            yield {"type": "refined_question", "data": {"question": question}}
        prompt, matched_examples = await asyncio.to_thread(self._build_prompt, question, context, message)
        if matched_examples:
            yield {"type": "matched_examples", "data": {"examples": matched_examples}}

        pending: Dict[str, Dict[str, Any]] = {}
        step_number = 0
        last_observations = ""
        answer = None
        try:
            async with self.agent.run_stream_events(
                prompt, usage_limits=UsageLimits(request_limit=MAX_MODEL_REQUESTS),
            ) as stream:
                async for event in stream:
                    if isinstance(event, FunctionToolCallEvent):
                        part = event.part
                        pending[part.tool_call_id] = {"name": part.tool_name, "args": part.args_as_dict()}
                    elif isinstance(event, FunctionToolResultEvent):
                        call = pending.pop(event.tool_call_id, None) or {"name": "unknown", "args": {}}
                        is_error = isinstance(event.part, RetryPromptPart)
                        content = event.part.model_response() if is_error else str(event.part.content)
                        if not is_error:
                            last_observations = content
                        step_number += 1
                        yield {
                            "type": "step",
                            "data": {
                                "step_number": step_number,
                                "code": format_tool_call(call["name"], call["args"]),
                                "observations": content[:2000],
                                "tool_calls": [{"name": call["name"], "arguments": json.dumps(call["args"], ensure_ascii=False)}],
                                "error": content[:500] if is_error else None,
                            },
                        }
                    elif isinstance(event, AgentRunResultEvent):
                        answer = str(event.result.output).strip()
        except UsageLimitExceeded:
            logger.warning("Chat agent hit request limit (%d)", MAX_MODEL_REQUESTS)
        except Exception:
            logger.exception("Chat agent failed")

        if not answer:
            answer = last_observations[:2000] if last_observations else FALLBACK_ANSWER
        yield {"type": "answer", "data": {"answer": answer}}
