"""Airflow DAG가 부르는 내부 엔드포인트. X-Internal-Token(utils.encryption.internal_token)으로만 연다."""
import hmac
from datetime import date

from fastapi import APIRouter, Header, HTTPException

from ..services import weekly_opinion
from ..utils.encryption import internal_token

router = APIRouter()

WEEKLY_OPINION = "weekly_opinion"


def _check(token: str | None, purpose: str) -> None:
    if not token or not hmac.compare_digest(token, internal_token(purpose)):
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/weekly-opinion/{run_on}", status_code=202)
async def start_weekly_opinion(run_on: date, x_internal_token: str | None = Header(None)):
    """그 차례를 백그라운드로 시작한다. 이미 끝났거나 돌고 있으면 started=false (DAG가 opinion_runs로 끝을 지켜본다)."""
    _check(x_internal_token, WEEKLY_OPINION)
    return {"started": await weekly_opinion.start(run_on)}
