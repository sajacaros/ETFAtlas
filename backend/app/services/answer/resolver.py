"""질문에 나온 ETF·종목 이름을 코드로 바꾼다. 한 답변 안의 슬롯들이 같은 이름을 같은 대상으로 읽도록 결과를 공유한다."""
import re
import threading
from typing import Dict, List, Optional, Tuple, Union

from sqlalchemy import func
from sqlalchemy.orm import Session

from ...models.etf import ETF
from ..graph_service import GraphService

# 6자리 코드 (숫자로 시작, 신규 상장 ETF는 영문이 섞인다: 0080G0)
CODE_RE = re.compile(r"(?<![0-9A-Z])(\d[0-9A-Z]{5})(?![0-9A-Z])")

# 이름이 정확히 같지 않을 때: ETF는 후보가 둘 이상이면 고르지 않고 되묻는다(AmbiguousETF, 순자산 큰 순으로 보여준다).
# 종목은 이름이 짧은 것을 고른다(삼성전자 > 삼성전자우)
CANDIDATE_LIMIT = 20
CANDIDATES = {
    "ETF": "MATCH (e:ETF) WHERE replace(toLower(e.name), ' ', '') CONTAINS $query "
           f"RETURN {{code: e.code, name: e.name, net_assets: e.net_assets}} ORDER BY e.net_assets DESC LIMIT {CANDIDATE_LIMIT}",
    "Stock": "MATCH (e:Stock) WHERE replace(toLower(e.name), ' ', '') CONTAINS $query AND coalesce(e.is_etf, false) = false "
             "RETURN {code: e.code, name: e.name} LIMIT 50",
}


# GraphService는 파라미터를 쿼리 문자열에 치환하므로, LLM이 적은 이름에서 이름에 쓰이는 문자만 남긴다
UNSAFE_RE = re.compile(r"[^0-9A-Za-z가-힣&().+\-]")


def _normalize(name: str) -> str:
    return UNSAFE_RE.sub("", re.sub(r"\s+", "", name)).lower()


class AmbiguousETF(Exception):
    """이름에 맞는 ETF가 여럿이라 하나로 정할 수 없다. 스킬은 이걸 받아 후보를 보여주고 되묻는다."""

    def __init__(self, name: str, candidates: List[Dict]):
        super().__init__(f"ETF가 여러 개입니다: {name}")
        self.name = name
        self.candidates = candidates  # [{code, name, net_assets}] 순자산 큰 순, 최대 CANDIDATE_LIMIT개


class UnmanagedETF(Exception):
    """ETF 목록(RDB etfs, 상장 ETF 전체)에는 있지만 ETF Atlas가 관리하지 않는 ETF — 그래프에 없어 구성종목·가격 데이터가 없다.
    어떤 ETF를 관리하는지는 수집 DAG의 유니버스 조건이 정한다. 스킬은 이걸 받아 관리하지 않는 ETF라고 알린다."""

    def __init__(self, etf: Dict):
        super().__init__(f"관리하지 않는 ETF입니다: {etf['name']}")
        self.etf = etf  # {code, name}


class EntityResolver:
    """슬롯마다 다른 DB 세션(스레드)에서 부르므로 캐시는 잠금으로 보호한다."""

    def __init__(self):
        self._cache: Dict[Tuple[str, str], Union[Optional[Dict], AmbiguousETF, UnmanagedETF]] = {}
        self._lock = threading.Lock()

    def etf(self, db: Session, name: str) -> Optional[Dict]:
        """{code, name} 또는 None. 이름에 맞는 ETF가 여럿이고 정확히 같은 이름이 없으면 AmbiguousETF,
        관리하지 않는 ETF의 코드나 정확한 이름이면 UnmanagedETF."""
        return self._resolve(db, "ETF", name)

    def stock(self, db: Session, name: str) -> Optional[Dict]:
        return self._resolve(db, "Stock", name)

    def etfs(self, db: Session, names: List[str]) -> Tuple[List[Dict], List[str]]:
        """(찾은 ETF 목록 — 중복 제거, 순서 유지, 찾지 못한 이름 목록). 관리하지 않는 ETF는 찾지 못한 목록에 그렇다고 적는다."""
        return self._resolve_all(db, "ETF", names)

    def stocks(self, db: Session, names: List[str]) -> Tuple[List[Dict], List[str]]:
        return self._resolve_all(db, "Stock", names)

    def _resolve_all(self, db: Session, label: str, names: List[str]) -> Tuple[List[Dict], List[str]]:
        found: List[Dict] = []
        missing: List[str] = []
        unmanaged: List[UnmanagedETF] = []
        for name in names:
            try:
                entity = self._resolve(db, label, name)
            except UnmanagedETF as e:
                unmanaged.append(e)
                missing.append(f"{e.etf['name']}(관리하지 않는 ETF)")
                continue
            if entity is None:
                missing.append(name)
            elif all(e["code"] != entity["code"] for e in found):
                found.append(entity)
        if len(names) == 1 and unmanaged:  # 하나만 물었으면 '찾지 못했다'가 아니라 단일 ETF와 같은 안내로
            raise unmanaged[0]
        return found, missing

    def _resolve(self, db: Session, label: str, name: str) -> Optional[Dict]:
        key = (label, _normalize(name))
        with self._lock:
            cached = self._cache.get(key, ...)
        if cached is ...:
            try:
                cached = self._lookup(db, label, name)
            except (AmbiguousETF, UnmanagedETF) as e:
                cached = e
            with self._lock:
                self._cache[key] = cached
        if isinstance(cached, Exception):
            raise cached
        return cached

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
            unmanaged = _unmanaged_etf(db, code.group(1), "") if label == "ETF" else None
            if unmanaged:
                raise UnmanagedETF(unmanaged)
        query = _normalize(CODE_RE.sub("", name)) if code else _normalize(name)
        if not query:
            return None
        rows = graph.execute_cypher(CANDIDATES[label], {"query": query}, raise_errors=True)
        candidates = [GraphService.parse_agtype(r["result"]) for r in rows]
        if label == "Stock":
            candidates.sort(key=lambda c: len(c["name"]))
        exact = [c for c in candidates if _normalize(c["name"]) == query]
        if label == "ETF" and not exact:
            # 정확히 같은 이름이 관리하지 않는 ETF면 그게 사용자가 말한 ETF다 (비슷한 이름의 관리 ETF로 바꾸거나 되묻지 않는다)
            unmanaged = _unmanaged_etf(db, None, query)
            if unmanaged:
                raise UnmanagedETF(unmanaged)
            if len(candidates) > 1:
                raise AmbiguousETF(name, candidates)
        found = (exact or candidates or [None])[0]
        return {"code": found["code"], "name": found["name"]} if found else None


def _unmanaged_etf(db: Session, code: Optional[str], query: str) -> Optional[Dict]:
    """그래프에 없는(관리하지 않는) ETF를 상장 ETF 목록(RDB)에서 코드나 정확한 이름(공백·대소문자 무시)으로. {code, name} 또는 None.
    그래프에서 먼저 찾고 못 찾았을 때만 부르므로, 여기서 나온 ETF는 관리하지 않는 ETF다."""
    if code:
        row = db.query(ETF).filter(ETF.code == code).first()
    else:
        row = db.query(ETF).filter(func.lower(func.replace(ETF.name, " ", "")) == query).first()
    return {"code": row.code, "name": row.name} if row else None
