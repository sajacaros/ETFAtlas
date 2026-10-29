"""기간 표기와 기간 수익률. 가격 추이·기간 수익률·수익률 순위·차트 분석이 같은 시작점을 써서 같은 기간이면 같은 수익률이 나온다."""
import re
from datetime import date, timedelta
from typing import Annotated, Dict, List, Optional

from pydantic import AfterValidator

# 기간 표기: 숫자+단위(d 일, w 주, m 개월, y 년) 또는 ytd(올해, 작년 마지막 거래일 대비). 개월·년은 30·365일로 센다
_PERIOD_RE = re.compile(r"(\d{1,3})([dwmy])|ytd")
_UNITS = {"d": ("일", 1), "w": ("주", 7), "m": ("개월", 30), "y": ("년", 365)}


def _check_period(spec: str) -> str:
    spec = spec.strip().lower()
    match = _PERIOD_RE.fullmatch(spec)
    if not match or (match.group(1) and int(match.group(1)) == 0):
        raise ValueError(f"기간 표기가 맞지 않습니다: '{spec}' (예: 1w, 45d, 3m, 1y, ytd)")
    return spec


Period = Annotated[str, AfterValidator(_check_period)]


def period_label(spec: str) -> str:
    if spec == "ytd":
        return "연초 이후"
    n, unit = int(spec[:-1]), spec[-1]
    return f"{n}{_UNITS[unit][0]}"


def period_start(spec: str, end: date) -> date:
    """end에서 거슬러 간 시작 기준일. 수익률은 이 날 이전의 가장 가까운 거래일 종가에서 센다."""
    if spec == "ytd":
        return date(end.year - 1, 12, 31)
    n, unit = int(spec[:-1]), spec[-1]
    return end - timedelta(days=n * _UNITS[unit][1])


def period_days(spec: str) -> int:
    """기간의 시작점까지 가져오려면 오늘부터 거슬러 가져올 가격 일수 (시작점 앞 휴장일 여유 포함)."""
    today = date.today()
    return (today - period_start(spec, today)).days + 10


def period_base(prices: List[Dict], spec: str) -> Optional[Dict]:
    """기간의 시작점: 마지막 거래일에서 기간만큼 거슬러 간 날 이전의 가장 가까운 거래일 가격. 데이터가 그만큼 없으면 None."""
    target = period_start(spec, date.fromisoformat(prices[-1]["date"])).isoformat()
    past = [p for p in prices if p["date"] <= target]
    return past[-1] if past else None


def pct_change(start: Optional[float], end: Optional[float]) -> Optional[float]:
    if not start or end is None:
        return None
    return round((end - start) / start * 100, 2)
