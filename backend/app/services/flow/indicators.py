"""일봉으로 계산하는 차트 지표. 순수 함수라 시세 공급원(yfinance·DB)과 상관없이 테스트한다.

bars: 날짜 오름차순 [{date, open, high, low, close, volume}]. 기간이 모자라면 None을 돌려준다.
"""
from typing import Dict, List, Optional, Sequence

Bar = Dict[str, float]


def sma(values: Sequence[float], n: int) -> Optional[float]:
    if n <= 0 or len(values) < n:
        return None
    return sum(values[-n:]) / n


def period_return(closes: Sequence[float], n: int) -> Optional[float]:
    """n거래일 전 종가 대비 수익률(%)."""
    if n <= 0 or len(closes) <= n or not closes[-n - 1]:
        return None
    return (closes[-1] / closes[-n - 1] - 1) * 100


def from_high(bars: Sequence[Bar], n: int) -> Optional[float]:
    """최근 n거래일 고가 대비 현재 종가의 위치(%). 0이면 신고가, -10이면 고가보다 10% 아래."""
    if n <= 0 or len(bars) < n:
        return None
    high = max(b["high"] for b in bars[-n:])
    return (bars[-1]["close"] / high - 1) * 100 if high else None


def volume_ratio(volumes: Sequence[float], n: int = 20) -> Optional[float]:
    """마지막 날 거래량 ÷ 그 전 n거래일 평균 거래량."""
    if len(volumes) < n + 1:
        return None
    avg = sum(volumes[-n - 1:-1]) / n
    return volumes[-1] / avg if avg else None


def rsi(closes: Sequence[float], n: int = 14) -> Optional[float]:
    """Wilder 평활 RSI."""
    if len(closes) < n + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gain = sum(max(c, 0) for c in changes[:n]) / n
    loss = sum(max(-c, 0) for c in changes[:n]) / n
    for c in changes[n:]:
        gain = (gain * (n - 1) + max(c, 0)) / n
        loss = (loss * (n - 1) + max(-c, 0)) / n
    if loss == 0:
        return 100.0
    return 100 - 100 / (1 + gain / loss)


def ma_aligned(closes: Sequence[float], periods: Sequence[int] = (5, 20, 60)) -> Optional[bool]:
    """이동평균 정배열: 짧은 이평이 긴 이평보다 차례로 위에 있다 (5일 > 20일 > 60일)."""
    mas = [sma(closes, n) for n in periods]
    if any(m is None for m in mas):
        return None
    return all(a > b for a, b in zip(mas, mas[1:]))


def contraction_ranges(bars: Sequence[Bar], windows: int = 3, size: int = 20) -> Optional[List[float]]:
    """최근 windows×size 거래일을 size일씩 나눈 구간별 변동폭(%) = (최고가 - 최저가) / 최고가, 오래된 구간부터."""
    if len(bars) < windows * size:
        return None
    ranges = []
    for i in range(windows):
        chunk = bars[len(bars) - (windows - i) * size: len(bars) - (windows - i - 1) * size]
        high = max(b["high"] for b in chunk)
        low = min(b["low"] for b in chunk)
        ranges.append((high - low) / high * 100 if high else 0.0)
    return ranges


def is_vcp(bars: Sequence[Bar], last_range_max: float = 10.0, near_high_pct: float = 10.0) -> Optional[bool]:
    """간이 VCP(변동성 수축): 20일 구간 3개의 변동폭이 차례로 줄고, 마지막 구간이 last_range_max% 이하이며,
    종가가 60일 고가에서 near_high_pct% 안에 있고, 마지막 구간 평균 거래량이 첫 구간보다 적다.
    미너비니 VCP의 핵심(수축·고점 근처·거래량 감소)만 옮긴 근사다."""
    ranges = contraction_ranges(bars)
    position = from_high(bars, 60)
    if ranges is None or position is None:
        return None
    first = [b["volume"] for b in bars[-60:-40]]
    last = [b["volume"] for b in bars[-20:]]
    return (
        ranges[0] > ranges[1] > ranges[2]
        and ranges[2] <= last_range_max
        and position >= -near_high_pct
        and sum(last) < sum(first)
    )
