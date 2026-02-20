"""
ETF Metadata RDB Sync DAG (경량)
- KRX API에서 전체 ETF 목록 수집
- RDB etfs 테이블에 code + name만 동기화 (포트폴리오 비유니버스 ETF 이름 조회용)

ETF 상세 메타데이터(net_assets, expense_ratio, issuer 등)는 AGE에서 관리.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
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
    schedule_interval='30 8 * * 1-5',  # 평일 08:30 KST
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


def fetch_krx_data(**context):
    """KRX API에서 전체 ETF 목록 조회 (code + name만)"""
    import os
    from krx_api_client import KRXApiClient

    date = context['ds_nodash']

    auth_key = os.environ.get('KRX_AUTH_KEY', '')
    if not auth_key:
        log.warning("KRX_AUTH_KEY not set, cannot fetch KRX data")
        return []

    try:
        client = KRXApiClient(auth_key)

        base_date = datetime.strptime(date, '%Y%m%d')
        for i in range(7):
            check_date = (base_date - timedelta(days=i)).strftime('%Y%m%d')
            result = client.get_etf_daily_trading(check_date)
            if result:
                if i > 0:
                    log.info(f"No data for {date}, using latest trading day: {check_date}")
                return [
                    {'code': item.code, 'name': item.name}
                    for item in result
                ]

        log.warning(f"No trading data found within 7 days from {date}")
        return []
    except Exception as e:
        log.error(f"Failed to get KRX daily data: {e}")
        return []


def sync_etfs_to_rdb(**context):
    """전체 ETF의 code + name을 etfs RDB 테이블에 동기화"""
    ti = context['ti']
    krx_data_dicts = ti.xcom_pull(task_ids='fetch_krx_data')
    if not krx_data_dicts:
        log.warning("No KRX data available for RDB sync")
        return

    conn = get_db_connection()
    cur = conn.cursor()
    success_count = 0

    try:
        for item in krx_data_dicts:
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

task_fetch_krx_data = PythonOperator(
    task_id='fetch_krx_data',
    python_callable=fetch_krx_data,
    dag=dag,
)

task_sync_etfs_to_rdb = PythonOperator(
    task_id='sync_etfs_to_rdb',
    python_callable=sync_etfs_to_rdb,
    dag=dag,
)

# Define dependencies
start >> task_fetch_krx_data >> task_sync_etfs_to_rdb >> end
