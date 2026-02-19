import json
import re
from datetime import date, timedelta, timezone, datetime
from decimal import Decimal
from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session


class GraphService:
    def __init__(self, db: Session):
        self.db = db

    def execute_cypher(self, query: str, params: Dict[str, Any] = None) -> List[Dict]:
        set_path = "SET search_path = ag_catalog, \"$user\", public;"
        load_age = "LOAD 'age';"

        # Substitute $param with actual values in Cypher query
        cypher = query
        if params:
            for key, value in params.items():
                if isinstance(value, str):
                    escaped = value.replace("'", "\\'")
                    cypher = cypher.replace(f"${key}", f"'{escaped}'")
                elif isinstance(value, (int, float)):
                    cypher = cypher.replace(f"${key}", str(value))

        cypher_query = f"""
        SELECT * FROM cypher('etf_graph', $$
            {cypher}
        $$) as (result agtype);
        """

        full_query = f"{set_path} {load_age} {cypher_query}"

        # Escape colons so SQLAlchemy text() doesn't treat Cypher syntax
        # (e.g. :ETF, :TAGGED, :HOLDS) as bind parameters
        escaped_full = full_query.replace(":", "\\:")

        try:
            result = self.db.execute(text(escaped_full))
            return [dict(row._mapping) for row in result]
        except Exception as e:
            print(f"Cypher query error: {e}")
            self.db.rollback()
            return []

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

    def create_etf_stock_relationship(self, etf_code: str, stock_code: str, weight: float):
        query = """
        MERGE (e:ETF {code: $etf_code})
        MERGE (s:Stock {code: $stock_code})
        MERGE (e)-[r:HOLDS]->(s)
        SET r.weight = $weight
        RETURN e, r, s
        """
        return self.execute_cypher(query, {
            "etf_code": etf_code,
            "stock_code": stock_code,
            "weight": weight
        })

    def find_etfs_holding_stock(self, stock_code: str) -> List[Dict]:
        query = """
        MATCH (e:ETF)-[r:HOLDS]->(s:Stock {code: $stock_code})
        RETURN e.code as etf_code, r.weight as weight
        ORDER BY r.weight DESC
        """
        return self.execute_cypher(query, {"stock_code": stock_code})

    def find_similar_etfs(self, etf_code: str, min_overlap: int = 5) -> List[Dict]:
        # 1) 입력 ETF의 비중 합 (정규화 기준)
        self_sum_query = """
        MATCH (e1:ETF {code: $etf_code})-[h1:HOLDS]->(s:Stock)
        WITH e1, s, h1 ORDER BY h1.date DESC
        WITH e1, s, head(collect(h1)) as latest1
        WITH SUM(latest1.weight) as self_sum
        RETURN {self_sum: self_sum}
        """
        self_sum_rows = self.execute_cypher(self_sum_query, {"etf_code": etf_code})
        self_sum = self.parse_agtype(self_sum_rows[0]["result"])["self_sum"] if self_sum_rows else 1.0

        # 2) 다른 ETF와의 비중 겹침 유사도
        query = """
        MATCH (e1:ETF {code: $etf_code})-[h1:HOLDS]->(s:Stock)
        WITH e1, s, h1 ORDER BY h1.date DESC
        WITH e1, s, head(collect(h1)) as latest1
        MATCH (e2:ETF)-[h2:HOLDS]->(s) WHERE e1 <> e2
        WITH e2, s, latest1, h2 ORDER BY h2.date DESC
        WITH e2, s, latest1, head(collect(h2)) as latest2
        WITH e2, COUNT(s) as overlap,
             SUM(CASE WHEN latest1.weight < latest2.weight THEN latest1.weight ELSE latest2.weight END) as similarity
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

    def find_common_stocks(self, etf_code1: str, etf_code2: str) -> List[Dict]:
        query = """
        MATCH (e1:ETF {code: $etf_code1})-[:HOLDS]->(s:Stock)<-[:HOLDS]-(e2:ETF {code: $etf_code2})
        RETURN s.code as stock_code
        """
        return self.execute_cypher(query, {"etf_code1": etf_code1, "etf_code2": etf_code2})

    def get_stock_exposure(self, stock_code: str) -> Dict:
        query = """
        MATCH (e:ETF)-[r:HOLDS]->(s:Stock {code: $stock_code})
        RETURN COUNT(e) as etf_count, AVG(r.weight) as avg_weight
        """
        result = self.execute_cypher(query, {"stock_code": stock_code})
        if result:
            return result[0]
        return {"etf_count": 0, "avg_weight": 0}

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

    def get_top_etfs(self, limit: int = 20, sort: str = "market_cap") -> List[Dict]:
        """AGE Universe 내 ETF 목록 (정렬 기준 선택 가능)"""
        order_field = self.SORT_FIELDS.get(sort, "e.net_assets")
        cypher = f"""
        MATCH (e:ETF)
        WHERE {order_field} IS NOT NULL
        RETURN {{code: e.code, name: e.name, net_assets: e.net_assets, return_1d: e.return_1d, return_1w: e.return_1w, return_1m: e.return_1m, market_cap_change_1w: e.market_cap_change_1w}}
        ORDER BY {order_field} DESC
        LIMIT $limit
        """
        rows = self.execute_cypher(cypher, {"limit": limit})
        return [self.parse_agtype(row["result"]) for row in rows]

    def search_etfs_in_universe(self, query: str, limit: int = 20) -> List[Dict]:
        """AGE Universe 내 ETF 검색 (시가총액순, 대소문자 무시)"""
        cypher = """
        MATCH (e:ETF)
        WHERE toLower(e.name) CONTAINS toLower($query) OR toLower(e.code) CONTAINS toLower($query)
        RETURN {code: e.code, name: e.name, net_assets: e.net_assets, return_1d: e.return_1d, return_1w: e.return_1w, return_1m: e.return_1m, market_cap_change_1w: e.market_cap_change_1w}
        ORDER BY e.net_assets DESC
        LIMIT $limit
        """
        rows = self.execute_cypher(cypher, {"query": query, "limit": limit})
        return [self.parse_agtype(row["result"]) for row in rows]

    def get_etf_detail(self, code: str) -> Dict | None:
        """AGE에서 ETF 상세 정보 조회 (메타데이터 + 운용사)"""
        query = """
        MATCH (e:ETF {code: $code})
        OPTIONAL MATCH (e)-[:MANAGED_BY]->(c:Company)
        RETURN {code: e.code, name: e.name, net_assets: e.net_assets,
                expense_ratio: e.expense_ratio, issuer: c.name}
        """
        rows = self.execute_cypher(query, {"code": code})
        if rows:
            return self.parse_agtype(rows[0]["result"])
        return None

    def get_etf_names(self, codes: List[str]) -> Dict[str, str]:
        """AGE에서 ETF 코드→이름 매핑 조회"""
        if not codes:
            return {}
        # AGE는 IN 연산자 미지원 → 개별 조회 대신 전체 스캔 + 필터
        query = """
        MATCH (e:ETF)
        RETURN {code: e.code, name: e.name}
        """
        rows = self.execute_cypher(query)
        result = {}
        code_set = set(codes)
        for row in rows:
            parsed = self.parse_agtype(row["result"])
            if parsed["code"] in code_set:
                result[parsed["code"]] = parsed["name"]
        return result

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
        query = """
        MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: $tag_name})
        RETURN {code: e.code, name: e.name, net_assets: e.net_assets, return_1d: e.return_1d, return_1w: e.return_1w, return_1m: e.return_1m, market_cap_change_1w: e.market_cap_change_1w}
        ORDER BY e.net_assets DESC
        """
        rows = self.execute_cypher(query, {"tag_name": tag_name})
        return [self.parse_agtype(row["result"]) for row in rows]

    def get_holdings_by_etf_graph(self, etf_code: str) -> List[Dict]:
        """ETF 보유종목 TOP 10 (비중순)"""
        query = """
        MATCH (e:ETF {code: $etf_code})-[h:HOLDS]->(s:Stock)
        WITH s, h ORDER BY h.date DESC
        WITH s, head(collect(h)) as latest
        RETURN {stock_code: s.code, stock_name: s.name, weight: latest.weight}
        ORDER BY latest.weight DESC
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

    def get_etf_holdings_full(self, etf_code: str) -> List[Dict]:
        """ETF 전체 보유종목 (최신 날짜 기준)"""
        query = """
        MATCH (e:ETF {code: $etf_code})-[h:HOLDS]->(s:Stock)
        WITH s, h ORDER BY h.date DESC
        With s, head(collect(h)) as latest
        RETURN {stock_code: s.code, stock_name: s.name,
                weight: latest.weight, shares: latest.shares, recorded_at: latest.date}
        ORDER BY latest.weight DESC
        """
        rows = self.execute_cypher(query, {"etf_code": etf_code})
        return [self.parse_agtype(row["result"]) for row in rows]

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

    def get_etf_holdings_changes(self, etf_code: str, period: str = "1d", base_date: str = None) -> List[Dict]:
        """ETF 보유종목 비중 변화. period: 1d/1w/1m, base_date: 기준일(None이면 마지막 거래일)"""
        from datetime import date, timedelta

        current, actual_date = self._get_holdings_at(etf_code, base_date)

        if not actual_date:
            return []

        ref = date.fromisoformat(actual_date)
        if period == "1d":
            prev_date = self._get_prev_trading_date(etf_code, actual_date)
        elif period == "1w":
            prev_date = (ref - timedelta(days=7)).isoformat()
        elif period == "1m":
            prev_date = (ref - timedelta(days=30)).isoformat()
        else:
            prev_date = self._get_prev_trading_date(etf_code, actual_date)

        previous, _ = self._get_holdings_at(etf_code, prev_date) if prev_date else ({}, None)

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
        return sorted(changes, key=lambda x: x["current_weight"], reverse=True)

    def get_company_etfs(self, company_name: str = None) -> List[Dict]:
        """운용사별 ETF 목록 조회. company_name 없으면 전체 운용사 목록 + ETF 수 반환"""
        if company_name:
            query = """
            MATCH (e:ETF)-[:MANAGED_BY]->(c:Company)
            WHERE c.name CONTAINS $name
            RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, company: c.name}
            ORDER BY e.name
            """
            rows = self.execute_cypher(query, {"name": company_name})
            return [self.parse_agtype(row["result"]) for row in rows]
        else:
            query = """
            MATCH (e:ETF)-[:MANAGED_BY]->(c:Company)
            WITH c.name as company, count(e) as cnt
            RETURN {company: company, etf_count: cnt}
            ORDER BY cnt DESC
            """
            rows = self.execute_cypher(query)
            return [self.parse_agtype(row["result"]) for row in rows]

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

    def get_etf_market_cap(self, etf_code: str, days: int = 365) -> List[Dict]:
        """시가총액/순자산 조회 (Price 노드)"""
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        query = """
        MATCH (e:ETF {code: $etf_code})-[:HAS_PRICE]->(p:Price)
        WHERE p.date >= $start_date AND p.date <= $end_date
        RETURN {date: p.date, market_cap: p.market_cap,
                net_assets: p.net_assets, close_price: p.close}
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
            if parsed.get("close_price") is not None:
                parsed["close_price"] = float(parsed["close_price"])
            if parsed.get("market_cap") is not None:
                parsed["market_cap"] = int(parsed["market_cap"])
            if parsed.get("net_assets") is not None:
                parsed["net_assets"] = int(parsed["net_assets"])
            results.append(parsed)
        return results

    def get_latest_close_prices(self, tickers: List[str]) -> Dict[str, Decimal]:
        """당일(KST) 종가 조회 — PriceService에서 호출"""
        today_kst = datetime.now(timezone(timedelta(hours=9))).date()
        today_str = today_kst.isoformat()

        prices: Dict[str, Decimal] = {}
        for ticker in tickers:
            # Try ETF first
            query = """
            MATCH (e:ETF {code: $ticker})-[:HAS_PRICE]->(p:Price {date: $today})
            RETURN {close: p.close}
            """
            rows = self.execute_cypher(query, {"ticker": ticker, "today": today_str})
            if rows:
                parsed = self.parse_agtype(rows[0]["result"])
                if parsed.get("close") is not None:
                    prices[ticker] = Decimal(str(parsed["close"]))
                    continue
            # Try Stock
            query = """
            MATCH (s:Stock {code: $ticker})-[:HAS_PRICE]->(p:Price {date: $today})
            RETURN {close: p.close}
            """
            rows = self.execute_cypher(query, {"ticker": ticker, "today": today_str})
            if rows:
                parsed = self.parse_agtype(rows[0]["result"])
                if parsed.get("close") is not None:
                    prices[ticker] = Decimal(str(parsed["close"]))
        return prices

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
        """사용자의 즐겨찾기 ETF 목록 (UniverseETFResponse 형식)"""
        query = """
        MATCH (u:User {user_id: $user_id})-[r:WATCHES]->(e:ETF)
        RETURN {code: e.code, name: e.name, net_assets: e.net_assets, return_1d: e.return_1d, return_1w: e.return_1w, return_1m: e.return_1m, market_cap_change_1w: e.market_cap_change_1w}
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

    # ── User role methods ──

    def get_user_role(self, user_id: int) -> str:
        """유저 역할 조회. 없으면 'member'."""
        query = """
        MATCH (u:User {user_id: $user_id})
        RETURN {role: u.role}
        """
        rows = self.execute_cypher(query, {"user_id": user_id})
        if rows:
            result = self.parse_agtype(rows[0]["result"])
            return result.get("role") or "member"
        return "member"

    def set_user_role(self, user_id: int, role: str):
        """유저 역할 설정."""
        query = """
        MERGE (u:User {user_id: $user_id})
        SET u.role = $role
        RETURN {role: u.role}
        """
        self.execute_cypher(query, {"user_id": user_id, "role": role})
        self.db.commit()

    def get_admin_user_ids(self) -> list[int]:
        """admin 역할 유저 ID 목록."""
        query = """
        MATCH (u:User {role: 'admin'})
        RETURN {user_id: u.user_id}
        """
        rows = self.execute_cypher(query, {})
        return [self.parse_agtype(row["result"])["user_id"] for row in rows]

    def get_latest_close_prices_fallback(self, tickers: List[str]) -> Dict[str, Decimal]:
        """최신 종가 폴백 조회 (날짜 무관, 가장 최근 Price) — PriceService에서 호출"""
        prices: Dict[str, Decimal] = {}
        for ticker in tickers:
            # Try ETF first
            query = """
            MATCH (e:ETF {code: $ticker})-[:HAS_PRICE]->(p:Price)
            RETURN {close: p.close}
            ORDER BY p.date DESC
            LIMIT 1
            """
            rows = self.execute_cypher(query, {"ticker": ticker})
            if rows:
                parsed = self.parse_agtype(rows[0]["result"])
                if parsed.get("close") is not None:
                    prices[ticker] = Decimal(str(parsed["close"]))
                    continue
            # Try Stock
            query = """
            MATCH (s:Stock {code: $ticker})-[:HAS_PRICE]->(p:Price)
            RETURN {close: p.close}
            ORDER BY p.date DESC
            LIMIT 1
            """
            rows = self.execute_cypher(query, {"ticker": ticker})
            if rows:
                parsed = self.parse_agtype(rows[0]["result"])
                if parsed.get("close") is not None:
                    prices[ticker] = Decimal(str(parsed["close"]))
        return prices
