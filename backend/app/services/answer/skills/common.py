"""데이터 스킬들이 함께 쓰는 도우미."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from ...graph_service import GraphService

PERIOD_DAYS = {"1w": 7, "1m": 30, "3m": 90, "6m": 180, "1y": 365}

ETF_NAMES_DESCRIPTION = "ETF 이름 또는 6자리 코드. 사용자가 말한 이름을 그대로 적는다 (예: 'KODEX 200')"


class ETFListArgs(BaseModel):
    etfs: List[str] = Field(min_length=1, max_length=5, description=ETF_NAMES_DESCRIPTION)


def missing_notes(missing: List[str]) -> List[str]:
    return [f"찾지 못한 ETF: {', '.join(missing)}"] if missing else []


def node(graph: GraphService, cypher: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    # DB 오류를 "데이터 없음"으로 삼키지 않고 슬롯 실패로 드러낸다
    return [GraphService.parse_agtype(r["result"]) for r in graph.execute_cypher(cypher, params, raise_errors=True)]


def pct_change(start: Optional[float], end: Optional[float]) -> Optional[float]:
    if not start or end is None:
        return None
    return round((end - start) / start * 100, 2)


def format_value(value: Any, fmt: str) -> str:
    """요약 텍스트용 서식 (LLM이 단위를 헷갈리지 않게). 화면 표시 서식은 프런트가 따로 한다."""
    if value is None:
        return "-"
    if fmt == "percent":
        return f"{value:.2f}%"
    if fmt == "krw":
        eok = int(value) // 1_0000_0000
        return f"{eok // 1_0000:,}조 {eok % 1_0000:,}억원" if eok >= 1_0000 else f"{eok:,}억원"
    if fmt == "price":
        return f"{value:,.0f}원"
    if fmt == "number" and isinstance(value, (int, float)):
        return f"{value:,}"
    return str(value)
