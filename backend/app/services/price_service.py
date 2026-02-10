import time
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import text


# Module-level cache: {ticker: (price, timestamp)}
_price_cache: dict[str, tuple[Decimal, float]] = {}
_CACHE_TTL = 60  # seconds


class PriceService:
    def __init__(self, db: Session):
        self.db = db

    def get_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        """
        Get latest prices for tickers.
        Strategy:
        1. Return cached prices if within 1 minute
        2. Fetch from yfinance for uncached/expired tickers
        3. Fallback to DB for any still missing
        CASH is excluded (handled by domain layer).
        """
        query_tickers = [t for t in tickers if t != "CASH"]
        if not query_tickers:
            return {}

        now = time.time()
        prices: dict[str, Decimal] = {}

        # Step 1: Check cache
        missing = []
        for ticker in query_tickers:
            cached = _price_cache.get(ticker)
            if cached and (now - cached[1]) < _CACHE_TTL:
                prices[ticker] = cached[0]
            else:
                missing.append(ticker)

        if not missing:
            return prices

        # Step 2: Fetch from yfinance
        yf_prices = self._get_yfinance_prices(missing)
        for ticker, price in yf_prices.items():
            _price_cache[ticker] = (price, now)
            prices[ticker] = price

        # Step 3: DB fallback for still missing
        still_missing = [t for t in missing if t not in yf_prices]
        if still_missing:
            db_prices = self._get_db_prices(still_missing)
            for ticker, price in db_prices.items():
                _price_cache[ticker] = (price, now)
                prices[ticker] = price

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
        """Fetch prices from yfinance with .KS suffix for KRX stocks."""
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
        """Get ETF names from the etfs table."""
        if not tickers:
            return {}

        query_tickers = [t for t in tickers if t != "CASH"]
        names: dict[str, str] = {}

        if "CASH" in tickers:
            names["CASH"] = "현금"

        if not query_tickers:
            return names

        result = self.db.execute(
            text("SELECT code, name FROM etfs WHERE code = ANY(:tickers)"),
            {"tickers": query_tickers}
        )
        for row in result:
            names[row.code] = row.name

        # Fallback: use ticker as name for any missing
        for t in query_tickers:
            if t not in names:
                names[t] = t

        return names
