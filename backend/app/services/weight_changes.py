from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from ..models.discord_setting import DiscordSetting
from ..models.weight_change import WeightChange, WeightChangeDate

DEFAULT_ALERT_THRESHOLD = 3.0
DEFAULT_ADDED_THRESHOLD = 2.0


def get_alert_thresholds(db: Session) -> tuple[float, float]:
    """(비중변화 기준값, 신규편입 기준값) %p. 디스코드 알림과 웹 비중변화 화면이 같은 값을 쓴다 (관리자 페이지에서 설정)."""
    setting = db.get(DiscordSetting, 1)
    if not setting:
        return DEFAULT_ALERT_THRESHOLD, DEFAULT_ADDED_THRESHOLD
    return setting.threshold, setting.added_threshold


def is_significant(change_type: str, weight_change: float, threshold: float, added_threshold: float) -> bool:
    """신규편입은 added_threshold, 나머지는 threshold를 넘는 |변화량|만."""
    return abs(weight_change) > (added_threshold if change_type == "added" else threshold)


def resolve_change_date(db: Session, base_date: str | None = None) -> str | None:
    """비중 변화가 계산된 날짜 중 base_date 이하(없으면 전체)에서 가장 최근 날짜."""
    q = db.query(func.max(WeightChangeDate.base_date))
    if base_date:
        q = q.filter(WeightChangeDate.base_date <= base_date)
    return q.scalar()


def get_significant_changes(db: Session, base_date: str, threshold: float,
                            added_threshold: float) -> list[WeightChange]:
    """Airflow가 저장한 base_date의 액티브 ETF 비중 변화 중 기준값을 넘는 것 (변화량 큰 순).
    신규편입은 added_threshold, 나머지는 threshold를 쓴다."""
    size = func.abs(WeightChange.weight_change)
    return (
        db.query(WeightChange)
        .filter(
            WeightChange.base_date == base_date,
            or_(
                and_(WeightChange.change_type == "added", size > added_threshold),
                and_(WeightChange.change_type != "added", size > threshold),
            ),
        )
        .order_by(size.desc(), WeightChange.etf_code, WeightChange.stock_code)
        .all()
    )
