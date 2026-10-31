"""
주간 매수 의견 DAG — 토요일 아침 백엔드가 ETF가 담은 주식 전체에 매수 의견을 내고 상위 10개를 디스코드로 알리게 한다

판정은 백엔드(app/services/weekly_opinion.py)가 한다. airflow에는 pydantic_ai·챗봇 스킬이 없어 이 DAG는
언제 돌지만 정한다 — 그래서 DAG를 꺼 둔 로컬에서는 돌지 않는다.

1. 백엔드 내부 엔드포인트(POST /internal/weekly-opinion/{날짜})로 차례를 시작시킨다.
2. opinion_runs의 그 날짜 행이 done이 될 때까지 POLL마다 본다(PythonSensor, reschedule — 기다리는 동안 워커 자리를 비운다).
   볼 때마다 다시 부른다 — 이미 돌고 있으면 백엔드가 무시하고,
   백엔드가 중간에 다시 떠서 30분(STALE) 넘게 소식이 없으면 그 차례를 이어 맡는다(판정한 종목은 건너뛴다).

수동 실행: date(YYYY-MM-DD, 비우면 오늘 KST). 이미 끝난 차례를 다시 돌리려면 opinion_runs의 그 날짜 행을 지운다.
"""

import logging
import os
from datetime import date, datetime, timedelta

import requests
from airflow.sdk import DAG, Param
from airflow.providers.standard.sensors.python import PythonSensor

from app.utils.encryption import internal_token

from market_calendar import KST
from rdb import connection

log = logging.getLogger(__name__)

BACKEND_URL = os.environ.get('BACKEND_URL', 'http://backend:8000')
TOKEN_PURPOSE = 'weekly_opinion'  # backend routers/internal.py WEEKLY_OPINION
POLL = 300  # 초
RUN_HOURS = 6  # 10-31 첫 차례는 572종목에 81분

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'email_on_failure': False,
}

dag = DAG(
    'weekly_opinion',
    default_args=default_args,
    description='토요일 전 종목 매수 의견 → 디스코드 상위 10개 (판정은 백엔드)',
    schedule='0 7 * * 6',  # 토요일 07:00 KST — 금요일 종가·재무가 들어온 뒤
    catchup=False,
    max_active_runs=1,
    params={
        'date': Param('', type='string', description='차례 날짜 YYYY-MM-DD (KST). 비우면 오늘'),
    },
    tags=['opinion', 'discord'],
)


def run_status(run_on: date) -> str | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM opinion_runs WHERE run_on = %s", (run_on,))
        row = cur.fetchone()
    return row[0] if row else None


def start(run_on: date) -> None:
    try:
        resp = requests.post(f"{BACKEND_URL}/internal/weekly-opinion/{run_on.isoformat()}",
                             headers={'X-Internal-Token': internal_token(TOKEN_PURPOSE)}, timeout=30)
        resp.raise_for_status()
        if resp.json().get('started'):
            log.info("Weekly opinion %s started", run_on)
    except requests.RequestException as e:
        # 백엔드가 다시 뜨는 중이면 다음 POLL에 다시 부른다
        log.warning("Weekly opinion start failed: %s", e)


def run_date(params) -> date:
    raw = (params.get('date') or '').strip()
    return date.fromisoformat(raw) if raw else datetime.now(KST).date()


def week_done(**context) -> bool:
    """끝났으면 True. 아니면 시작(또는 이어 맡기)을 부르고 False — POLL 뒤에 다시 본다."""
    run_on = run_date(context['params'])
    status = run_status(run_on)
    if status == 'done':
        log.info("Weekly opinion %s done", run_on)
        return True
    log.info("Weekly opinion %s status=%s", run_on, status)
    start(run_on)
    return False


PythonSensor(
    task_id='run_week',
    python_callable=week_done,
    mode='reschedule',
    poke_interval=POLL,
    timeout=RUN_HOURS * 3600,  # 넘으면 실패 — 백엔드 로그와 opinion_runs를 본다
    dag=dag,
)
