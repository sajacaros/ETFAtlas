from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")  # 장 날짜·스냅샷 날짜의 기준. 서버 시간대에 기대지 않는다


def utcnow() -> datetime:
    """Naive UTC now — DB의 TIMESTAMP(without time zone) 컬럼과 호환. datetime.utcnow() 대체."""
    return datetime.now(UTC).replace(tzinfo=None)


def today_kst() -> date:
    return datetime.now(KST).date()


def iso_utc(dt: datetime | None) -> str | None:
    """DB의 naive UTC 시각을 오프셋을 붙인 ISO 문자열로. 브라우저가 현지 시각으로 바르게 읽는다."""
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()
