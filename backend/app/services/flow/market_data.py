"""종목 스크리너의 시세 공급원.

노드는 MarketData.bars()만 부른다. 지금은 기능을 먼저 검증하려고 yfinance로 받고,
어떤 데이터를 쌓을지 정해지면 DB(AGE Price)를 읽는 구현체로 바꾼다.
"""
import logging
import threading
import time
from typing import Dict, Iterable, List, Optional, Protocol

from ...domain.indicators import Bar

logger = logging.getLogger(__name__)

HISTORY_PERIOD = "1y"  # 120일 이평·VCP(60일)까지 계산할 수 있는 기간
CACHE_TTL = 6 * 3600  # 같은 종목을 하루 안에 다시 받지 않는다 (559종목 일괄 다운로드에 약 30초)
SUFFIXES = (".KS", ".KQ")  # 코스피 → 코스닥 순서로 시도한다


class MarketData(Protocol):
    def bars(self, codes: Iterable[str]) -> Dict[str, List[Bar]]:
        """코드 → 날짜 오름차순 일봉. 받지 못한 종목은 빠진다."""
        ...


class FreshMarketData:
    """since(epoch 초) 전에 받아 둔 캐시는 다시 받는다. 자동 실행이 장중에 받아 둔 미완성 일봉을 쓰지 않게 한다."""

    def __init__(self, base: "YFinanceMarketData", since: float):
        self.base, self.since = base, since

    def bars(self, codes: Iterable[str]) -> Dict[str, List[Bar]]:
        return self.base.bars(codes, fetched_after=self.since)


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
    """yfinance 일봉(수정주가). 프로세스 메모리에 CACHE_TTL 동안 두고, 종목별 시장 구분(.KS/.KQ)도 기억한다.

    락은 캐시를 읽고 쓸 때만 잡는다 — 다운로드(수십 초)를 하는 동안 다른 요청이 캐시를 읽지 못하면 안 된다.
    그래서 같은 종목을 두 요청이 동시에 받을 수는 있다. 다운로드가 실패한 종목은 캐시하지 않아 다음 요청이 다시 받는다.
    """

    def __init__(self):
        self._cache: Dict[str, tuple[float, List[Bar]]] = {}
        self._suffix: Dict[str, str] = {}
        self._lock = threading.Lock()

    def bars(self, codes: Iterable[str], fetched_after: float = 0) -> Dict[str, List[Bar]]:
        codes = list(dict.fromkeys(codes))
        now = time.time()
        with self._lock:
            missing = [
                c for c in codes
                if c not in self._cache or now - self._cache[c][0] > CACHE_TTL or self._cache[c][0] < fetched_after
            ]
            known = {c: self._suffix[c] for c in missing if c in self._suffix}
        if missing:
            fetched = self._fetch(missing, known)
            with self._lock:
                for code, (bars, suffix) in fetched.items():
                    self._cache[code] = (now, bars)
                    if suffix:
                        self._suffix[code] = suffix
        with self._lock:
            return {c: self._cache[c][1] for c in codes if c in self._cache and self._cache[c][1]}

    def _fetch(self, codes: List[str], known: Dict[str, str]) -> Dict[str, tuple[List[Bar], Optional[str]]]:
        """코드 → (일봉, 시장 접미사). 시장을 아는 종목은 그 접미사로 바로, 모르는 종목은 .KS부터 시도해 없으면 .KQ로.
        두 시장 모두 받았는데 없으면 빈 일봉으로 남겨 같은 날 다시 시도하지 않고, 다운로드가 실패한 종목은 빼서 다음에 다시 받는다."""
        out: Dict[str, tuple[List[Bar], Optional[str]]] = {}
        pending = list(codes)
        failed: set = set()
        for suffix in SUFFIXES:
            targets = [c for c in pending if known.get(c, suffix) == suffix]
            if not targets:
                continue
            fetched = self._download([c + suffix for c in targets])
            if fetched is None:
                failed.update(targets)
                continue
            for code in targets:
                bars = fetched.get(code + suffix)
                if bars:
                    out[code] = (bars, suffix)
            pending = [c for c in pending if c not in out]
        for code in pending:
            if code not in failed:
                out[code] = ([], None)
        return out

    @staticmethod
    def _download(tickers: List[str]) -> Optional[Dict[str, List[Bar]]]:
        """티커 → 일봉 (데이터가 없는 티커는 빠진다). 다운로드 자체가 실패하면 None."""
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
            return None
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


def default_market_data() -> YFinanceMarketData:
    global _default
    if _default is None:
        _default = YFinanceMarketData()
    return _default
