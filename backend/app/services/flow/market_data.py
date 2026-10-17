"""분석 흐름의 시세 공급원.

노드는 MarketData.bars()만 부른다. 지금은 기능을 먼저 검증하려고 yfinance로 받고,
어떤 데이터를 쌓을지 정해지면 DB(AGE Price)를 읽는 구현체로 바꾼다.
"""
import logging
import threading
import time
from typing import Dict, Iterable, List, Optional, Protocol

from .indicators import Bar

logger = logging.getLogger(__name__)

HISTORY_PERIOD = "1y"  # 120일 이평·VCP(60일)까지 계산할 수 있는 기간
CACHE_TTL = 6 * 3600  # 같은 종목을 하루 안에 다시 받지 않는다 (559종목 일괄 다운로드에 약 30초)
SUFFIXES = (".KS", ".KQ")  # 코스피 → 코스닥 순서로 시도한다


class MarketData(Protocol):
    def bars(self, codes: Iterable[str]) -> Dict[str, List[Bar]]:
        """코드 → 날짜 오름차순 일봉. 받지 못한 종목은 빠진다."""
        ...


def _frame_bars(frame) -> List[Bar]:
    frame = frame.dropna(subset=["Close"])
    return [
        {
            "date": idx.strftime("%Y-%m-%d"),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"]) if row["Volume"] == row["Volume"] else 0.0,  # NaN이면 0
        }
        for idx, row in frame.iterrows()
    ]


class YFinanceMarketData:
    """yfinance 일봉(수정주가). 프로세스 메모리에 CACHE_TTL 동안 두고, 종목별 시장 구분(.KS/.KQ)도 기억한다."""

    def __init__(self):
        self._cache: Dict[str, tuple[float, List[Bar]]] = {}
        self._suffix: Dict[str, str] = {}
        self._lock = threading.Lock()

    def bars(self, codes: Iterable[str]) -> Dict[str, List[Bar]]:
        codes = list(dict.fromkeys(codes))
        now = time.time()
        with self._lock:
            missing = [c for c in codes if c not in self._cache or now - self._cache[c][0] > CACHE_TTL]
            if missing:
                self._fetch(missing, now)
            return {c: self._cache[c][1] for c in codes if c in self._cache and self._cache[c][1]}

    def _fetch(self, codes: List[str], now: float) -> None:
        # 시장을 아는 종목은 그 접미사로 바로, 모르는 종목은 .KS부터 시도해 없으면 .KQ로
        pending = list(codes)
        for suffix in SUFFIXES:
            targets = [c for c in pending if self._suffix.get(c, suffix) == suffix]
            if not targets:
                continue
            fetched = self._download([c + suffix for c in targets])
            got = set()
            for code in targets:
                bars = fetched.get(code + suffix)
                if bars:
                    self._cache[code] = (now, bars)
                    self._suffix[code] = suffix
                    got.add(code)
            pending = [c for c in pending if c not in got]
        for code in pending:  # 두 시장 모두 없으면 빈 값으로 캐시해 같은 날 다시 시도하지 않는다
            self._cache[code] = (now, [])

    @staticmethod
    def _download(tickers: List[str]) -> Dict[str, List[Bar]]:
        import yfinance as yf

        # 코스닥 종목을 .KS로 먼저 시도하므로 "No data found"가 종목마다 찍힌다 — 예상된 실패라 숨긴다
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
        try:
            frame = yf.download(
                tickers, period=HISTORY_PERIOD, auto_adjust=True, progress=False,
                group_by="ticker", threads=True,
            )
        except Exception as e:
            logger.warning("yfinance download failed: %s", e)
            return {}
        if frame is None or frame.empty:
            return {}
        result = {}
        for ticker in tickers:
            try:
                sub = frame[ticker] if ticker in frame.columns.get_level_values(0) else None
            except Exception:
                sub = None
            if sub is not None:
                bars = _frame_bars(sub)
                if bars:
                    result[ticker] = bars
        return result


_default: Optional[YFinanceMarketData] = None


def default_market_data() -> MarketData:
    global _default
    if _default is None:
        _default = YFinanceMarketData()
    return _default
