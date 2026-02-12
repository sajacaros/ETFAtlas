"""
ETF RDB Sync DAG
- KRX API에서 ETF 일별매매정보 수집
- RDB etfs 테이블에 동기화 (pg_trgm 퍼지 검색용)

AGE DAG(etf_daily_etl)과 독립적으로 동작.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
import logging

log = logging.getLogger(__name__)

# ETF 이름 prefix → 운용사 매핑
ETF_COMPANY_MAP = {
    'KODEX': '삼성자산운용',
    'KoAct': '삼성액티브자산운용',
    'TIGER': '미래에셋자산운용',
    'RISE': 'KB자산운용',
    'ACE': '한국투자신탁운용',
    'HANARO': 'NH아문디자산운용',
    'SOL': '신한자산운용',
    'PLUS': '한화자산운용',
    'KIWOOM': '키움자산운용',
    '1Q': '하나자산운용',
    'TIMEFOLIO': '타임폴리오자산운용',
    'TIME': '타임폴리오자산운용',
    'WON': '우리자산운용',
    '마이다스': '마이다스자산운용',
    '파워': '교보악사자산운용',
    'BNK': 'BNK자산운용',
    'DAISHIN343': '대신자산운용',
    'HK': '흥국자산운용',
    'UNICORN': '현대자산운용',
}


def get_company_from_etf_name(name: str) -> str:
    """ETF 이름에서 운용사 추출"""
    for prefix, company in ETF_COMPANY_MAP.items():
        if name.startswith(prefix):
            return company
    return '기타'


default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
    'email_on_failure': False,
}

dag = DAG(
    'etf_rdb_etl',
    default_args=default_args,
    description='ETF 메타데이터 RDB 동기화 파이프라인',
    schedule_interval='0 7 * * 1-5',  # 평일 07:00 KST
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
    """KRX API에서 ETF 일별매매정보 조회 (최근 거래일 자동 탐색)

    AGE 의존 없이 단순히 최근 거래일 데이터를 수집한다.
    """
    import os
    from krx_api_client import KRXApiClient

    date = context['ds_nodash']

    auth_key = os.environ.get('KRX_AUTH_KEY', '')
    if not auth_key:
        log.warning("KRX_AUTH_KEY not set, cannot fetch KRX data")
        return []

    try:
        client = KRXApiClient(auth_key)

        # 주어진 날짜부터 최대 7일 전까지 거래일 탐색
        base_date = datetime.strptime(date, '%Y%m%d')
        for i in range(7):
            check_date = (base_date - timedelta(days=i)).strftime('%Y%m%d')
            result = client.get_etf_daily_trading(check_date)
            if result:
                if i > 0:
                    log.info(f"No data for {date}, using latest trading day: {check_date}")
                return [
                    {
                        'code': item.code,
                        'name': item.name,
                        'net_assets': item.net_assets,
                    }
                    for item in result
                ]

        log.warning(f"No trading data found within 7 days from {date}")
        return []
    except Exception as e:
        log.error(f"Failed to get KRX daily data: {e}")
        return []


def sync_etfs_to_rdb(**context):
    """모든 ETF 메타데이터를 etfs RDB 테이블에 동기화"""
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
                issuer = get_company_from_etf_name(item['name'])
                cur.execute("""
                    INSERT INTO etfs (code, name, issuer, net_assets, updated_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        issuer = EXCLUDED.issuer,
                        net_assets = EXCLUDED.net_assets,
                        updated_at = CURRENT_TIMESTAMP
                """, (item['code'], item['name'], issuer, item['net_assets']))
                success_count += 1
            except Exception as e:
                log.warning(f"Failed to sync ETF {item.get('code', 'unknown')}: {e}")
                continue

        conn.commit()
        log.info(f"Synced {success_count} ETFs to RDB etfs table")

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
