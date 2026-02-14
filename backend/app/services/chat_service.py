import json
import logging
from typing import List, Dict
from sqlalchemy.orm import Session
from smolagents import Tool, CodeAgent, LiteLLMModel
from ..config import get_settings
from .graph_service import GraphService

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


class ETFSearchTool(Tool):
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
    output_type = "string"

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


class StockSearchTool(Tool):
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
    output_type = "string"

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


class ListTagsTool(Tool):
    name = "list_tags"
    description = """그래프 DB에 등록된 모든 태그(테마) 목록과 각 태그에 속한 ETF 수를 조회합니다.
사용자가 특정 테마/섹터의 ETF를 질문할 때, 먼저 이 도구로 정확한 태그명을 확인하세요."""
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
    description = """특정 ETF와 보유종목이 유사한 ETF를 찾습니다. 보유종목 비중 겹침(overlap) 기반 유사도로 계산합니다.
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
    description = """ETF의 메타 정보를 종합 조회합니다. 기본 정보(코드, 이름, 보수율), 운용사, 태그, 상위 보유종목 10개, 최근 수익률(1주/1개월/3개월)을 한번에 반환합니다.
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
            "MATCH (e:ETF {code: $etf_code}) "
            "OPTIONAL MATCH (e)-[:MANAGED_BY]->(c:Company) "
            "RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, company: c.name}",
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
            "MATCH (e:ETF {code: $etf_code})-[h:HOLDS]->(s:Stock) "
            "WITH s, h ORDER BY h.date DESC "
            "WITH s, head(collect(h)) as latest "
            "RETURN {stock_code: s.code, stock_name: s.name, weight: latest.weight} "
            "ORDER BY latest.weight DESC LIMIT 10",
            {"etf_code": etf_code},
        )
        info["top_holdings"] = [GraphService.parse_agtype(h["result"]) for h in holdings] if holdings else []
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
                        returns[label] = round((latest_close - past_close) / past_close * 100, 2)
                if returns:
                    info["returns"] = returns
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
        graph_service = GraphService(self.db)
        prices = graph_service.get_etf_prices(etf_code, days=days)
        if not prices:
            return "해당 기간의 가격 데이터가 없습니다"

        closes = [p["close"] for p in prices if p["close"] is not None]
        volumes = [p["volume"] for p in prices if p["volume"] is not None]
        market_caps = [p.get("market_cap") for p in prices if p.get("market_cap") is not None]
        net_assets_list = [p.get("net_assets") for p in prices if p.get("net_assets") is not None]

        summary = _format_monetary_fields({
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
        })

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


class GetStockPricesTool(Tool):
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

    def forward(self, stock_code: str, period: str = "1m") -> str:
        days = self.PERIOD_DAYS.get(period, 30)
        graph_service = GraphService(self.db)
        prices = graph_service.get_stock_prices(stock_code, days=days)
        if not prices:
            return "해당 기간의 가격 데이터가 없습니다"

        closes = [p["close"] for p in prices if p["close"] is not None]
        volumes = [p["volume"] for p in prices if p["volume"] is not None]

        summary = {
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
        }

        daily = [
            {
                "date": p["date"],
                "open": p["open"],
                "high": p["high"],
                "low": p["low"],
                "close": p["close"],
                "volume": p["volume"],
                "change_rate": p["change_rate"],
            }
            for p in prices
        ]

        return json.dumps({"summary": summary, "daily": daily}, ensure_ascii=False, default=str)


class CompareETFsTool(Tool):
    name = "compare_etfs"
    description = """2~3개 ETF를 한번에 비교합니다. 비교 항목: 기본정보(보수율, 순자산), 태그, 최근 1개월 수익률, 상위 보유종목 5개.
etf_search로 ETF 코드를 먼저 확인한 후 사용하세요."""
    inputs = {
        "etf_codes": {
            "type": "string",
            "description": "비교할 ETF 코드들 (쉼표 구분, 예: '069500,102110,229200')"
        }
    }
    output_type = "string"

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
                "MATCH (e:ETF {code: $etf_code})-[h:HOLDS]->(s:Stock) "
                "WITH s, h ORDER BY h.date DESC "
                "WITH s, head(collect(h)) as latest "
                "RETURN {stock_code: s.code, stock_name: s.name, weight: latest.weight} "
                "ORDER BY latest.weight DESC LIMIT 5",
                {"etf_code": code},
            )
            etf_data["top_holdings"] = [GraphService.parse_agtype(h["result"]) for h in holdings] if holdings else []

            # 최근 1개월 수익률 + 순자산
            prices = graph_service.get_etf_prices(code, days=30)
            if prices:
                closes = [p["close"] for p in prices if p["close"] is not None]
                if len(closes) >= 2:
                    etf_data["return_1m"] = round((closes[-1] - closes[0]) / closes[0] * 100, 2)
                net_assets_list = [p.get("net_assets") for p in prices if p.get("net_assets") is not None]
                if net_assets_list:
                    etf_data["latest_net_assets"] = net_assets_list[-1]

            results.append(_format_monetary_fields(etf_data))

        return json.dumps(results, ensure_ascii=False, default=str)


