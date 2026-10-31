"""
챗봇 점검 DAG — 전날 대화를 검토해 제대로 안 나온 답과 고칠 곳을 디스코드로 알린다

고치는 건 사람이 한다. 이 DAG는 보고만 하고 스킬·예제·코드를 건드리지 않는다.

1. 신호 모으기 (LLM 없음): 실패·중단·되묻기로 끝난 답, 비거나 실패한 영역, 싫어요, agent 도구 오류 반복,
   같은 질문인데 영역 구성이 달랐던 경우
2. 판정 (등록된 LLM, 추론 끔): 세션마다 대화 전체를 보고 문제 턴과 원인·제안을 고른다.
   다음 턴의 사용자 말("재무 스킬에서 가져오면 되잖아")이 가장 강한 신호라 턴 하나가 아니라 세션 단위로 본다.
   스킬 목록은 backend 스킬 파일의 name·description을 읽어 넘긴다 (airflow에는 pydantic_ai가 없어 import하지 않는다)
3. 디스코드 발송: 발송 이력(discord_notification_logs, kind='chat_review')에 성공 기록이 있는 날짜는 건너뛴다.
   몇 개를 보낸 뒤 실패했으면 재시도가 그때의 판정(이력의 items)으로 남은 메시지만 보낸다

본문은 chat_reviewer.py에 있다.

수동 실행: date(YYYY-MM-DD, 비우면 어제)와 dry_run(보내지 않고 로그로만)을 받는다.
"""

from datetime import datetime, timedelta

from airflow.sdk import DAG, Param
from airflow.providers.standard.operators.python import PythonOperator

from chat_reviewer import resolve_date, run_review

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'email_on_failure': False,
}

dag = DAG(
    'chat_review',
    default_args=default_args,
    description='전날 챗봇 대화 점검 → 디스코드 보고',
    schedule='0 8 * * *',  # 매일 08:00 KST — 전날 대화. 08:40·08:50 수집 전이라 LLM·DB가 한가하다
    catchup=False,
    max_active_runs=1,
    params={
        'date': Param('', type='string', description='점검할 날짜 YYYY-MM-DD (KST). 비우면 어제'),
        'dry_run': Param(False, type='boolean', description='보내지 않고 로그로만 남긴다'),
    },
    tags=['chat', 'discord'],
)


def review_and_notify(**context):
    params = context['params']
    run_review(resolve_date(params), dry_run=bool(params.get('dry_run')))


PythonOperator(
    task_id='review_and_notify',
    python_callable=review_and_notify,
    execution_timeout=timedelta(hours=1),
    dag=dag,
)
