from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..models.etf import ETF


class ETFService:
    def __init__(self, db: Session):
        self.db = db

    def search_etfs(self, query: str, limit: int = 50) -> List[ETF]:
        stripped = query.replace(" ", "")
        # Every whitespace-separated token appears in the name, in any order
        # ("time 나스닥" -> "TIME 미국나스닥100액티브")
        tokens = query.split() or [query]
        token_params = {f"tok{i}": f"%{t}%" for i, t in enumerate(tokens)}
        all_tokens = " AND ".join(f"e.name ILIKE :{k}" for k in token_params)
        rows = self.db.execute(
            text(f"""
                SELECT e.code
                FROM etfs e
                WHERE e.name ILIKE :like_q OR e.code ILIKE :like_q
                   OR REPLACE(e.name, ' ', '') ILIKE :like_stripped
                   OR ({all_tokens})
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
                        WHEN {all_tokens} THEN 7
                        ELSE 8
                    END,
                    similarity(LOWER(e.name), LOWER(:q)) DESC,
                    e.name
                LIMIT :lim
            """),
            {
                "q": query,
                "like_q": f"%{query}%",
                "starts_q": f"{query}%",
                "like_stripped": f"%{stripped}%",
                "starts_stripped": f"{stripped}%",
                "lim": limit,
                **token_params,
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