class GraphQueryTool(Tool):
    name = "graph_query"
    description = """그래프 DB에 Cypher 쿼리를 직접 실행합니다. 다른 전용 도구로 해결할 수 없는 그래프 관계 질문에 사용하세요.
예: '삼성전자를 가장 많이 보유한 ETF', '반도체 태그 ETF 중 보수율 낮은 순', '삼성자산운용의 ETF 목록' 등

## 그래프 스키마
노드: ETF(code, name, expense_ratio, updated_at), Stock(code, name, is_etf), Company(name), Tag(name), Price(date, open, high, low, close, volume, nav, market_cap, net_assets, trade_value, change_rate)
관계: (ETF)-[:HOLDS {date, weight, shares}]->(Stock), (ETF)-[:MANAGED_BY]->(Company), (ETF)-[:TAGGED]->(Tag), (ETF)-[:HAS_PRICE]->(Price), (Stock)-[:HAS_PRICE]->(Price), (ETF)-[:HAS_CHANGE {date, change_type}]->(Stock)

## Cypher 작성 규칙
1. MATCH로 시작하는 읽기 전용 쿼리만 가능 (CREATE/MERGE/DELETE/SET 불가)
2. RETURN은 반드시 단일 맵으로 감싸세요: RETURN {key1: val1, key2: val2}
3. 문자열 값은 작은따옴표: {code: '005930'}
4. 집계 함수와 ORDER BY를 함께 쓸 때 WITH 절로 분리하세요

## 쿼리 패턴 예시

ETF의 최신 보유종목 (반드시 이 패턴 사용):
MATCH (e:ETF {code: '069500'})-[h:HOLDS]->(s:Stock)
WITH s, h ORDER BY h.date DESC
WITH s, head(collect(h)) as latest
RETURN {stock_code: s.code, stock_name: s.name, weight: latest.weight}
ORDER BY latest.weight DESC LIMIT 10

특정 종목을 보유한 ETF:
MATCH (e:ETF)-[h:HOLDS]->(s:Stock {code: '005930'})
WITH e, h ORDER BY h.date DESC
WITH e, head(collect(h)) as latest
RETURN {etf_code: e.code, etf_name: e.name, weight: latest.weight}
ORDER BY latest.weight DESC

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
    output_type = "string"

    FORBIDDEN = ("CREATE", "MERGE", "DELETE", "SET ", "REMOVE", "DROP")

    def __init__(self, db: Session):
        super().__init__()
        self.db = db

    def forward(self, cypher: str) -> str:
        upper = cypher.strip().upper()
        for kw in self.FORBIDDEN:
            if kw in upper:
                return f"오류: 읽기 전용 쿼리만 허용됩니다 ({kw} 사용 불가)"
        graph_service = GraphService(self.db)
        rows = graph_service.execute_cypher(cypher)
        if not rows:
            return "조회 결과 없음"
        results = _format_expense_ratio([GraphService.parse_agtype(row["result"]) for row in rows])
        results = [_format_monetary_fields(r) for r in results]
        return json.dumps(results, ensure_ascii=False, default=str)


SYSTEM_PROMPT = """당신은 ETF Atlas의 AI 어시스턴트입니다. 한국 ETF 시장에 대한 질문에 답변합니다.

주어진 도구를 활용하여 사용자의 질문에 정확하게 답변하세요:
- etf_search: ETF 이름/코드 검색 (예: 'KODEX' → KODEX ETF 목록). 사용자가 "다 찾아줘/전부/모두" 요청 시 limit=50으로 호출
- stock_search: 종목 이름으로 종목코드를 검색 (예: '삼성전자' → '005930'). 사용자가 전체 조회 요청 시 limit=50으로 호출
- list_tags: 사용 가능한 태그/테마 목록 조회 (정확한 태그명 확인용)
- get_etf_info: ETF 메타 정보 종합 조회 (기본정보, 운용사, 태그, 상위 보유종목, 최근 수익률)
- find_similar_etfs: 특정 ETF와 유사한 ETF 조회 (보유종목 비중 겹침 유사도)
- get_holdings_changes: ETF 보유종목 비중 변화 조회 (전거래일/1주/1개월 비교)
- get_etf_prices: ETF 가격/시가총액/순자산총액 추이 조회 (기간별 종가, 수익률, 거래량, 시가총액)
- get_stock_prices: 종목(주식) 가격 추이 조회 (기간별 OHLCV, 등락률)
- compare_etfs: 2~3개 ETF 비교 (보수율, 태그, 수익률, 보유종목 비교)
- graph_query: 그래프 DB에 Cypher 쿼리 직접 실행. 다른 도구로 해결 안 되는 복잡한 관계 질문에 사용 (태그별 ETF, 운용사별 ETF, 종목 보유 ETF 등)

사용 순서:
1. 종목명이 나오면 stock_search로 코드를 먼저 확인
2. 태그/테마가 나오면 list_tags로 정확한 태그명을 먼저 확인
3. ETF명이 나오면 etf_search로 코드를 먼저 확인
4. 확인된 코드/태그명으로 적절한 전용 도구 실행
5. ETF 비교 질문은 compare_etfs 사용
6. 전용 도구가 없는 그래프 관계 질문은 graph_query로 Cypher 직접 작성

답변 규칙:
1. 한국어로 답변하세요
2. 데이터를 조회한 후 결과를 보기 좋게 정리해서 답변하세요
3. 조회 결과가 없으면 솔직하게 데이터가 없다고 알려주세요
4. 비중(weight)은 퍼센트(%)로 표시하세요
5. 반드시 final_answer()를 호출하여 최종 답변을 반환하세요. 절대 print()로 답변하지 마세요.
6. 결과를 정렬하여 답변할 때 반드시 정렬 방향을 검증하세요:
   - "가장 높은/좋은/큰" → 내림차순(reverse=True)
   - "가장 낮은/작은" → 오름차순(reverse=False)
   - final_answer() 호출 전에 정렬된 결과의 첫 번째와 마지막 값을 비교하여 질문 의도에 맞는지 확인하세요.
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
