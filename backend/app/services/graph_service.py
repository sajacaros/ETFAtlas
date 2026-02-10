import json
import re
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
        query = """
        MATCH (e1:ETF {code: $etf_code})-[:HOLDS]->(s:Stock)<-[:HOLDS]-(e2:ETF)
        WHERE e1 <> e2
        WITH e2, COUNT(s) as overlap
        WHERE overlap >= $min_overlap
        RETURN e2.code as etf_code, overlap
        ORDER BY overlap DESC
        LIMIT 10
        """
        return self.execute_cypher(query, {"etf_code": etf_code, "min_overlap": min_overlap})

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

    def get_all_tags(self) -> List[Dict]:
        """모든 Tag 노드 조회 (시장지수 제외), ETF 수 포함"""
        query = """
        MATCH (e:ETF)-[:TAGGED]->(t:Tag)
        WHERE t.name <> '시장지수'
        WITH t.name as name, count(e) as cnt
        RETURN {name: name, etf_count: cnt}
        ORDER BY cnt DESC
        """
        rows = self.execute_cypher(query)
        return [self.parse_agtype(row["result"]) for row in rows]

    def get_etfs_by_tag(self, tag_name: str) -> List[Dict]:
        """태그에 속한 ETF 목록 (이름, 코드)"""
        query = """
        MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: $tag_name})
        RETURN {code: e.code, name: e.name}
        ORDER BY e.name
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
