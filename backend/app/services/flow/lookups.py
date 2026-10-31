"""노드들이 함께 쓰는 DB 조회."""
from typing import Dict, List

from sqlalchemy.orm import Session

from ..graph_service import GraphService, node


def held_by(db: Session, codes: List[str]) -> Dict[str, List[Dict]]:
    """종목 코드 → 그 종목을 상위 30위 안에 담은 ETF [{code, etf, weight}], 비중 큰 순."""
    if not codes:
        return {}
    rows = node(
        GraphService(db),
        "MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock) WHERE s.code IN $codes "
        "RETURN {code: s.code, etf: e.name, weight: h.weight}",
        {"codes": codes},
    )
    out: Dict[str, List[Dict]] = {}
    for r in sorted(rows, key=lambda r: -(r.get("weight") or 0)):
        out.setdefault(r["code"], []).append(r)
    return out
