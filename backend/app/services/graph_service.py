import json
import logging
import re
from datetime import date, timedelta, timezone, datetime
from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain.weight_diff import diff_holdings
from app.utils import cypher

logger = logging.getLogger(__name__)

# ETF 목록 화면(ETFListItem)이 쓰는 필드
ETF_LIST_ITEM = "{code: e.code, name: e.name, net_assets: e.net_assets, return_1d: e.return_1d, return_1w: e.return_1w, return_1m: e.return_1m, market_cap_change_1w: e.market_cap_change_1w, active: e.active}"


class GraphService:
    def __init__(self, db: Session):
        self.db = db

    def execute_cypher(self, query: str, params: Dict[str, Any] = None, raise_errors: bool = True) -> List[Dict]:
        """Cypher 실행. 실패는 SAVEPOINT까지만 되돌려 같은 세션에 쌓인 다른 변경은 지키고, 기본으로 예외를 올린다.

        raise_errors=False는 "없음"으로 다뤄도 되는 조회만 쓴다.
        """
        set_path = "SET search_path = ag_catalog, \"$user\", public;"
        load_age = "LOAD 'age';"
        cypher_query = f"""
        SELECT * FROM cypher('etf_graph', $$
            {cypher.bind(query, params)}
        $$) as (result agtype);
        """

        full_query = f"{set_path} {load_age} {cypher_query}"

        # Escape colons so SQLAlchemy text() doesn't treat Cypher syntax
        # (e.g. :ETF, :TAGGED, :HOLDS) as bind parameters
        escaped_full = full_query.replace(":", "\\:")

        try:
            with self.db.begin_nested():
                result = self.db.execute(text(escaped_full))
                return [dict(row._mapping) for row in result]
        except Exception:
            logger.exception("Cypher query error")
            if raise_errors:
                raise
            return []

    def execute_cypher_readonly(self, query: str, timeout_ms: int = 10_000) -> List[Dict]:
        """외부(LLM)가 작성한 Cypher 실행. 별도 연결의 읽기 전용 트랜잭션 + 시간 제한 안에서 돌린다.

        쓰기·탈출 시도와 문법 오류는 예외로 올린다(호출 측이 메시지를 LLM에 돌려준다).
        """
        if "$$" in query or ";" in query:
            raise ValueError("쿼리에 '$$'나 ';'를 쓸 수 없습니다")
        raw = self.db.get_bind().raw_connection()
        try:
            cur = raw.cursor()
            # 인자 없이 execute하므로 psycopg2가 %를 치환하지 않는다
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            cur.execute("LOAD 'age'")
            cur.execute('SET LOCAL search_path = ag_catalog, "$user", public')
            cur.execute(f"SELECT * FROM cypher('etf_graph', $$ {query} $$) as (result agtype)")
            return [{"result": row[0]} for row in cur.fetchall()]
        finally:
            raw.rollback()
            raw.close()

    @staticmethod
    def parse_agtype(value: str) -> Any:
        """Parse an agtype string value to a Python object."""
        s = str(value).strip()
        # Remove ::type suffixes (e.g. ::numeric, ::vertex, ::edge)
        s = re.sub(r'::(?:numeric|integer|float|vertex|edge|path)\b', '', s)
        # Remove trailing ::text-like suffixes on quoted strings
        s = re.sub(r'"(\s*)::[\w]+', r'"\1', s)
        try:
            return json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return s

    def find_similar_etfs(self, etf_code: str, min_overlap: int = 5) -> List[Dict]:
        # 1) 입력 ETF의 비중 합 (정규화 기준)
        self_sum_query = """
        MATCH (:ETF {code: $etf_code})-[h1:CURRENT_HOLDS]->(s:Stock)
        WITH SUM(h1.weight) as self_sum
        RETURN {self_sum: self_sum}
        """
        self_sum_rows = self.execute_cypher(self_sum_query, {"etf_code": etf_code})
        if not self_sum_rows:
            return []
        self_sum = self.parse_agtype(self_sum_rows[0]["result"])["self_sum"] or 1.0

        # 2) 다른 ETF와의 비중 겹침 유사도 (각 ETF의 현재 구성종목 기준)
        query = """
        MATCH (e1:ETF {code: $etf_code})-[h1:CURRENT_HOLDS]->(s:Stock)<-[h2:CURRENT_HOLDS]-(e2:ETF)
        WHERE e1 <> e2
        WITH e2, COUNT(s) as overlap,
             SUM(CASE WHEN h1.weight < h2.weight THEN h1.weight ELSE h2.weight END) as similarity
        WHERE overlap >= $min_overlap
        RETURN {etf_code: e2.code, name: e2.name, overlap: overlap, similarity: similarity}
        ORDER BY similarity DESC
        LIMIT 5
        """
        rows = self.execute_cypher(query, {"etf_code": etf_code, "min_overlap": min_overlap})
        results = [self.parse_agtype(row["result"]) for row in rows]
        for r in results:
            r["similarity"] = round(r["similarity"] / self_sum * 100, 1)
        return results

    SORT_FIELDS = {
        "market_cap": "e.net_assets",
        "market_cap_change_1w": "e.market_cap_change_1w",
        "return_1d": "e.return_1d",
        "return_1w": "e.return_1w",
    }

    def get_latest_price_date(self) -> str | None:
        """AGE에서 가장 최근 ETF 가격 날짜 조회"""
        rows = self.execute_cypher("""
            MATCH (e:ETF)-[:HAS_PRICE]->(p:Price)
            RETURN p.date
            ORDER BY p.date DESC
            LIMIT 1
        """)
        if rows:
            raw = self.parse_agtype(rows[0]["result"])
            if raw:
                return str(raw)
        return None

    def get_top_etfs(self, limit: int = 20, sort: str = "market_cap", offset: int = 0,
                     active: bool | None = None) -> List[Dict]:
        """AGE Universe 내 ETF 목록 (정렬 기준 선택 가능, active로 액티브/패시브만 거를 수 있다)"""
        order_field = self.SORT_FIELDS.get(sort, "e.net_assets")
        active_filter = "" if active is None else " AND e.active = $active"
        cypher = f"""
        MATCH (e:ETF)
        WHERE {order_field} IS NOT NULL{active_filter}
        RETURN {ETF_LIST_ITEM}
        ORDER BY {order_field} DESC, e.code
        SKIP $offset
        LIMIT $limit
        """
        rows = self.execute_cypher(cypher, {"offset": offset, "limit": limit, "active": active})
        return [self.parse_agtype(row["result"]) for row in rows]

    def search_etfs_in_universe(self, query: str, limit: int = 20, offset: int = 0) -> List[Dict]:
        """AGE Universe 내 ETF 검색 (시가총액순, 대소문자 무시).
        띄어쓰기로 나눈 낱말이 모두 이름(공백 무시)이나 코드에 들어 있으면 찾는다 — 'kodex반도체', '반도체 kodex' 모두 'KODEX 반도체'"""
        tokens = [t for t in query.lower().split() if t][:5] or [query.lower()]
        params: Dict[str, Any] = {f"q{i}": t for i, t in enumerate(tokens)}
        where = " AND ".join(
            f"(replace(toLower(e.name), ' ', '') CONTAINS $q{i} OR toLower(e.code) CONTAINS $q{i})" for i in range(len(tokens))
        )
        cypher = """
        MATCH (e:ETF)
        WHERE """ + where + """
        RETURN """ + ETF_LIST_ITEM + """
        ORDER BY e.net_assets DESC, e.code
        SKIP $offset
        LIMIT $limit
        """
        rows = self.execute_cypher(cypher, {**params, "offset": offset, "limit": limit})
        return [self.parse_agtype(row["result"]) for row in rows]

    def get_etf_detail(self, code: str) -> Dict | None:
        """AGE에서 ETF 상세 정보 조회 (메타데이터 + 운용사)"""
        query = """
        MATCH (e:ETF {code: $code})
        OPTIONAL MATCH (e)-[:MANAGED_BY]->(c:Company)
        RETURN {code: e.code, name: e.name, net_assets: e.net_assets,
                expense_ratio: e.expense_ratio, issuer: c.name,
                description: e.description, base_index: e.base_index,
                listed_date: e.listed_date, dividend_cycle: e.dividend_cycle,
                dividend_yield: e.dividend_yield, dividend_per_share: e.dividend_per_share,
                component_count: e.component_count, active: e.active}
        """
        rows = self.execute_cypher(query, {"code": code})
        if rows:
            return self.parse_agtype(rows[0]["result"])
        return None

    def get_etf_names(self, codes: List[str]) -> Dict[str, str]:
        """AGE에서 ETF 코드→이름 매핑 조회"""
        if not codes:
            return {}
        rows = self.execute_cypher("MATCH (e:ETF) WHERE e.code IN $codes RETURN {code: e.code, name: e.name}",
                                   {"codes": list(codes)})
        return {r["code"]: r["name"] for r in map(self.parse_agtype, (row["result"] for row in rows))}

    PINNED_TAGS = ['코스피', '코스닥']

    def get_all_tags(self) -> List[Dict]:
        """모든 Tag 노드 조회 (시장지수 제외, 고정 태그 선두 배치), ETF 수 포함"""
        query = """
        MATCH (e:ETF)-[:TAGGED]->(t:Tag)
        WHERE t.name <> '시장지수'
        WITH t.name as name, count(e) as cnt
        RETURN {name: name, etf_count: cnt}
        ORDER BY cnt DESC
        """
        rows = self.execute_cypher(query)
        tags = [self.parse_agtype(row["result"]) for row in rows]
        pinned = [t for t in tags if t["name"] in self.PINNED_TAGS]
        rest = [t for t in tags if t["name"] not in self.PINNED_TAGS]
        return pinned + rest

    def get_etfs_by_tag(self, tag_name: str) -> List[Dict]:
        """태그에 속한 ETF 목록 (이름, 코드, 순자산)"""
        query = f"""
        MATCH (e:ETF)-[:TAGGED]->(t:Tag {{name: $tag_name}})
        RETURN {ETF_LIST_ITEM}
        ORDER BY e.net_assets DESC
        """
        rows = self.execute_cypher(query, {"tag_name": tag_name})
        return [self.parse_agtype(row["result"]) for row in rows]

    def get_holdings_by_etf_graph(self, etf_code: str) -> List[Dict]:
        """ETF 보유종목 TOP 10 (비중순)"""
        query = """
        MATCH (:ETF {code: $etf_code})-[h:CURRENT_HOLDS]->(s:Stock)
        RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight}
        ORDER BY h.weight DESC
        LIMIT 10
        """
        rows = self.execute_cypher(query, {"etf_code": etf_code})
        return [self.parse_agtype(row["result"]) for row in rows]

    def get_tags_by_etf(self, etf_code: str) -> List[str]:
        """특정 ETF에 연결된 태그 목록 조회"""
        query = """
        MATCH (e:ETF {code: $etf_code})-[:TAGGED]->(t:Tag)
        RETURN {name: t.name}
        ORDER BY t.name
        """
        rows = self.execute_cypher(query, {"etf_code": etf_code})
        return [self.parse_agtype(row["result"])["name"] for row in rows]

    def get_tags_of(self, etf_codes: List[str]) -> Dict[str, List[str]]:
        """ETF 코드 → 태그 이름 목록(이름순). 한 번의 쿼리로 가져온다."""
        if not etf_codes:
            return {}
        rows = self.execute_cypher("""
        MATCH (e:ETF)-[:TAGGED]->(t:Tag)
        WHERE e.code IN $codes
        RETURN {code: e.code, name: t.name}
        ORDER BY t.name
        """, {"codes": list(etf_codes)})
        tags: Dict[str, List[str]] = {}
        for row in rows:
            r = self.parse_agtype(row["result"])
            tags.setdefault(r["code"], []).append(r["name"])
        return tags

    # ── 태그 관리 (관리자) ──
    # ETF.manual_tags가 있으면 age_tagging DAG가 규칙/LLM 대신 그 값을 쓴다. 빈 리스트는 "태그 없음"으로 고정.

    def get_tag_names(self) -> List[str]:
        rows = self.execute_cypher("MATCH (t:Tag) RETURN t.name ORDER BY t.name")
        return [self.parse_agtype(row["result"]) for row in rows]

    def get_etf_tag_overview(self, etf_code: str | None = None) -> List[Dict]:
        """ETF와 현재 태그, 수동 지정 여부 (순자산순). etf_code를 주면 그 ETF만."""
        match = "MATCH (e:ETF {code: $etf_code})" if etf_code else "MATCH (e:ETF)"
        query = match + """
        OPTIONAL MATCH (e)-[:TAGGED]->(t:Tag)
        WITH e, collect(t.name) AS tags
        RETURN {code: e.code, name: e.name, net_assets: e.net_assets, tags: tags, manual_tags: e.manual_tags}
        ORDER BY e.net_assets DESC
        """
        items = []
        for row in self.execute_cypher(query, {"etf_code": etf_code} if etf_code else None):
            item = self.parse_agtype(row["result"])
            item["manual"] = item.pop("manual_tags", None) is not None
            items.append(item)
        return items

    def set_manual_tags(self, etf_code: str, tags: List[str] | None) -> None:
        """ETF 태그를 수동 지정하고 TAGGED를 즉시 교체한다. None이면 수동 지정 해제.

        해제 시 tagged_at도 지워 다음 age_tagging 실행이 신규 ETF처럼 다시 태깅하게 한다(그때까지 현재 태그 유지).
        """
        code = {"etf_code": etf_code}
        if tags is None:
            self.execute_cypher("MATCH (e:ETF {code: $etf_code}) REMOVE e.manual_tags REMOVE e.tagged_at RETURN e.code",
                                code, raise_errors=True)
            self.db.commit()
            return
        self.execute_cypher("MATCH (e:ETF {code: $etf_code}) SET e.manual_tags = $tags RETURN e.code",
                            {**code, "tags": tags}, raise_errors=True)
        self.execute_cypher("MATCH (e:ETF {code: $etf_code})-[r:TAGGED]->(:Tag) DELETE r RETURN 1",
                            code, raise_errors=True)
        for tag in tags:
            self.execute_cypher("""
                MATCH (e:ETF {code: $etf_code}), (t:Tag {name: $tag})
                CREATE (e)-[:TAGGED]->(t) RETURN 1
            """, {**code, "tag": tag}, raise_errors=True)
        self.db.commit()

    def get_etf_holdings_full(self, etf_code: str) -> List[Dict]:
        """ETF 전체 보유종목 (최신 날짜 기준)"""
        query = """
        MATCH (:ETF {code: $etf_code})-[h:CURRENT_HOLDS]->(s:Stock)
        RETURN {stock_code: s.code, stock_name: s.name,
                weight: h.weight, shares: h.shares, recorded_at: h.date}
        ORDER BY h.weight DESC, s.code
        """
        rows = self.execute_cypher(query, {"etf_code": etf_code})
        return [self.parse_agtype(row["result"]) for row in rows]

    def get_holdings_of(self, etf_codes: List[str]) -> Dict[str, List[Dict]]:
        """ETF 코드 → 전체 보유종목(get_etf_holdings_full 형식, 비중 큰 순). 한 번의 쿼리로 가져온다."""
        if not etf_codes:
            return {}
        rows = self.execute_cypher("""
        MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock)
        WHERE e.code IN $codes
        RETURN {etf_code: e.code, stock_code: s.code, stock_name: s.name,
                weight: h.weight, shares: h.shares, recorded_at: h.date}
        ORDER BY h.weight DESC, s.code
        """, {"codes": list(etf_codes)})
        holdings: Dict[str, List[Dict]] = {}
        for row in rows:
            r = self.parse_agtype(row["result"])
            holdings.setdefault(r.pop("etf_code"), []).append(r)
        return holdings

    def _get_holdings_at(self, etf_code: str, target_date: str = None) -> tuple[Dict[str, Dict], str | None]:
        """특정 날짜의 보유종목 조회. target_date 이전 가장 가까운 거래일 데이터를 사용.

        Returns: (holdings_dict, actual_date) 튜플
        """
        if target_date:
            # target_date 이전 가장 최근 거래일 찾기
            date_query = """
            MATCH (e:ETF {code: $etf_code})-[h:HOLDS]->(:Stock)
            WHERE h.date <= $target_date
            WITH DISTINCT h.date as d
            RETURN {date: d}
            ORDER BY d DESC
            LIMIT 1
            """
            date_rows = self.execute_cypher(date_query, {"etf_code": etf_code, "target_date": target_date})
        else:
            # 가장 최근 거래일 찾기
            date_query = """
            MATCH (e:ETF {code: $etf_code})-[h:HOLDS]->(:Stock)
            WITH DISTINCT h.date as d
            RETURN {date: d}
            ORDER BY d DESC
            LIMIT 1
            """
            date_rows = self.execute_cypher(date_query, {"etf_code": etf_code})

        if not date_rows:
            return {}, None

        exact_date = self.parse_agtype(date_rows[0]["result"])["date"]
        query = """
        MATCH (e:ETF {code: $etf_code})-[h:HOLDS]->(s:Stock)
        WHERE h.date = $exact_date
        RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight}
        """
        rows = self.execute_cypher(query, {"etf_code": etf_code, "exact_date": exact_date})
        holdings = {r["stock_code"]: r for r in [self.parse_agtype(row["result"]) for row in rows]}
        return holdings, exact_date

    def _get_prev_trading_date(self, etf_code: str, base_date: str = None) -> str | None:
        """base_date 이전의 가장 최근 거래일 조회. base_date=None이면 전체에서 두 번째로 최신."""
        if base_date:
            query = """
            MATCH (e:ETF {code: $etf_code})-[h:HOLDS]->(:Stock)
            WITH DISTINCT h.date as d
            WHERE d < $base_date
            RETURN {date: d}
            ORDER BY d DESC
            LIMIT 1
            """
            rows = self.execute_cypher(query, {"etf_code": etf_code, "base_date": base_date})
            dates = [self.parse_agtype(row["result"])["date"] for row in rows]
            return dates[0] if dates else None
        else:
            query = """
            MATCH (e:ETF {code: $etf_code})-[h:HOLDS]->(:Stock)
            WITH DISTINCT h.date as d
            RETURN {date: d}
            ORDER BY d DESC
            LIMIT 2
            """
            rows = self.execute_cypher(query, {"etf_code": etf_code})
            dates = [self.parse_agtype(row["result"])["date"] for row in rows]
            return dates[1] if len(dates) >= 2 else None

    def get_etf_holdings_changes(self, etf_code: str, period: str = "1d", base_date: str = None) -> tuple[List[Dict], str | None, str | None]:
        """ETF 보유종목 비중 변화. period: 1d/1w/1m, base_date: 기준일(None이면 마지막 거래일)

        Returns:
            (changes_list, current_date, previous_date)
        """
        from datetime import date, timedelta

        current, actual_date = self._get_holdings_at(etf_code, base_date)

        if not actual_date:
            return [], None, None

        ref = date.fromisoformat(actual_date)
        if period == "1d":
            prev_date = self._get_prev_trading_date(etf_code, actual_date)
        elif period == "1w":
            prev_date = (ref - timedelta(days=7)).isoformat()
        elif period == "1m":
            prev_date = (ref - timedelta(days=30)).isoformat()
        else:
            prev_date = self._get_prev_trading_date(etf_code, actual_date)

        previous, prev_actual = self._get_holdings_at(etf_code, prev_date) if prev_date else ({}, None)
        if not prev_actual:
            # 비교할 이전 데이터가 없으면(유니버스 신규 편입 첫날 등) 전 종목이 신규편입으로 보이므로 비교하지 않는다
            return [], actual_date, None

        changes = []
        all_codes = set(current.keys()) | set(previous.keys())
        for code in all_codes:
            curr = current.get(code)
            prev = previous.get(code)
            cw = float(curr["weight"]) if curr else 0
            pw = float(prev["weight"]) if prev else 0
            if curr and not prev:
                change_type = "added"
            elif prev and not curr:
                change_type = "removed"
            elif cw > pw:
                change_type = "increased"
            elif cw < pw:
                change_type = "decreased"
            else:
                change_type = "unchanged"
            changes.append({
                "stock_code": code,
                "stock_name": (curr or prev)["stock_name"],
                "change_type": change_type,
                "current_weight": cw,
                "previous_weight": pw,
                "weight_change": round(cw - pw, 4),
            })
        return sorted(changes, key=lambda x: x["current_weight"], reverse=True), actual_date, prev_actual

    def get_active_period_changes(self, current_date: str, days: int) -> tuple[List[Dict], str | None]:
        """액티브 ETF 전체의 current_date 보유종목을 days일 전(그날 이하 마지막 HOLDS)과 비교. 변화 없는 종목은 뺀다.

        weight_changes(직전 공시일 대비)와 같은 모양으로 돌려준다. 비교할 이전 HOLDS가 없는 ETF는 뺀다.
        Returns: (changes_list, 비교한 이전 날짜 중 가장 최근)
        """
        from collections import defaultdict
        from datetime import date, timedelta

        ref = (date.fromisoformat(current_date) - timedelta(days=days)).isoformat()
        prev_dates = {}
        for row in self.execute_cypher("""
            MATCH (e:ETF)-[h:HOLDS]->(:Stock)
            WHERE e.active = true AND h.date <= $ref
            WITH e.code as code, max(h.date) as d
            RETURN {etf_code: code, date: d}
        """, {"ref": ref}):
            data = self.parse_agtype(row["result"])
            prev_dates[data["etf_code"]] = data["date"]
        if not prev_dates:
            return [], None

        holdings = defaultdict(lambda: defaultdict(dict))  # etf_code -> date -> stock_code -> {name, weight}
        etf_names = {}

        def add_rows(rows):
            for row in rows:
                data = self.parse_agtype(row["result"])
                etf_names[data["etf_code"]] = data.get("etf_name") or data["etf_code"]
                holdings[data["etf_code"]][data["date"]][data["stock_code"]] = {
                    "name": data.get("stock_name") or data["stock_code"],
                    "weight": float(data["weight"]) if data.get("weight") else 0,
                }

        add_rows(self.execute_cypher("""
            MATCH (e:ETF)-[h:HOLDS {date: $date}]->(s:Stock)
            WHERE e.active = true
            RETURN {etf_code: e.code, etf_name: e.name, date: h.date,
                    stock_code: s.code, stock_name: s.name, weight: h.weight}
        """, {"date": current_date}))
        # ETF마다 이전 날짜가 다를 수 있어(며칠 빠진 ETF) 범위로 읽고 ETF별 날짜만 쓴다
        add_rows(self.execute_cypher("""
            MATCH (e:ETF)-[h:HOLDS]->(s:Stock)
            WHERE e.active = true AND h.date >= $since AND h.date <= $ref
            RETURN {etf_code: e.code, etf_name: e.name, date: h.date,
                    stock_code: s.code, stock_name: s.name, weight: h.weight}
        """, {"since": min(prev_dates.values()), "ref": ref}))

        changes = []
        compared = []
        for etf_code, by_date in holdings.items():
            today_h = by_date.get(current_date)
            prev_date = prev_dates.get(etf_code)
            prev_h = by_date.get(prev_date) if prev_date else None
            if not today_h or not prev_h:
                continue
            compared.append(prev_date)
            changes.extend({"etf_code": etf_code, "etf_name": etf_names[etf_code], "prev_date": prev_date, **change}
                           for change in diff_holdings(prev_h, today_h))
        return changes, max(compared, default=None)

    # ── Price query methods (AGE Price nodes) ──

    def get_etf_prices(self, etf_code: str, days: int = 365) -> List[Dict]:
        """기간별 ETF 가격 데이터 조회 (Price 노드)"""
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        query = """
        MATCH (e:ETF {code: $etf_code})-[:HAS_PRICE]->(p:Price)
        WHERE p.date >= $start_date AND p.date <= $end_date
        RETURN {date: p.date, open: p.open, high: p.high, low: p.low,
                close: p.close, volume: p.volume, market_cap: p.market_cap,
                net_assets: p.net_assets}
        ORDER BY p.date
        """
        rows = self.execute_cypher(query, {
            "etf_code": etf_code,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        })
        results = []
        for row in rows:
            parsed = self.parse_agtype(row["result"])
            # Ensure numeric fields are properly typed
            for key in ("open", "high", "low", "close"):
                if parsed.get(key) is not None:
                    parsed[key] = float(parsed[key])
            if parsed.get("volume") is not None:
                parsed["volume"] = int(parsed["volume"])
            if parsed.get("market_cap") is not None:
                parsed["market_cap"] = int(parsed["market_cap"])
            if parsed.get("net_assets") is not None:
                parsed["net_assets"] = int(parsed["net_assets"])
            results.append(parsed)
        return results

    def get_stock_prices(self, stock_code: str, days: int = 30) -> List[Dict]:
        """기간별 Stock 가격 데이터 조회 (Price 노드)"""
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        query = """
        MATCH (s:Stock {code: $stock_code})-[:HAS_PRICE]->(p:Price)
        WHERE p.date >= $start_date AND p.date <= $end_date
        RETURN {date: p.date, open: p.open, high: p.high, low: p.low,
                close: p.close, volume: p.volume, change_rate: p.change_rate}
        ORDER BY p.date
        """
        rows = self.execute_cypher(query, {
            "stock_code": stock_code,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        })
        results = []
        for row in rows:
            parsed = self.parse_agtype(row["result"])
            for key in ("open", "high", "low", "close", "change_rate"):
                if parsed.get(key) is not None:
                    parsed[key] = float(parsed[key])
            if parsed.get("volume") is not None:
                parsed["volume"] = int(parsed["volume"])
            results.append(parsed)
        return results

    # ── Watchlist methods (User)-[:WATCHES]->(ETF) direct relationship ──

    def get_user_watches(self, user_id: int) -> List[Dict]:
        """사용자의 즐겨찾기 ETF 목록 조회 (User)-[:WATCHES]->(ETF)"""
        query = """
        MATCH (u:User {user_id: $user_id})-[r:WATCHES]->(e:ETF)
        RETURN {etf_code: e.code, etf_name: e.name, added_at: r.added_at}
        ORDER BY r.added_at DESC
        """
        rows = self.execute_cypher(query, {"user_id": user_id})
        return [self.parse_agtype(row["result"]) for row in rows]

    def get_watched_etfs(self, user_id: int) -> List[Dict]:
        """사용자의 즐겨찾기 ETF 목록 (ETFListItem 형식)"""
        query = f"""
        MATCH (u:User {{user_id: $user_id}})-[r:WATCHES]->(e:ETF)
        RETURN {ETF_LIST_ITEM}
        ORDER BY e.net_assets DESC
        """
        rows = self.execute_cypher(query, {"user_id": user_id})
        return [self.parse_agtype(row["result"]) for row in rows]

    def get_watched_codes(self, user_id: int) -> List[str]:
        """사용자의 즐겨찾기 ETF 코드 목록"""
        query = """
        MATCH (u:User {user_id: $user_id})-[:WATCHES]->(e:ETF)
        RETURN {code: e.code}
        """
        rows = self.execute_cypher(query, {"user_id": user_id})
        return [self.parse_agtype(row["result"])["code"] for row in rows]

    def is_watching(self, user_id: int, etf_code: str) -> bool:
        """특정 ETF 즐겨찾기 여부 확인"""
        query = """
        MATCH (u:User {user_id: $user_id})-[:WATCHES]->(e:ETF {code: $etf_code})
        RETURN {exists: true}
        """
        rows = self.execute_cypher(query, {"user_id": user_id, "etf_code": etf_code})
        return len(rows) > 0

    def add_watch(self, user_id: int, etf_code: str) -> Dict:
        """ETF 즐겨찾기 추가 (User)-[:WATCHES]->(ETF)"""
        # ETF 존재 확인
        etf_query = """
        MATCH (e:ETF {code: $etf_code})
        RETURN {code: e.code, name: e.name}
        """
        etf_rows = self.execute_cypher(etf_query, {"etf_code": etf_code})
        if not etf_rows:
            return {"error": "etf_not_found"}

        # 중복 확인
        if self.is_watching(user_id, etf_code):
            return {"error": "already_exists"}

        # WATCHES 엣지 생성
        now = datetime.now(timezone.utc).isoformat()
        add_query = """
        MERGE (u:User {user_id: $user_id})
        WITH u
        MATCH (e:ETF {code: $etf_code})
        CREATE (u)-[:WATCHES {added_at: $now}]->(e)
        RETURN {etf_code: e.code, etf_name: e.name}
        """
        rows = self.execute_cypher(add_query, {
            "user_id": user_id,
            "etf_code": etf_code,
            "now": now,
        })
        self.db.commit()
        if rows:
            return self.parse_agtype(rows[0]["result"])
        return {}

    def remove_watch(self, user_id: int, etf_code: str) -> bool:
        """ETF 즐겨찾기 해제"""
        query = """
        MATCH (u:User {user_id: $user_id})-[r:WATCHES]->(e:ETF {code: $etf_code})
        DELETE r
        RETURN {deleted: true}
        """
        rows = self.execute_cypher(query, {
            "user_id": user_id,
            "etf_code": etf_code,
        })
        self.db.commit()
        return len(rows) > 0

def node(graph: GraphService, cypher: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """{...} 맵 하나를 RETURN하는 쿼리의 결과 행. DB 오류를 "데이터 없음"으로 삼키지 않고 슬롯 실패로 드러낸다."""
    return [GraphService.parse_agtype(r["result"]) for r in graph.execute_cypher(cypher, params, raise_errors=True)]
