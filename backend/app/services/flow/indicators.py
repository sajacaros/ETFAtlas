"""일봉으로 계산하는 차트 지표. 순수 함수라 시세 공급원(yfinance·DB)과 상관없이 테스트한다.

bars: 날짜 오름차순 [{date, open, high, low, close, volume}]. 기간이 모자라면 None을 돌려준다.
"""
from typing import Dict, List, Optional, Sequence, Tuple

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


def rsi_series(closes: Sequence[float], n: int = 14) -> List[float]:
    """Wilder 평활 RSI 시계열 (len(closes) - n개, 끝을 closes에 맞춘다)."""
    if n <= 0 or len(closes) < n + 1:
        return []
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gain = sum(max(c, 0) for c in changes[:n]) / n
    loss = sum(max(-c, 0) for c in changes[:n]) / n
    out = []
    for i in range(n, len(changes) + 1):
        if i > n:
            c = changes[i - 1]
            gain = (gain * (n - 1) + max(c, 0)) / n
            loss = (loss * (n - 1) + max(-c, 0)) / n
        out.append(100.0 if loss == 0 else 100 - 100 / (1 + gain / loss))
    return out


def rsi(closes: Sequence[float], n: int = 14) -> Optional[float]:
    """Wilder 평활 RSI."""
    series = rsi_series(closes, n)
    return series[-1] if series else None


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


def rolling_mean(values: Sequence[float], n: int) -> List[float]:
    """길이 n 창의 단순 평균 시계열 (len(values) - n + 1개)."""
    return [sum(values[i - n + 1: i + 1]) / n for i in range(n - 1, len(values))]


def ema_series(values: Sequence[float], n: int) -> List[float]:
    """지수이동평균 시계열 (len(values) - n + 1개). 처음 n개의 단순 평균에서 시작한다."""
    if n <= 0 or len(values) < n:
        return []
    alpha = 2 / (n + 1)
    out = [sum(values[:n]) / n]
    for v in values[n:]:
        out.append(out[-1] + alpha * (v - out[-1]))
    return out


def macd(closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[Tuple[List[float], List[float]]]:
    """(MACD선, 시그널선), 끝을 맞춘 같은 길이. MACD = 단기 EMA − 장기 EMA, 시그널 = MACD의 EMA."""
    slow_e = ema_series(closes, slow)
    fast_e = ema_series(closes, fast)[-len(slow_e):] if slow_e else []
    line = [f - s for f, s in zip(fast_e, slow_e)]
    sig = ema_series(line, signal)
    if len(sig) < 2:
        return None
    return line[-len(sig):], sig


def stoch_slow(bars: Sequence[Bar], n: int = 5, k: int = 3, d: int = 3) -> Optional[Tuple[List[float], List[float]]]:
    """스토캐스틱 슬로우 (%K, %D), 끝을 맞춘 같은 길이.
    Fast %K = (종가 − n일 최저가) / (n일 최고가 − n일 최저가), Slow %K = Fast %K의 k일 단순 평균, Slow %D = Slow %K의 d일 단순 평균.
    n일 동안 가격이 그대로면 Fast %K는 50으로 둔다."""
    if len(bars) < n + k + d:
        return None
    fast_k = []
    for i in range(n - 1, len(bars)):
        window = bars[i - n + 1: i + 1]
        high = max(b["high"] for b in window)
        low = min(b["low"] for b in window)
        fast_k.append((bars[i]["close"] - low) / (high - low) * 100 if high > low else 50.0)
    slow_k = rolling_mean(fast_k, k)
    slow_d = rolling_mean(slow_k, d)
    return slow_k[-len(slow_d):], slow_d


def days_since_golden_cross(a: Sequence[float], b: Sequence[float]) -> Optional[int]:
    """a가 b를 위로 뚫은 뒤 지금도 위에 있다면 그 교차가 며칠 전인지 (0 = 마지막 거래일).
    지금 a가 b 위가 아니거나, 받은 기간 내내 위여서 교차를 못 봤으면 None. a·b는 끝을 맞춘 같은 길이."""
    i = len(a) - 1
    if i < 1 or a[i] <= b[i]:
        return None
    while i > 0 and a[i - 1] > b[i - 1]:
        i -= 1
    return len(a) - 1 - i if i > 0 else None


def last_cross(a: Sequence[float], b: Sequence[float]) -> Optional[Tuple[str, int]]:
    """a와 b가 마지막으로 교차한 방향('golden' = a가 b를 위로, 'dead' = 아래로)과 몇 거래일 전인지 (0 = 마지막 거래일).
    받은 기간 안에 교차가 없으면 None. a·b는 끝을 맞춘 같은 길이."""
    for i in range(len(a) - 1, 0, -1):
        above = a[i] > b[i]
        if above != (a[i - 1] > b[i - 1]):
            return ("golden" if above else "dead"), len(a) - 1 - i
    return None


def bollinger_series(closes: Sequence[float], n: int = 20, k: float = 2.0) -> List[Tuple[float, float, float]]:
    """볼린저 밴드 (중심선, 상단, 하단) 시계열 (len(closes) - n + 1개). 밴드 = n일 이평 ± k × 표준편차(모집단)."""
    out = []
    for i in range(n - 1, len(closes)):
        window = closes[i - n + 1: i + 1]
        mid = sum(window) / n
        std = (sum((c - mid) ** 2 for c in window) / n) ** 0.5
        out.append((mid, mid + k * std, mid - k * std))
    return out


def bollinger_pctb(closes: Sequence[float], n: int = 20, k: float = 2.0) -> Optional[float]:
    """볼린저 %B(%): 0이면 하단 밴드, 100이면 상단 밴드, 밴드 밖이면 0 미만·100 초과. 밴드 = n일 이평 ± k × 표준편차(모집단)."""
    if len(closes) < n:
        return None
    _, upper, lower = bollinger_series(closes[-n:], n, k)[-1]
    if upper == lower:
        return None
    return (closes[-1] - lower) / (upper - lower) * 100
