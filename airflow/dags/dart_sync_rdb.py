"""
DART Sync DAG — 챗봇 기업 분석의 실적·공시

- dart_corps: DART 고유번호 전체 (종목코드 → corp_code, 그래프 밖 상장사 안내용)
- stock_disclosures: 그래프 종목의 공시 목록. 매일 전체 회사의 최근 3일을 받아 그래프 종목만 남기고,
  공시가 하나도 없는 종목은 회사별로 최근 90일을 백필한다.
- stock_financials: 그래프 종목의 주요계정(매출액·영업이익·순이익·자산·부채·자본).
  최근 5개 사업연도 × 4개 보고서를 매일 다시 받는다 (100개 회사씩 묶어 하루 수십 건).
  같은 테이블에 현금흐름(영업활동현금흐름·유형/무형자산의 취득)도 둔다. 현금흐름은 회사·보고서마다 한 번 불러야 해서
  주요계정이 있는 보고서 중 아직 받지 않았거나 정정으로 접수번호가 바뀐 것만, 최근 보고서부터 하루 상한까지 받는다.
  사업보고서는 모든 연도, 분·반기 보고서는 최근 4분기 합계와 전년 동기 비교에 필요한 직전 연도부터.
  사업보고서는 연결이 있어도 별도를 함께 받는다 (금융 자회사가 연결 영업현금흐름을 왜곡하는지 가리는 대조용).

API 키는 관리자 페이지에서 저장한 dart_settings(암호문)만 쓴다. 없으면 건너뛴다. 본문은 dart_sync.py에 있다.
"""

from datetime import datetime, timedelta

from airflow.sdk import DAG
from airflow.providers.standard.operators.python import PythonOperator

import dart_sync

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 2,
    'retry_delay': timedelta(minutes=10),
    'email_on_failure': False,
}

dag = DAG(
    'dart_sync_rdb',
    default_args=default_args,
    description='DART 고유번호·공시·주요계정 RDB 동기화 (챗봇 기업 분석)',
    schedule='20 19 * * 1-5',  # 평일 19:20 KST — 장 마감 후 공시까지 반영
    catchup=False,
    max_active_runs=1,
    tags=['dart', 'daily', 'rdb'],
)


t_corps = PythonOperator(task_id='sync_corps', python_callable=dart_sync.sync_corps, dag=dag)
t_disclosures = PythonOperator(task_id='sync_disclosures', python_callable=dart_sync.sync_disclosures, dag=dag)
t_financials = PythonOperator(task_id='sync_financials', python_callable=dart_sync.sync_financials, dag=dag)
t_cash_flows = PythonOperator(task_id='sync_cash_flows', python_callable=dart_sync.sync_cash_flows, dag=dag)

t_corps >> [t_disclosures, t_financials]
t_financials >> t_cash_flows
