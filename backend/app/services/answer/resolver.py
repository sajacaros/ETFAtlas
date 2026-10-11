"""질문에 나온 ETF 이름을 코드로 바꾼다. 한 답변 안의 슬롯들이 같은 이름을 같은 ETF로 읽도록 결과를 공유한다."""
import re
import threading
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..graph_service import GraphService

# ETF 코드: 6자리 (숫자로 시작, 신규 상장은 영문이 섞인다: 0080G0)
CODE_RE = re.compile(r"(?<![0-9A-Z])(\d[0-9A-Z]{5})(?![0-9A-Z])")


def _normalize(name: str) -> str:
    return re.sub(r"\s+", "", name).lower()


class EntityResolver:
    """슬롯마다 다른 DB 세션(스레드)에서 부르므로 캐시는 잠금으로 보호한다."""

    def __init__(self):
        self._cache: Dict[str, Optional[Dict]] = {}
        self._lock = threading.Lock()

    def etf(self, db: Session, name: str) -> Optional[Dict]:
        """{code, name} 또는 None. 이름이 정확히 같으면 그것, 아니면 이름을 포함하는 것 중 순자산이 가장 큰 것."""
        key = _normalize(name)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        found = self._lookup(db, name)
        with self._lock:
            self._cache[key] = found
        return found

    def etfs(self, db: Session, names: List[str]) -> Tuple[List[Dict], List[str]]:
        """(찾은 ETF 목록 — 중복 제거, 순서 유지, 찾지 못한 이름 목록)."""
        found: List[Dict] = []
        missing: List[str] = []
        for name in names:
            etf = self.etf(db, name)
            if etf is None:
                missing.append(name)
            elif all(e["code"] != etf["code"] for e in found):
                found.append(etf)
        return found, missing

    @staticmethod
    def _lookup(db: Session, name: str) -> Optional[Dict]:
        graph = GraphService(db)
        code = CODE_RE.search(name.upper())
        if code:
            rows = graph.execute_cypher(
                "MATCH (e:ETF {code: $code}) RETURN {code: e.code, name: e.name}", {"code": code.group(1)}, raise_errors=True,
            )
            if rows:
                return GraphService.parse_agtype(rows[0]["result"])
        query = _normalize(CODE_RE.sub("", name)) if code else _normalize(name)
        if not query:
            return None
        rows = graph.execute_cypher(
            "MATCH (e:ETF) WHERE replace(toLower(e.name), ' ', '') CONTAINS $query "
            "RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC LIMIT 20",
            {"query": query}, raise_errors=True,
        )
        candidates = [GraphService.parse_agtype(r["result"]) for r in rows]
        exact = [c for c in candidates if _normalize(c["name"]) == query]
        return (exact or candidates or [None])[0]
