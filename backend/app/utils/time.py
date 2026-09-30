from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC now — DB의 TIMESTAMP(without time zone) 컬럼과 호환. datetime.utcnow() 대체."""
    return datetime.now(UTC).replace(tzinfo=None)
