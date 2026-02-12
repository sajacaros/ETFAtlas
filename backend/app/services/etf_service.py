from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..models.etf import ETF


class ETFService:
    def __init__(self, db: Session):
        self.db = db

    def search_etfs(self, query: str, limit: int = 50) -> List[ETF]:
        stripped = query.replace(" ", "")
        rows = self.db.execute(
            text("""
                SELECT e.code
                FROM etfs e
                WHERE e.name ILIKE :like_q OR e.code ILIKE :like_q
                   OR REPLACE(e.name, ' ', '') ILIKE :like_stripped
                   OR LOWER(e.name) % LOWER(:q)
                ORDER BY
                    CASE
                        WHEN e.code ILIKE :q THEN 0
                        WHEN e.code ILIKE :like_q THEN 1
                        WHEN e.name ILIKE :q THEN 2
                        WHEN e.name ILIKE :starts_q THEN 3
                        WHEN REPLACE(e.name, ' ', '') ILIKE :starts_stripped THEN 4
                        WHEN e.name ILIKE :like_q THEN 5
                        WHEN REPLACE(e.name, ' ', '') ILIKE :like_stripped THEN 6
                        ELSE 7
                    END,
                    e.net_assets DESC NULLS LAST
                LIMIT :lim
            """),
            {
                "q": query,
                "like_q": f"%{query}%",
                "starts_q": f"{query}%",
                "like_stripped": f"%{stripped}%",
                "starts_stripped": f"{stripped}%",
                "lim": limit,
            }
        ).fetchall()
        if not rows:
            return []
        codes = [row.code for row in rows]
        etfs = self.db.query(ETF).filter(ETF.code.in_(codes)).all()
        # Preserve the order from the SQL query
        code_to_etf = {etf.code: etf for etf in etfs}
        return [code_to_etf[code] for code in codes if code in code_to_etf]

    def get_etf_by_code(self, code: str) -> Optional[ETF]:
        return self.db.query(ETF).filter(ETF.code == code).first()

