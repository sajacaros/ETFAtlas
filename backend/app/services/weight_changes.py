from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models.discord_setting import DiscordSetting
from ..models.weight_change import WeightChange, WeightChangeDate

DEFAULT_ALERT_THRESHOLD = 3.0


def get_alert_threshold(db: Session) -> float:
    """비중변화 기준값(%p). 디스코드 알림과 웹 비중변화 화면이 같은 값을 쓴다 (관리자 페이지에서 설정)."""
    setting = db.get(DiscordSetting, 1)
    return setting.threshold if setting else DEFAULT_ALERT_THRESHOLD


def resolve_change_date(db: Session, base_date: str | None = None) -> str | None:
    """비중 변화가 계산된 날짜 중 base_date 이하(없으면 전체)에서 가장 최근 날짜."""
    q = db.query(func.max(WeightChangeDate.base_date))
    if base_date:
        q = q.filter(WeightChangeDate.base_date <= base_date)
    return q.scalar()


def get_significant_changes(db: Session, base_date: str, threshold: float) -> list[WeightChange]:
    """Airflow가 저장한 base_date의 액티브 ETF 비중 변화 중 |변화량| > threshold (변화량 큰 순)."""
    return (
        db.query(WeightChange)
        .filter(WeightChange.base_date == base_date, func.abs(WeightChange.weight_change) > threshold)
        .order_by(func.abs(WeightChange.weight_change).desc(), WeightChange.etf_code, WeightChange.stock_code)
        .all()
    )
