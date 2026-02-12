import time
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import text
from .graph_service import GraphService


# Module-level cache: {ticker: (price, timestamp)}
_price_cache: dict[str, tuple[Decimal, float]] = {}
_CACHE_TTL = 60  # seconds


class PriceService:
    def __init__(self, db: Session, graph_service: GraphService | None = None):
        self.db = db
        self.graph_service = graph_service or GraphService(db)

    def get_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        """
        Get latest prices for tickers.
        Strategy:
        1. Return cached prices if within 1 minute
        2. AGE에 당일 종가가 있으면 사용 (장 마감 후 수집된 데이터)
        3. 없으면 yfinance로 조회 (장중 실시간)
        4. Fallback to AGE (최신 날짜)
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

        # Step 2: AGE 당일 종가
        age_today = self.graph_service.get_latest_close_prices(missing)
        for ticker, price in age_today.items():
            _price_cache[ticker] = (price, now)
            prices[ticker] = price

        still_missing = [t for t in missing if t not in prices]
        if not still_missing:
            return prices

        # Step 3: yfinance for rest
        yf_prices = self._get_yfinance_prices(still_missing)
        for ticker, price in yf_prices.items():
            _price_cache[ticker] = (price, now)
            prices[ticker] = price

        # Step 4: AGE fallback for still missing
        still_missing = [t for t in still_missing if t not in yf_prices]
        if still_missing:
            age_fallback = self.graph_service.get_latest_close_prices_fallback(still_missing)
            for ticker, price in age_fallback.items():
                _price_cache[ticker] = (price, now)
                prices[ticker] = price

        return prices

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
