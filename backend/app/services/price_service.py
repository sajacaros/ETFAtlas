import time
from datetime import date
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
        1. Return cached prices if within 60 seconds
        2. RDB ticker_prices 테이블에서 최신 가격 조회
        3. 없으면 yfinance로 조회 (폴백)
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

        # Step 2: RDB ticker_prices (최신 날짜 기준)
        rdb_prices = self._get_rdb_prices(missing)
        for ticker, price in rdb_prices.items():
            _price_cache[ticker] = (price, now)
            prices[ticker] = price

        still_missing = [t for t in missing if t not in prices]
        if not still_missing:
            return prices

        # Step 3: yfinance fallback
        yf_prices = self._get_yfinance_prices(still_missing)
        for ticker, price in yf_prices.items():
            _price_cache[ticker] = (price, now)
            prices[ticker] = price

        return prices

    def _get_rdb_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        """ticker_prices 테이블에서 각 티커의 최신 가격 조회 (batch)."""
        if not tickers:
            return {}

        result = self.db.execute(
            text("""
                SELECT DISTINCT ON (ticker) ticker, price
                FROM ticker_prices
                WHERE ticker = ANY(:tickers)
                ORDER BY ticker, date DESC
            """),
            {"tickers": tickers},
        )
        return {row.ticker: Decimal(str(row.price)) for row in result}

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

    def get_latest_price_date(self) -> date | None:
        """ticker_prices 테이블에서 MAX(date)를 조회한다."""
        result = self.db.execute(text("SELECT MAX(date) AS max_date FROM ticker_prices"))
        row = result.fetchone()
        if row and row.max_date:
            return row.max_date
        return None

    def get_prev_prices(self, tickers: list[str]) -> dict[str, Decimal]:
        """ticker_prices 테이블에서 각 티커의 전일(두 번째 최신) 가격 조회."""
        query_tickers = [t for t in tickers if t != "CASH"]
        if not query_tickers:
            return {}

        result = self.db.execute(
            text("""
                SELECT ticker, price FROM (
                    SELECT ticker, price, date,
                           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
                    FROM ticker_prices
                    WHERE ticker = ANY(:tickers)
                ) sub
                WHERE rn = 2
            """),
            {"tickers": query_tickers},
        )
        return {row.ticker: Decimal(str(row.price)) for row in result}

    def get_etf_names(self, tickers: list[str]) -> dict[str, str]:
        """Get ETF names. AGE first, RDB etfs fallback for non-universe ETFs."""
        if not tickers:
            return {}

        query_tickers = [t for t in tickers if t != "CASH"]
        names: dict[str, str] = {}

        if "CASH" in tickers:
            names["CASH"] = "현금"

        if not query_tickers:
            return names

        # AGE에서 조회
        from .graph_service import GraphService
        graph = GraphService(self.db)
        age_names = graph.get_etf_names(query_tickers)
        names.update(age_names)

        # AGE에 없는 것은 RDB 폴백 (비유니버스 ETF)
        missing = [t for t in query_tickers if t not in names]
        if missing:
            result = self.db.execute(
                text("SELECT code, name FROM etfs WHERE code = ANY(:tickers)"),
                {"tickers": missing}
            )
            for row in result:
                names[row.code] = row.name

        for t in query_tickers:
            if t not in names:
                names[t] = t

        return names
