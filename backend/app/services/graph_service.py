from typing import List, Dict, Any
from sqlalchemy import text
from sqlalchemy.orm import Session


class GraphService:
    def __init__(self, db: Session):
        self.db = db

    def execute_cypher(self, query: str, params: Dict[str, Any] = None) -> List[Dict]:
        set_path = "SET search_path = ag_catalog, \"$user\", public;"
        load_age = "LOAD 'age';"

        cypher_query = f"""
        SELECT * FROM cypher('etf_graph', $$
            {query}
        $$) as (result agtype);
        """

        full_query = f"{set_path} {load_age} {cypher_query}"

        try:
            result = self.db.execute(text(full_query), params or {})
            return [dict(row._mapping) for row in result]
        except Exception as e:
            print(f"Cypher query error: {e}")
            return []

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
