from typing import List, Optional
from datetime import date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, text
from ..models.etf import ETF, Stock, ETFHolding, ETFPrice


class ETFService:
    def __init__(self, db: Session):
        self.db = db

    def search_etfs(self, query: str, limit: int = 50) -> List[ETF]:
        stripped = query.replace(" ", "")
        rows = self.db.execute(
            text("""
                SELECT e.code
                FROM etfs e
                JOIN etf_universe u ON e.code = u.code AND u.is_active = TRUE
                WHERE e.name ILIKE :like_q OR e.code ILIKE :like_q
                   OR REPLACE(e.name, ' ', '') ILIKE :like_stripped
                   OR LOWER(e.name) % LOWER(:q)
                ORDER BY
                    e.net_assets DESC NULLS LAST
                LIMIT :lim
            """),
            {"q": query, "like_q": f"%{query}%", "like_stripped": f"%{stripped}%", "lim": limit}
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

    def get_etf_holdings(self, etf_id: int, recorded_date: Optional[date] = None) -> List[dict]:
        query = self.db.query(
            ETFHolding,
            Stock.code.label("stock_code"),
            Stock.name.label("stock_name"),
            Stock.sector
        ).join(Stock, ETFHolding.stock_id == Stock.id).filter(ETFHolding.etf_id == etf_id)

        if recorded_date:
            query = query.filter(ETFHolding.recorded_at == recorded_date)
        else:
            latest_date = self.db.query(func.max(ETFHolding.recorded_at)).filter(
                ETFHolding.etf_id == etf_id
            ).scalar()
            if latest_date:
                query = query.filter(ETFHolding.recorded_at == latest_date)

        results = query.order_by(desc(ETFHolding.weight)).all()
        return [
            {
                "stock_code": r.stock_code,
                "stock_name": r.stock_name,
                "sector": r.sector,
                "weight": float(r.ETFHolding.weight) if r.ETFHolding.weight else 0,
                "shares": r.ETFHolding.shares,
                "recorded_at": r.ETFHolding.recorded_at
            }
            for r in results
        ]

    def get_holdings_changes(self, etf_id: int, days: int = 30) -> List[dict]:
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        current = self.get_etf_holdings(etf_id, end_date)
        previous = self.get_etf_holdings(etf_id, start_date)

        current_dict = {h["stock_code"]: h for h in current}
        previous_dict = {h["stock_code"]: h for h in previous}

        changes = []
        all_codes = set(current_dict.keys()) | set(previous_dict.keys())

        for code in all_codes:
            curr = current_dict.get(code)
            prev = previous_dict.get(code)

            if curr and not prev:
                changes.append({
                    "stock_code": code,
                    "stock_name": curr["stock_name"],
                    "change_type": "added",
                    "current_weight": curr["weight"],
                    "previous_weight": 0,
                    "weight_change": curr["weight"]
                })
            elif prev and not curr:
                changes.append({
                    "stock_code": code,
                    "stock_name": prev["stock_name"],
                    "change_type": "removed",
                    "current_weight": 0,
                    "previous_weight": prev["weight"],
                    "weight_change": -prev["weight"]
                })
            elif curr and prev and curr["weight"] != prev["weight"]:
                change = curr["weight"] - prev["weight"]
                changes.append({
                    "stock_code": code,
                    "stock_name": curr["stock_name"],
                    "change_type": "increased" if change > 0 else "decreased",
                    "current_weight": curr["weight"],
                    "previous_weight": prev["weight"],
                    "weight_change": change
                })

        return sorted(changes, key=lambda x: abs(x["weight_change"]), reverse=True)

    def get_etf_prices(self, etf_code: str, days: int = 365) -> List[dict]:
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        prices = self.db.query(ETFPrice).filter(
            ETFPrice.etf_code == etf_code,
            ETFPrice.date >= start_date,
            ETFPrice.date <= end_date
        ).order_by(ETFPrice.date).all()

        return [
            {
                "date": p.date.isoformat(),
                "open": float(p.open_price) if p.open_price else None,
                "high": float(p.high_price) if p.high_price else None,
                "low": float(p.low_price) if p.low_price else None,
                "close": float(p.close_price) if p.close_price else None,
                "volume": p.volume
            }
            for p in prices
        ]

    def find_etfs_by_stock(self, stock_code: str) -> List[dict]:
        stock = self.db.query(Stock).filter(Stock.code == stock_code).first()
        if not stock:
            return []

        latest_date = self.db.query(func.max(ETFHolding.recorded_at)).scalar()

        results = self.db.query(
            ETF,
            ETFHolding.weight
        ).join(ETFHolding, ETF.id == ETFHolding.etf_id).filter(
            ETFHolding.stock_id == stock.id,
            ETFHolding.recorded_at == latest_date
        ).order_by(desc(ETFHolding.weight)).all()

        return [
            {
                "etf_code": r.ETF.code,
                "etf_name": r.ETF.name,
                "issuer": r.ETF.issuer,
                "category": r.ETF.category,
                "weight": float(r.weight) if r.weight else 0
            }
            for r in results
        ]
