"""
market_calendar — 시각(KST)·영업일·날짜 형식

컨테이너 TZ가 Asia/Seoul이어도 시각은 now_kst()로 받는다 — 테스트·다른 환경에서도 같은 날짜가 나오게.
"""

import logging
from datetime import datetime, time, timedelta
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from kis_api_client import get_kis_client
from rdb import connection

log = logging.getLogger(__name__)

KST = ZoneInfo('Asia/Seoul')

BUSINESS_DAY_REFERENCE_CODE = '069500'  # KODEX 200 — 모든 거래일에 거래됨
MARKET_OPEN_TIME = time(9, 0)
MARKET_SETTLED_TIME = time(16, 0)  # 15:30 종가 확정 후 여유
# KIS 구성종목(PDF)은 영업일 08:30에 그날 공시분(직전 영업일 장 마감 후 보유)으로 갱신된다 — 갱신 뒤에 받는다
HOLDINGS_PUBLISH_TIME = time(8, 35)


def now_kst() -> datetime:
    """지금 KST 시각 (tz 없는 벽시계 값 — 날짜 문자열·DB timestamp에 그대로 쓴다)."""
    return datetime.now(KST).replace(tzinfo=None)


def dash_date(d: str) -> str:
    """YYYYMMDD → YYYY-MM-DD (Price.date·HOLDS.date 형식)."""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def compact_date(d: str) -> str:
    """YYYY-MM-DD → YYYYMMDD (KIS 날짜 형식)."""
    return d.replace('-', '')


def last_settled_day(now: datetime) -> str:
    """종가가 확정된 마지막 날짜(YYYYMMDD). 장 마감 전이면 전날.

    KIS 일봉은 장중에도 당일 봉(미완성)을 돌려주므로 수집 범위 끝을 여기서 자른다.
    휴장일 여부는 보지 않는다 — get_business_days가 거른다.
    """
    day = now if now.time() >= MARKET_SETTLED_TIME else now - timedelta(days=1)
    return day.strftime('%Y%m%d')


def snapshot_is_settled(now: datetime) -> bool:
    """지금 받는 현재가(NAV·순자산)가 last_settled_day의 값인지. 장중(개장~종가 확정)에는 그날 움직이는 값이다."""
    return not (MARKET_OPEN_TIME <= now.time() < MARKET_SETTLED_TIME)


def days_before(d: str, days: int) -> str:
    """YYYYMMDD에서 달력 기준 days일 전 (YYYYMMDD)."""
    return (datetime.strptime(d, '%Y%m%d') - timedelta(days=days)).strftime('%Y%m%d')


def get_business_days(from_date: str, to_date: str) -> list[str]:
    """KIS 일봉(기준 ETF)으로 영업일 목록 조회. YYYYMMDD 리스트 반환."""
    kis = get_kis_client()
    if kis is None:
        return []
    # 실패를 빈 목록으로 돌려주면 "이미 최신"으로 오인하므로 예외를 그대로 올려 태스크 재시도에 맡긴다
    bars = kis.get_daily_bars(BUSINESS_DAY_REFERENCE_CODE, from_date, to_date)
    return [b.date for b in bars]


def is_market_open(day) -> bool | None:
    """개장일 여부. market_calendar 캐시 → 없으면 KIS 국내휴장일조회(1일 1회 권장) 후 저장. 모르면 None."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT is_open FROM market_calendar WHERE date = %s", (day,))
        row = cur.fetchone()
        if row is not None:
            return row[0]

        kis = get_kis_client()
        if kis is None:
            return None
        try:
            is_open = kis.is_market_open(day.strftime('%Y%m%d'))
        except Exception as e:
            log.warning(f"KIS holiday lookup failed: {e}")
            return None
        if is_open is not None:
            cur.execute(
                "INSERT INTO market_calendar (date, is_open) VALUES (%s, %s) "
                "ON CONFLICT (date) DO UPDATE SET is_open = EXCLUDED.is_open, checked_at = NOW()",
                (day, is_open),
            )
            conn.commit()
        return is_open


def holdings_target_date(now: datetime, market_open: Callable[..., Optional[bool]] = is_market_open) -> str | None:
    """지금 받을 구성종목의 날짜(YYYYMMDD) — 수집한 날(그날 공시된 구성). 받으면 안 되는 때면 None.

    KIS 구성종목(PDF)은 영업일 08:30에 그날 적용할 내역(직전 영업일 장 마감 후 보유)으로 갱신되고
    다음 영업일 아침까지 그대로다. 그래서 개장일 08:35 이후면 언제 받아도 같은 내역이고, 그날 날짜로 적는다.
    주말·휴장일에는 갱신이 없으므로 받지 않는다. 비교는 ETF별 이전 수집일과 하므로 날짜가 비어도 된다.
    """
    if now.time() < HOLDINGS_PUBLISH_TIME:
        return None
    is_open = market_open(now.date())
    if is_open is None:
        raise RuntimeError(f"Cannot tell whether {now:%Y-%m-%d} is a trading day")
    return now.strftime('%Y%m%d') if is_open else None
