"""질문에 나온 ETF·종목 이름을 코드로 바꾼다. 한 답변 안의 슬롯들이 같은 이름을 같은 대상으로 읽도록 결과를 공유한다."""
import re
import threading
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..graph_service import GraphService

# 6자리 코드 (숫자로 시작, 신규 상장 ETF는 영문이 섞인다: 0080G0)
CODE_RE = re.compile(r"(?<![0-9A-Z])(\d[0-9A-Z]{5})(?![0-9A-Z])")

# 이름이 정확히 같지 않을 때 후보 중 무엇을 고를지: ETF는 순자산이 큰 것, 종목은 이름이 짧은 것(삼성전자 > 삼성전자우)
CANDIDATES = {
    "ETF": "MATCH (e:ETF) WHERE replace(toLower(e.name), ' ', '') CONTAINS $query "
           "RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC LIMIT 20",
    "Stock": "MATCH (e:Stock) WHERE replace(toLower(e.name), ' ', '') CONTAINS $query AND coalesce(e.is_etf, false) = false "
             "RETURN {code: e.code, name: e.name} LIMIT 50",
}


# GraphService는 파라미터를 쿼리 문자열에 치환하므로, LLM이 적은 이름에서 이름에 쓰이는 문자만 남긴다
UNSAFE_RE = re.compile(r"[^0-9A-Za-z가-힣&().+\-]")


def _normalize(name: str) -> str:
    return UNSAFE_RE.sub("", re.sub(r"\s+", "", name)).lower()


class EntityResolver:
    """슬롯마다 다른 DB 세션(스레드)에서 부르므로 캐시는 잠금으로 보호한다."""

    def __init__(self):
        self._cache: Dict[Tuple[str, str], Optional[Dict]] = {}
        self._lock = threading.Lock()

    def etf(self, db: Session, name: str) -> Optional[Dict]:
        """{code, name} 또는 None."""
        return self._resolve(db, "ETF", name)

    def stock(self, db: Session, name: str) -> Optional[Dict]:
        return self._resolve(db, "Stock", name)

    def etfs(self, db: Session, names: List[str]) -> Tuple[List[Dict], List[str]]:
        """(찾은 ETF 목록 — 중복 제거, 순서 유지, 찾지 못한 이름 목록)."""
        return self._resolve_all(db, "ETF", names)

    def stocks(self, db: Session, names: List[str]) -> Tuple[List[Dict], List[str]]:
        return self._resolve_all(db, "Stock", names)

    def _resolve_all(self, db: Session, label: str, names: List[str]) -> Tuple[List[Dict], List[str]]:
        found: List[Dict] = []
        missing: List[str] = []
        for name in names:
            entity = self._resolve(db, label, name)
            if entity is None:
                missing.append(name)
            elif all(e["code"] != entity["code"] for e in found):
                found.append(entity)
        return found, missing

    def _resolve(self, db: Session, label: str, name: str) -> Optional[Dict]:
        key = (label, _normalize(name))
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        found = self._lookup(db, label, name)
        with self._lock:
            self._cache[key] = found
        return found

    @staticmethod
    def _lookup(db: Session, label: str, name: str) -> Optional[Dict]:
        graph = GraphService(db)
        code = CODE_RE.search(name.upper())
        if code:
            rows = graph.execute_cypher(
                f"MATCH (e:{label} {{code: $code}}) RETURN {{code: e.code, name: e.name}}",
                {"code": code.group(1)}, raise_errors=True,
            )
            if rows:
                return GraphService.parse_agtype(rows[0]["result"])
        query = _normalize(CODE_RE.sub("", name)) if code else _normalize(name)
        if not query:
            return None
        rows = graph.execute_cypher(CANDIDATES[label], {"query": query}, raise_errors=True)
        candidates = [GraphService.parse_agtype(r["result"]) for r in rows]
        if label == "Stock":
            candidates.sort(key=lambda c: len(c["name"]))
        exact = [c for c in candidates if _normalize(c["name"]) == query]
        return (exact or candidates or [None])[0]
