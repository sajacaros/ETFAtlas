from typing import Any, Dict, List

from ..graph_service import GraphService


def node(graph: GraphService, cypher: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    # DB 오류를 "데이터 없음"으로 삼키지 않고 슬롯 실패로 드러낸다
    return [GraphService.parse_agtype(r["result"]) for r in graph.execute_cypher(cypher, params, raise_errors=True)]
