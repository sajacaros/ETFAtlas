"""지표를 정해진 규칙(대가들의 방법)으로 읽은 강세·약세 판정. 일봉과 지표 시계열만 받는 순수 함수다.

level: 2 강한 강세 … −2 강한 약세, None이면 강세·약세를 매기지 않고 상태만 (데이터 부족, 스토캐스틱).
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

STOCH_LEVELS = (20, 80)
# 신호에 필요한 일봉: 200일선이 한 달(20거래일) 올랐는지, 52주(250거래일) 고가·저가까지
SIGNAL_DAYS = 400
STAGE_MA = 150  # 와인스타인 30주 이평 ≈ 150거래일
SLOPE_DAYS = 20  # 이평 기울기를 보는 거래일 (약 4주)
FLAT_PCT = 1.0  # 이 폭(%) 안이면 이평이 평평하다
YEAR_DAYS = 250
RSI_RANGE_DAYS = 60  # 카드웰 범위를 보는 거래일
RSI_RECENT_DAYS = 10  # 범위 이탈을 보는 최근 거래일


@dataclass
class Judgement:
    key: str
    label: str
    level: Optional[int]
    state: str
    rule: str


def ma_slope(ma: List[Optional[float]], days: int = SLOPE_DAYS) -> Optional[float]:
    """이평이 days거래일 동안 몇 % 움직였는지."""
    if len(ma) <= days or ma[-1] is None or ma[-1 - days] is None:
        return None
    return (ma[-1] / ma[-1 - days] - 1) * 100


def weinstein_stage(closes: List[float], ma150: List[Optional[float]]) -> Optional[Tuple[int, str]]:
    """와인스타인 단계 (단계, 설명). 150일선(30주)의 기울기와 그 위아래 종가로 나눈다."""
    slope = ma_slope(ma150)
    if slope is None:
        return None
    above = closes[-1] > ma150[-1]
    if slope > FLAT_PCT:
        return (2, "2단계(상승): 150일선이 오르고 종가가 그 위") if above \
            else (2, "2단계 중 조정: 150일선은 오르지만 종가가 그 아래")
    if slope < -FLAT_PCT:
        return (4, "4단계(하락): 150일선이 내리고 종가가 그 아래") if not above \
            else (4, "4단계 중 반등: 150일선은 내리지만 종가가 그 위")
    # 평평하면 그 전의 흐름으로 바닥(1단계)과 천장(3단계)을 가른다
    before = ma_slope(ma150[:len(ma150) - SLOPE_DAYS], SLOPE_DAYS * 3)
    if before is not None and before < 0:
        return 1, "1단계(바닥 다지기): 내리던 150일선이 평평해짐"
    return 3, "3단계(천장권): 오르던 150일선이 평평해짐"


def minervini_template(closes: List[float], bars: List[Dict], mas: Dict[int, List]) -> Optional[Tuple[int, int]]:
    """미너비니 트렌드 템플릿 8개 중 상대강도 순위를 뺀 7개 조건의 (충족 개수, 전체 개수). 200일선 기울기를 못 보면 None."""
    ma50, ma150, ma200 = mas[50][-1], mas[150][-1], mas[200][-1]
    slope200 = ma_slope(mas[200])
    if None in (ma50, ma150, ma200, slope200):
        return None
    price = closes[-1]
    year = bars[-YEAR_DAYS:]
    low, high = min(b["low"] for b in year), max(b["high"] for b in year)
    checks = [
        price > ma150 and price > ma200,
        ma150 > ma200,
        slope200 > 0,
        ma50 > ma150 and ma50 > ma200,
        price > ma50,
        price >= low * 1.25,
        price >= high * 0.75,
    ]
    return sum(checks), len(checks)


def trend_signal(closes: List[float], bars: List[Dict], mas: Dict[int, List]) -> Judgement:
    rule = ("와인스타인 단계: 150일선(30주)의 4주 기울기가 +1% 넘으면 상승, −1% 밑이면 하락, 그 사이면 평평. "
            "2단계(오르는 이평 위) ▲▲, 1·3단계(평평) —, 4단계(내리는 이평 아래) ▼▼. "
            "미너비니 조건: 종가 > 150·200일선, 150일선 > 200일선, 200일선 한 달 상승, 50일선 > 150·200일선, "
            "종가 > 50일선, 52주 저가보다 25% 이상, 52주 고가에서 25% 이내 (상대강도 순위는 데이터가 없어 뺌)")
    stage = weinstein_stage(closes, mas[STAGE_MA])
    if not stage:
        return Judgement(key="trend", label="추세", level=None, state="데이터 부족 (150일선 기울기를 볼 수 없음)", rule=rule)
    number, text = stage
    clean = "중" not in text.split(":")[0]  # '2단계 중 조정'처럼 이평과 종가가 엇갈리면 화살표 없이
    level = {2: 2, 4: -2}.get(number, 0) if clean else 0
    template = minervini_template(closes, bars, mas)
    if template:
        text += f" · 미너비니 조건 {template[0]}/{template[1]}"
    return Judgement(key="trend", label="추세", level=level, state=text, rule=rule)


def macd_signal(hist: List[float]) -> Judgement:
    rule = ("엘더 방식: MACD 히스토그램의 기울기(전날보다 커졌는지)로 본다. 0 아래에서 위로 꺾이면 ▲▲, 0 위에서 아래로 꺾이면 ▼▼, "
            "그 밖에 히스토그램 값이 올라가는 중이면 ▲, 내려가는 중이면 ▼. 엘더는 주봉에 쓰지만 여기서는 일봉 기준")
    if len(hist) < 3:
        return Judgement(key="macd", label="MACD", level=None, state="데이터 부족", rule=rule)
    before, prev, now = hist[-3:]
    rising, was_rising = now > prev, prev > before
    if rising and not was_rising and now < 0:
        return Judgement(key="macd", label="MACD", level=2, state="히스토그램이 0 아래에서 위로 꺾임", rule=rule)
    if not rising and was_rising and now > 0:
        return Judgement(key="macd", label="MACD", level=-2, state="히스토그램이 0 위에서 아래로 꺾임", rule=rule)
    if now == prev:
        return Judgement(key="macd", label="MACD", level=0, state="히스토그램 변화 없음", rule=rule)
    side = "0 위" if now > 0 else "0 아래"
    return Judgement(key="macd", label="MACD", level=1 if rising else -1,
                  state=f"히스토그램이 {side}에서 {'올라가는' if rising else '내려가는'} 중", rule=rule)


def rsi_signal(rsi: List[float]) -> Judgement:
    rule = (f"카드웰 범위: 최근 {RSI_RANGE_DAYS}거래일 RSI가 40 아래로 안 내려가면 강세 범위(40~80) ▲, "
            "60 위로 안 올라가면 약세 범위(20~60) ▼, 60 아래로 안 내려가면 ▲▲, 40 위로 안 올라가면 ▼▼. "
            f"강세 범위였다가 최근 {RSI_RECENT_DAYS}거래일에 40을 깨면 ▼, 약세 범위였다가 60을 넘으면 ▲ (범위 전환)")
    if len(rsi) < RSI_RANGE_DAYS:
        return Judgement(key="rsi", label="RSI", level=None, state="데이터 부족", rule=rule)
    window = rsi[-RSI_RANGE_DAYS:]
    prior, recent = window[:-RSI_RECENT_DAYS], window[-RSI_RECENT_DAYS:]
    now = f"현재 {rsi[-1]:.1f}"
    if min(prior) >= 40 and min(recent) < 40:
        return Judgement(key="rsi", label="RSI", level=-1, state=f"범위 전환: 강세 범위에서 40 붕괴 ({now})", rule=rule)
    if max(prior) <= 60 and max(recent) > 60:
        return Judgement(key="rsi", label="RSI", level=1, state=f"범위 전환: 약세 범위에서 60 돌파 ({now})", rule=rule)
    low, high = min(window), max(window)
    if low >= 60:
        return Judgement(key="rsi", label="RSI", level=2, state=f"강한 강세 범위(60~80) ({now})", rule=rule)
    if high <= 40:
        return Judgement(key="rsi", label="RSI", level=-2, state=f"강한 약세 범위(20~40) ({now})", rule=rule)
    if low >= 40:
        return Judgement(key="rsi", label="RSI", level=1, state=f"강세 범위(40~80) ({now})", rule=rule)
    if high <= 60:
        return Judgement(key="rsi", label="RSI", level=-1, state=f"약세 범위(20~60) ({now})", rule=rule)
    return Judgement(key="rsi", label="RSI", level=0, state=f"범위 없음 ({low:.0f}~{high:.0f} 사이 등락, {now})", rule=rule)


def stoch_signal(k: List[float], d: List[float], stage: Optional[Tuple[int, str]]) -> Judgement:
    rule = ("엘더의 두 번째 스크린: 스토캐스틱은 혼자 강세·약세를 매기지 않고 큰 추세(와인스타인 단계) 안에서 "
            f"단기 위치만 본다. %K {STOCH_LEVELS[0]} 이하면 눌림·과매도, {STOCH_LEVELS[1]} 이상이면 과열·반등")
    if not k:
        return Judgement(key="stochastic", label="스토캐스틱", level=None, state="데이터 부족", rule=rule)
    low, high = STOCH_LEVELS
    now = k[-1]
    trend = {1: None, 2: "상승", 3: None, 4: "하락"}.get(stage[0]) if stage else None
    cross = "%K가 %D 위" if now > d[-1] else "%K가 %D 아래"
    if now <= low:
        state = f"{trend} 추세 속 눌림" if trend == "상승" else f"{trend} 추세 속 과매도" if trend else "과매도 구간"
    elif now >= high:
        state = f"{trend} 추세 속 과열" if trend == "상승" else f"{trend} 추세 속 반등" if trend else "과매수 구간"
    else:
        state = "중간 구간"
    return Judgement(key="stochastic", label="스토캐스틱", level=None, state=f"{state} (%K {now:.1f}, {cross})", rule=rule)


def signals(bars: List[Dict], closes: List[float], mas: Dict[int, List], hist: List[float],
             rsi: List[float], k: List[float], d: List[float]) -> List[Judgement]:
    return [
        trend_signal(closes, bars, mas),
        macd_signal(hist),
        rsi_signal(rsi),
        stoch_signal(k, d, weinstein_stage(closes, mas[STAGE_MA])),
    ]
