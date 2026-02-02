"""
ETF Atlas Daily ETL DAG
- ETF 목록 수집
- 구성종목(PDF) 수집
- 가격 데이터 수집
- 포트폴리오 변화 감지

데이터 저장: Apache AGE (Graph DB)
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
    'etf_daily_etl',
    default_args=default_args,
    description='ETF 데이터 일일 수집 파이프라인 (Apache AGE)',
    schedule_interval='0 8 * * 1-5',  # 평일 08:00 KST
    catchup=False,
    tags=['etf', 'daily', 'age'],
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


def init_age(conn):
    """Initialize Apache AGE for the connection"""
    cur = conn.cursor()
    cur.execute("LOAD 'age';")
    cur.execute("SET search_path = ag_catalog, '$user', public;")
    conn.commit()
    return cur


def execute_cypher(cur, cypher_query, params=None):
    """Execute Cypher query via Apache AGE"""
    if params:
        # Escape parameters for Cypher
        for key, value in params.items():
            if value is None:
                cypher_query = cypher_query.replace(f'${key}', 'null')
            elif isinstance(value, bool):
                cypher_query = cypher_query.replace(f'${key}', 'true' if value else 'false')
            elif isinstance(value, (int, float)):
                cypher_query = cypher_query.replace(f'${key}', str(value))
            else:
                # 모든 다른 타입은 문자열로 변환
                str_value = str(value) if value is not None else ''
                escaped = str_value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
                cypher_query = cypher_query.replace(f'${key}', f"'{escaped}'")

    sql = f"""
        SELECT * FROM cypher('etf_graph', $$
            {cypher_query}
        $$) as (result agtype);
    """
    cur.execute(sql)
    return cur.fetchall()


def collect_etf_list(**context):
    """Task 1: ETF 목록 수집"""
    from pykrx import stock

    date = context['ds_nodash']
    log.info(f"Collecting ETF list for date: {date}")

    try:
        tickers = stock.get_etf_ticker_list(date)
        log.info(f"Found {len(tickers)} ETFs")

        filtered_tickers = filter_etf_universe(tickers, date)
        log.info(f"After filtering: {len(filtered_tickers)} ETFs")

        return filtered_tickers
    except Exception as e:
        log.error(f"Failed to collect ETF list: {e}")
        raise


def filter_etf_universe(tickers: list, date: str) -> list:
    """ETF 유니버스 필터링"""
    from pykrx import stock

    EXCLUDE_KEYWORDS = [
        '레버리지', '인버스', '2X', '곱버스', '2배', '3배',
        '합성', '선물', '파생', 'synthetic',
        '커버드콜', '커버드', 'covered', '프리미엄',
        '채권', '국채', '회사채', '크레딧', '금리', '국공채', '단기채', '장기채',
        '금현물', '골드', 'gold', '은현물', '실버', 'silver', '원유', 'WTI', '구리', '원자재',
        '달러', '엔화', '유로', '원화', '통화', 'USD', 'JPY', 'EUR',
        '머니마켓', 'CD', '단기', 'MMF', 'CMA',
        '리츠', 'REITs', 'REIT',
    ]

    MIN_ASSET_BILLION = 1000
    MIN_ASSET_WON = MIN_ASSET_BILLION * 100_000_000

    try:
        df_cap = stock.get_market_cap(date, date, "ALL")
        log.info(f"Retrieved market cap data for {len(df_cap)} items")
    except Exception as e:
        log.error(f"Failed to get market cap data: {e}")
        df_cap = None

    filtered = []
    skipped_by_keyword = 0
    skipped_by_asset = 0

    for ticker in tickers:
        try:
            name = stock.get_etf_ticker_name(ticker)
            name_lower = name.lower() if name else ''

            if any(kw.lower() in name_lower for kw in EXCLUDE_KEYWORDS):
                skipped_by_keyword += 1
                continue

            if df_cap is not None and ticker in df_cap.index:
                market_cap = df_cap.loc[ticker].get('시가총액', 0)
                if market_cap < MIN_ASSET_WON:
                    skipped_by_asset += 1
                    continue

            filtered.append(ticker)

        except Exception as e:
            log.warning(f"Failed to check ETF {ticker}: {e}")
            continue

    log.info(f"Filtered: {len(filtered)} ETFs (excluded by keyword: {skipped_by_keyword}, by asset: {skipped_by_asset})")
    return filtered


def collect_etf_metadata(**context):
    """Task 2: ETF 메타데이터 수집 및 AGE에 저장"""
    from pykrx import stock
    import time

    ti = context['ti']
    tickers = ti.xcom_pull(task_ids='collect_etf_list')

    if not tickers:
        log.warning("No tickers to process")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        for ticker in tickers:
            try:
                name = stock.get_etf_ticker_name(ticker)

                # Create or update ETF node in Apache AGE
                cypher = """
                    MERGE (e:ETF {code: $code})
                    SET e.name = $name, e.updated_at = $updated_at
                    RETURN e
                """
                execute_cypher(cur, cypher, {
                    'code': ticker,
                    'name': name,
                    'updated_at': datetime.now().isoformat()
                })

                time.sleep(0.1)

            except Exception as e:
                log.warning(f"Failed to save ETF {ticker}: {e}")
                continue

        conn.commit()
        log.info(f"Saved metadata for {len(tickers)} ETFs to Apache AGE")

    finally:
        cur.close()
        conn.close()


def collect_holdings(**context):
    """Task 3: ETF 구성종목 수집 및 AGE에 저장"""
    from pykrx import stock
    import pandas as pd
    import time

    ti = context['ti']
    tickers = ti.xcom_pull(task_ids='collect_etf_list')
    date_str = context['ds']

    if not tickers:
        log.warning("No tickers to process")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    success_count = 0
    fail_count = 0

    try:
        for ticker in tickers:
            try:
                df = stock.get_etf_portfolio_deposit_file(ticker)

                if df is None or df.empty:
                    log.warning(f"No holdings data for {ticker}")
                    continue

                for idx, row in df.iterrows():
                    # 인덱스가 종목 코드 (티커)
                    stock_code = str(idx)

                    # 종목명은 별도 API 호출로 조회
                    try:
                        stock_name = stock.get_market_ticker_name(stock_code)
                    except Exception:
                        stock_name = None

                    # stock_name이 None이거나 빈 값이면 stock_code로 대체
                    if not stock_name or (hasattr(stock_name, '__len__') and len(stock_name) == 0):
                        stock_name = stock_code
                    else:
                        stock_name = str(stock_name)  # 명시적으로 문자열 변환

                    weight = float(row.get('비중', 0))
                    # '계약수' 또는 '주수' 컬럼 사용
                    shares_val = row.get('계약수', row.get('주수', 0))
                    shares = int(shares_val) if shares_val and not pd.isna(shares_val) else 0

                    if not stock_code:
                        continue

                    # Create Stock node
                    cypher_stock = """
                        MERGE (s:Stock {code: $code})
                        SET s.name = $name
                        RETURN s
                    """
                    execute_cypher(cur, cypher_stock, {
                        'code': stock_code,
                        'name': stock_name
                    })

                    # Create HOLDS edge with date property
                    cypher_holds = """
                        MATCH (e:ETF {code: $etf_code})
                        MATCH (s:Stock {code: $stock_code})
                        MERGE (e)-[h:HOLDS {date: $date}]->(s)
                        SET h.weight = $weight, h.shares = $shares
                        RETURN h
                    """
                    execute_cypher(cur, cypher_holds, {
                        'etf_code': ticker,
                        'stock_code': stock_code,
                        'date': date_str,
                        'weight': weight,
                        'shares': shares
                    })

                conn.commit()
                success_count += 1
                time.sleep(0.5)

            except Exception as e:
                log.warning(f"Failed to collect holdings for {ticker}: {e}")
                conn.rollback()
                fail_count += 1
                continue

        log.info(f"Holdings collection complete. Success: {success_count}, Failed: {fail_count}")

    finally:
        cur.close()
        conn.close()


def collect_prices(**context):
    """Task 4: ETF 가격 데이터 수집 (관계형 테이블에 저장 - 시계열 데이터)"""
    from pykrx import stock
    import time

    ti = context['ti']
    tickers = ti.xcom_pull(task_ids='collect_etf_list')
    date_str = context['ds']
    date_nodash = context['ds_nodash']

    if not tickers:
        log.warning("No tickers to process")
        return

    conn = get_db_connection()
    cur = conn.cursor()

    success_count = 0

    try:
        for ticker in tickers:
            try:
                df = stock.get_etf_ohlcv_by_date(date_nodash, date_nodash, ticker)

                if df is None or df.empty:
                    continue

                for idx, row in df.iterrows():
                    cur.execute("""
                        INSERT INTO etf_prices (etf_code, date, open_price, high_price, low_price, close_price, volume)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (etf_code, date) DO UPDATE SET
                            open_price = EXCLUDED.open_price,
                            high_price = EXCLUDED.high_price,
                            low_price = EXCLUDED.low_price,
                            close_price = EXCLUDED.close_price,
                            volume = EXCLUDED.volume
                    """, (
                        ticker,
                        idx.strftime('%Y-%m-%d'),
                        int(row.get('시가', 0)),
                        int(row.get('고가', 0)),
                        int(row.get('저가', 0)),
                        int(row.get('종가', 0)),
                        int(row.get('거래량', 0))
                    ))

                conn.commit()
                success_count += 1
                time.sleep(0.3)

            except Exception as e:
                log.warning(f"Failed to collect prices for {ticker}: {e}")
                conn.rollback()
                continue

        log.info(f"Price collection complete. Success: {success_count}")

    finally:
        cur.close()
        conn.close()


def detect_portfolio_changes(**context):
    """Task 5: 포트폴리오 변화 감지 및 AGE에 저장"""

    ti = context['ti']
    tickers = ti.xcom_pull(task_ids='collect_etf_list')
    today = context['ds']
    yesterday = (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')

    if not tickers:
        log.warning("No tickers to process")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    changes_count = 0

    try:
        for ticker in tickers:
            try:
                # Get today's holdings from AGE
                cypher_today = """
                    MATCH (e:ETF {code: $etf_code})-[h:HOLDS {date: $date}]->(s:Stock)
                    RETURN s.code as stock_code, s.name as stock_name, h.weight as weight
                """
                today_results = execute_cypher(cur, cypher_today, {
                    'etf_code': ticker,
                    'date': today
                })
                today_holdings = {}
                for row in today_results:
                    if row[0]:
                        import json
                        data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                        if isinstance(data, dict):
                            code = data.get('stock_code', '')
                            if code:
                                today_holdings[code] = {
                                    'name': data.get('stock_name', ''),
                                    'weight': float(data.get('weight', 0))
                                }

                # Get yesterday's holdings from AGE
                cypher_yesterday = """
                    MATCH (e:ETF {code: $etf_code})-[h:HOLDS {date: $date}]->(s:Stock)
                    RETURN s.code as stock_code, s.name as stock_name, h.weight as weight
                """
                yesterday_results = execute_cypher(cur, cypher_yesterday, {
                    'etf_code': ticker,
                    'date': yesterday
                })
                yesterday_holdings = {}
                for row in yesterday_results:
                    if row[0]:
                        import json
                        data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                        if isinstance(data, dict):
                            code = data.get('stock_code', '')
                            if code:
                                yesterday_holdings[code] = {
                                    'name': data.get('stock_name', ''),
                                    'weight': float(data.get('weight', 0))
                                }

                if not today_holdings or not yesterday_holdings:
                    continue

                changes = detect_changes(ticker, today_holdings, yesterday_holdings)

                for change in changes:
                    # Create Change node and connect to ETF
                    import uuid
                    change_id = str(uuid.uuid4())

                    cypher_change = """
                        MATCH (e:ETF {code: $etf_code})
                        CREATE (c:Change {
                            id: $change_id,
                            stock_code: $stock_code,
                            stock_name: $stock_name,
                            change_type: $change_type,
                            before_weight: $before_weight,
                            after_weight: $after_weight,
                            weight_change: $weight_change,
                            detected_at: $detected_at
                        })
                        CREATE (e)-[:HAS_CHANGE]->(c)
                        RETURN c
                    """
                    execute_cypher(cur, cypher_change, {
                        'etf_code': ticker,
                        'change_id': change_id,
                        'stock_code': change['stock_code'],
                        'stock_name': change['stock_name'],
                        'change_type': change['type'],
                        'before_weight': change['before_weight'] if change['before_weight'] else 0,
                        'after_weight': change['after_weight'] if change['after_weight'] else 0,
                        'weight_change': change.get('weight_change', 0),
                        'detected_at': today
                    })
                    changes_count += 1

                conn.commit()

            except Exception as e:
                log.warning(f"Failed to detect changes for {ticker}: {e}")
                conn.rollback()
                continue

        log.info(f"Detected {changes_count} portfolio changes")

    finally:
        cur.close()
        conn.close()


def detect_changes(etf_code: str, today_holdings: dict, yesterday_holdings: dict) -> list:
    """두 스냅샷 비교하여 변화 감지"""

    changes = []

    # 신규 편입
    for code, data in today_holdings.items():
        if code not in yesterday_holdings:
            changes.append({
                'type': 'added',
                'stock_code': code,
                'stock_name': data['name'],
                'before_weight': None,
                'after_weight': data['weight'],
                'weight_change': data['weight']
            })

    # 완전 제외
    for code, data in yesterday_holdings.items():
        if code not in today_holdings:
            changes.append({
                'type': 'removed',
                'stock_code': code,
                'stock_name': data['name'],
                'before_weight': data['weight'],
                'after_weight': None,
                'weight_change': -data['weight']
            })

    # 비중 5%p 이상 변화
    for code, today_data in today_holdings.items():
        if code in yesterday_holdings:
            yesterday_data = yesterday_holdings[code]
            diff = today_data['weight'] - yesterday_data['weight']
            if abs(diff) >= 5.0:
                changes.append({
                    'type': 'increased' if diff > 0 else 'decreased',
                    'stock_code': code,
                    'stock_name': today_data['name'],
                    'before_weight': yesterday_data['weight'],
                    'after_weight': today_data['weight'],
                    'weight_change': diff
                })

    return changes


# Define tasks
start = EmptyOperator(task_id='start', dag=dag)
end = EmptyOperator(task_id='end', dag=dag)

task_collect_etf_list = PythonOperator(
    task_id='collect_etf_list',
    python_callable=collect_etf_list,
    dag=dag,
)

task_collect_metadata = PythonOperator(
    task_id='collect_etf_metadata',
    python_callable=collect_etf_metadata,
    dag=dag,
)

task_collect_holdings = PythonOperator(
    task_id='collect_holdings',
    python_callable=collect_holdings,
    dag=dag,
)

task_collect_prices = PythonOperator(
    task_id='collect_prices',
    python_callable=collect_prices,
    dag=dag,
)

task_detect_changes = PythonOperator(
    task_id='detect_portfolio_changes',
    python_callable=detect_portfolio_changes,
    dag=dag,
)

# Define dependencies
start >> task_collect_etf_list >> task_collect_metadata
task_collect_metadata >> [task_collect_holdings, task_collect_prices]
task_collect_holdings >> task_detect_changes >> end
task_collect_prices >> end
