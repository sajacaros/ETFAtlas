"""두 수집일의 ETF 보유 비중을 비교한다. 웹 화면(그래프 조회)과 Airflow(weight_changes 저장)가 함께 쓴다."""
from typing import Dict, List, Mapping, Optional

ADDED, REMOVED, INCREASED, DECREASED = "added", "removed", "increased", "decreased"


def change_type(prev: Optional[Mapping], curr: Optional[Mapping], diff: float) -> str:
    if curr and not prev:
        return ADDED
    if prev and not curr:
        return REMOVED
    return INCREASED if diff > 0 else DECREASED


def diff_holdings(prev: Mapping[str, Mapping], curr: Mapping[str, Mapping]) -> List[Dict]:
    """종목 코드 → {name, weight} 두 개를 비교해 비중이 달라진 종목만. 빠진 종목은 0%, 새로 들어온 종목은 이전 0%로 본다."""
    changes = []
    for code in sorted(set(curr) | set(prev)):
        c, p = curr.get(code), prev.get(code)
        cw = c["weight"] if c else 0
        pw = p["weight"] if p else 0
        diff = round(cw - pw, 4)
        if diff == 0:
            continue
        changes.append({
            "stock_code": code,
            "stock_name": (c or p)["name"],
            "change_type": change_type(p, c, diff),
            "previous_weight": pw,
            "current_weight": cw,
            "weight_change": diff,
        })
    return changes
