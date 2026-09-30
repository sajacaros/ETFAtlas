"""
ETF Metadata RDB Sync DAG (경량)
- KIS 종목 마스터 파일에서 전체 ETF 목록 수집
- RDB etfs 테이블에 code + name만 동기화 (포트폴리오 비유니버스 ETF 이름 조회용)

ETF 상세 메타데이터(net_assets, expense_ratio, issuer 등)는 AGE에서 관리.
"""

from datetime import datetime, timedelta
from airflow.sdk import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.standard.operators.empty import EmptyOperator
import logging

log = logging.getLogger(__name__)

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
    'email_on_failure': False,
}

dag = DAG(
    'rdb_sync_metadata',
    default_args=default_args,
    description='ETF 코드/이름 RDB 동기화 (포트폴리오용)',
    schedule='30 8 * * 1-5',  # 평일 08:30 KST
    catchup=False,
    tags=['etf', 'daily', 'rdb'],
)


def get_db_connection():
    """Get database connection"""
    import psycopg2
    import os

    db_url = os.environ.get(
        'DATABASE_URL',
        'postgresql://postgres:postgres@db:5432/etf_atlas'
    )

    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', '')

    if '@' in db_url:
        auth, host_db = db_url.split('@')
        user, password = auth.split(':')
        host_port, database = host_db.split('/')
        if ':' in host_port:
            host, port = host_port.split(':')
        else:
            host = host_port
            port = 5432
    else:
        user = 'postgres'
        password = 'postgres'
        host = 'db'
        port = 5432
        database = 'etf_atlas'

    conn = psycopg2.connect(
        host=host,
        port=int(port),
        database=database,
        user=user,
        password=password
    )
    return conn


def fetch_etf_master(**context):
    """KIS 종목 마스터 파일에서 전체 ETF 목록 조회 (code + name, 인증 불필요)"""
    from kis_api_client import fetch_etf_master as fetch

    try:
        etfs = fetch()
        log.info(f"Fetched {len(etfs)} ETFs from KIS master file")
        return [{'code': code, 'name': name} for code, name in etfs]
    except Exception as e:
        log.error(f"Failed to fetch KIS master file: {e}")
        return []


def sync_etfs_to_rdb(**context):
    """전체 ETF의 code + name을 etfs RDB 테이블에 동기화"""
    ti = context['ti']
    etf_dicts = ti.xcom_pull(task_ids='fetch_etf_master')
    if not etf_dicts:
        log.warning("No ETF master data available for RDB sync")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    success_count = 0

    try:
        for item in etf_dicts:
            try:
                cur.execute("""
                    INSERT INTO etfs (code, name, updated_at)
                    VALUES (%s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        updated_at = CURRENT_TIMESTAMP
                """, (item['code'], item['name']))
                success_count += 1
            except Exception as e:
                log.warning(f"Failed to sync ETF {item.get('code', 'unknown')}: {e}")
                continue

        conn.commit()
        log.info(f"Synced {success_count} ETFs to RDB etfs table (code + name only)")

    finally:
        cur.close()
        conn.close()


# Define tasks
start = EmptyOperator(task_id='start', dag=dag)
end = EmptyOperator(task_id='end', dag=dag)

task_fetch_etf_master = PythonOperator(
    task_id='fetch_etf_master',
    python_callable=fetch_etf_master,
    dag=dag,
)

task_sync_etfs_to_rdb = PythonOperator(
    task_id='sync_etfs_to_rdb',
    python_callable=sync_etfs_to_rdb,
    dag=dag,
)

# Define dependencies
start >> task_fetch_etf_master >> task_sync_etfs_to_rdb >> end
