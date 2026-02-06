from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import text


class PriceService:
    def __init__(self, db: Session):
        self.db = db

    def get_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        """
        Get latest prices for tickers.
        Strategy:
        1. Query etf_prices table for latest close_price (DISTINCT ON)
        2. Fallback to yfinance for missing tickers
        CASH is excluded (handled by domain layer).
        """
        # Filter out CASH
        query_tickers = [t for t in tickers if t != "CASH"]
        if not query_tickers:
            return {}

        prices: dict[str, Decimal] = {}

        # Step 1: DB lookup
        db_prices = self._get_db_prices(query_tickers)
        prices.update(db_prices)

        # Step 2: yfinance fallback for missing
        missing = [t for t in query_tickers if t not in prices]
        if missing:
            yf_prices = self._get_yfinance_prices(missing)
            prices.update(yf_prices)

        return prices

    def _get_db_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        """Query latest close_price from etf_prices using DISTINCT ON."""
        result = self.db.execute(
            text("""
                SELECT DISTINCT ON (etf_code) etf_code, close_price
                FROM etf_prices
                WHERE etf_code = ANY(:tickers)
                  AND close_price IS NOT NULL
                ORDER BY etf_code, date DESC
            """),
            {"tickers": tickers}
        )
        return {
            row.etf_code: Decimal(str(row.close_price))
            for row in result
        }

    def _get_yfinance_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        """Fallback: fetch prices from yfinance with .KS suffix for KRX stocks."""
        prices: dict[str, Decimal] = {}
        try:
            import yfinance as yf
            for ticker in tickers:
                try:
                    yf_ticker = f"{ticker}.KS"
                    info = yf.Ticker(yf_ticker)
                    hist = info.history(period="5d")
                    if not hist.empty:
                        close = hist["Close"].iloc[-1]
                        prices[ticker] = Decimal(str(int(close)))
                except Exception:
                    continue
        except ImportError:
            pass
        return prices

    def get_etf_names(self, tickers: list[str]) -> dict[str, str]:
        """Get ETF names from the graph or etf_prices table."""
        if not tickers:
            return {}

        query_tickers = [t for t in tickers if t != "CASH"]
        names: dict[str, str] = {}

        if "CASH" in tickers:
            names["CASH"] = "현금"

        if not query_tickers:
            return names

        # Try to get names from AGE graph
        try:
            result = self.db.execute(
                text("""
                    SELECT * FROM ag_catalog.cypher('etf_graph', $$
                        MATCH (e:ETF)
                        WHERE e.code IN :tickers
                        RETURN e.code, e.name
                    $$) AS (code agtype, name agtype)
                """.replace(":tickers", str(query_tickers)))
            )
            for row in result:
                code = str(row[0]).strip('"')
                name = str(row[1]).strip('"')
                names[code] = name
        except Exception:
            # Fallback: use ticker as name
            for t in query_tickers:
                if t not in names:
                    names[t] = t

        return names
