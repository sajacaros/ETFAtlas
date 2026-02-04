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
    """Task 1: ETF 전체 목록 수집 (메타데이터용)"""
    from pykrx import stock

    date = context['ds_nodash']
    log.info(f"Collecting ETF list for date: {date}")

    try:
        tickers = stock.get_etf_ticker_list(date)
        log.info(f"Found {len(tickers)} ETFs (all)")
        return tickers
    except Exception as e:
        log.error(f"Failed to collect ETF list: {e}")
        raise


def fetch_krx_data(**context):
    """Task 1-1: KRX API에서 일별매매정보 조회 (최근 거래일 자동 탐색)"""
    date = context['ds_nodash']

    krx_data, actual_date = get_krx_daily_data(date)
    log.info(f"Fetched {len(krx_data)} ETFs from KRX API (trading date: {actual_date})")

    # 실제 거래일을 XCom에 저장
    ti = context['ti']
    ti.xcom_push(key='trading_date', value=actual_date)

    # XCom은 직렬화가 필요하므로 dict 리스트로 변환
    return [
        {
            'date': item.date,
            'code': item.code,
            'name': item.name,
            'close_price': item.close_price,
            'open_price': item.open_price,
            'high_price': item.high_price,
            'low_price': item.low_price,
            'volume': item.volume,
            'trade_value': item.trade_value,
            'nav': item.nav,
            'market_cap': item.market_cap,
            'net_assets': item.net_assets,
        }
        for item in krx_data
    ]


def filter_etf_list(**context):
    """Task 1-2: DB 유니버스 기반 ETF 필터링 (구성목록 수집용)

    - DB의 etf_universe 테이블에서 기존 ETF 목록 읽기
    - 새로운 ETF 중 조건(500억 이상 + 필터 통과) 충족하면 유니버스에 추가
    - 한번 등록된 ETF는 계속 유지
    """
    ti = context['ti']
    krx_data_dicts = ti.xcom_pull(task_ids='fetch_krx_data')

    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # 1. 기존 유니버스 ETF 목록 읽기
        cur.execute("SELECT code FROM etf_universe WHERE is_active = TRUE")
        existing_codes = set(row[0] for row in cur.fetchall())
        log.info(f"Existing universe: {len(existing_codes)} ETFs")

        # 2. 새로운 ETF 확인 및 추가
        if krx_data_dicts:
            new_candidates = check_new_universe_candidates(krx_data_dicts, existing_codes)

            for candidate in new_candidates:
                cur.execute('''
                    INSERT INTO etf_universe (code, name, index_name, initial_net_assets)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (code) DO NOTHING
                ''', (candidate['code'], candidate['name'], candidate.get('index_name', ''), candidate['net_assets']))
                existing_codes.add(candidate['code'])

            if new_candidates:
                conn.commit()
                log.info(f"Added {len(new_candidates)} new ETFs to universe")

        universe_tickers = list(existing_codes)
        log.info(f"Total universe: {len(universe_tickers)} ETFs")
        return universe_tickers

    finally:
        cur.close()
        conn.close()


def check_new_universe_candidates(krx_data_dicts: list, existing_codes: set) -> list:
    """새로운 유니버스 후보 ETF 확인

    조건:
    - 기존 유니버스에 없음
    - 순자산 500억 이상
    - 제외 키워드 미포함
    - 해외 관련 키워드 미포함
    """
    FOREIGN_NAME_KEYWORDS = [
        '미국', '중국', '차이나', '일본', '인도', '베트남', '대만', '유럽', '독일',
        '글로벌', 'Global', 'China', 'Japan', 'India', 'US', 'USA',
        'S&P', 'NASDAQ', '나스닥', '다우존스',
        'MSCI', '선진국', '신흥국', '아시아',
        '테슬라', 'Tesla', '엔비디아', 'NVIDIA', '구글', 'Google',
        '애플', 'Apple', '아마존', 'Amazon', '팔란티어', 'Palantir',
        '브로드컴', 'Broadcom', '알리바바', 'Alibaba',
        '월드', 'World', '국제금', '금액티브',
    ]

    EXCLUDE_KEYWORDS = [
        '레버리지', '인버스', '2X', '곱버스', '2배', '3배',
        '합성', '선물', '파생', 'synthetic', '혼합',
        '커버드콜', '커버드', 'covered', '프리미엄',
        '채권', '국채', '회사채', '크레딧', '금리', '국공채', '단기채', '장기채',
        '금융채', '특수채', 'TDF', '전단채', '은행채',
        '국고채', 'TRF',
        '금현물', '골드', 'gold', '은현물', '실버', 'silver', '원유', 'WTI', '구리', '원자재',
        '달러', '엔화', '유로', '원화', '통화', 'USD', 'JPY', 'EUR',
        '머니마켓', 'CD', '단기', 'MMF', 'CMA',
        '리츠', 'REITs', 'REIT',
    ]

    MIN_AUM = 500 * 100_000_000  # 500억

    candidates = []
    for item in krx_data_dicts:
        code = item['code']
        if code in existing_codes:
            continue

        name = item['name']
        name_lower = name.lower()
        net_assets = item.get('net_assets', 0)

        # 조건 확인
        if net_assets < MIN_AUM:
            continue
        if any(kw.lower() in name_lower for kw in EXCLUDE_KEYWORDS):
            continue
        if any(kw.lower() in name_lower or kw in name for kw in FOREIGN_NAME_KEYWORDS):
            continue

        candidates.append({
            'code': code,
            'name': name,
            'index_name': '',  # KRX 일별매매정보에는 index_name이 없음
            'net_assets': net_assets
        })

    return candidates


def get_krx_daily_data(date: str) -> tuple[list, str]:
    """KRX Open API에서 ETF 일별매매정보 조회 (최근 거래일 자동 탐색)

    Args:
        date: 기준일자 (YYYYMMDD 형식)

    Returns:
        tuple: (ETFDailyData 리스트, 실제 조회된 날짜), 실패 시 (빈 리스트, 빈 문자열)
    """
    import os
    from datetime import datetime, timedelta
    from krx_api_client import KRXApiClient

    auth_key = os.environ.get('KRX_AUTH_KEY', '')
    if not auth_key:
        log.warning("KRX_AUTH_KEY not set, cannot fetch KRX data")
        return [], ''

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
                return result, check_date

        log.warning(f"No trading data found within 7 days from {date}")
        return [], ''
    except Exception as e:
        log.error(f"Failed to get KRX daily data: {e}")
        return [], ''


def get_etf_aum_from_krx_data(krx_data: list) -> dict:
    """KRX 일별매매정보에서 AUM 딕셔너리 추출

    Args:
        krx_data: ETFDailyData 리스트

    Returns:
        dict: {ticker: aum} 형태
    """
    return {item.code: item.net_assets for item in krx_data}


def filter_etf_universe(tickers: list, krx_data: list) -> list:
    """ETF 유니버스 필터링

    필터링 조건:
    1. 키워드 제외: 레버리지, 인버스, 합성, 채권, 원자재, 통화, 리츠 등
    2. 순자산총액(AUM) 1000억원 이상

    Args:
        tickers: pykrx에서 조회한 전체 ETF 티커 리스트
        krx_data: KRX API에서 조회한 ETFDailyData 리스트
    """
    EXCLUDE_KEYWORDS = [
        '레버리지', '인버스', '2X', '곱버스', '2배', '3배',
        '합성', '선물', '파생', 'synthetic', '혼합',
        '커버드콜', '커버드', 'covered', '프리미엄',
        '채권', '국채', '회사채', '크레딧', '금리', '국공채', '단기채', '장기채', '은행채',
        '금현물', '골드', 'gold', '은현물', '실버', 'silver', '원유', 'WTI', '구리', '원자재',
        '달러', '엔화', '유로', '원화', '통화', 'USD', 'JPY', 'EUR',
        '머니마켓', 'CD', '단기', 'MMF', 'CMA',
        '리츠', 'REITs', 'REIT',
    ]

    MIN_AUM_BILLION = 1000
    MIN_AUM_WON = MIN_AUM_BILLION * 100_000_000  # 1000억원

    # KRX 데이터를 딕셔너리로 변환 (빠른 조회용)
    krx_dict = {item.code: item for item in krx_data}

    filtered = []
    skipped_by_keyword = 0
    skipped_by_aum = 0
    skipped_no_krx_data = 0

    for ticker in tickers:
        try:
            # KRX 데이터에서 종목명과 AUM 조회
            krx_item = krx_dict.get(ticker)
            if not krx_item:
                skipped_no_krx_data += 1
                continue

            name = krx_item.name
            name_lower = name.lower() if name else ''

            # 1. 키워드 필터링
            if any(kw.lower() in name_lower for kw in EXCLUDE_KEYWORDS):
                skipped_by_keyword += 1
                continue

            # 2. AUM 필터링
            if krx_item.net_assets < MIN_AUM_WON:
                skipped_by_aum += 1
                continue

            filtered.append(ticker)

        except Exception as e:
            log.warning(f"Failed to check ETF {ticker}: {e}")
            continue

    log.info(f"Filtered: {len(filtered)} ETFs (excluded by keyword: {skipped_by_keyword}, by AUM: {skipped_by_aum}, no KRX data: {skipped_no_krx_data})")
    return filtered


def collect_etf_metadata(**context):
    """Task 2: ETF 메타데이터 수집 및 AGE에 저장 (필터링된 ETF만)"""
    from pykrx import stock
    import time

    ti = context['ti']
    tickers = ti.xcom_pull(task_ids='filter_etf_list')

    if not tickers:
        log.warning("No tickers to process")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        for ticker in tickers:
            try:
                name = stock.get_etf_ticker_name(ticker)

                # Create or update ETF node in Apache AGE (MERGE와 SET을 분리 - AGE 버그 우회)
                cypher_merge = """
                    MERGE (e:ETF {code: $code})
                    RETURN e
                """
                execute_cypher(cur, cypher_merge, {
                    'code': ticker
                })

                cypher_set = """
                    MATCH (e:ETF {code: $code})
                    SET e.name = $name, e.updated_at = $updated_at
                    RETURN e
                """
                execute_cypher(cur, cypher_set, {
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
    """Task 3: ETF 구성종목 수집 및 AGE에 저장 (필터링된 ETF만)"""
    from pykrx import stock
    import pandas as pd
    import time

    ti = context['ti']
    tickers = ti.xcom_pull(task_ids='filter_etf_list')
    trading_date = ti.xcom_pull(task_ids='fetch_krx_data', key='trading_date')
    # trading_date는 YYYYMMDD 형식, date_str은 YYYY-MM-DD 형식으로 변환
    date_str = f"{trading_date[:4]}-{trading_date[4:6]}-{trading_date[6:8]}" if trading_date else context['ds']

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

                # 비중순으로 정렬하여 상위 20개만 수집
                if '비중' in df.columns:
                    df = df.sort_values('비중', ascending=False).head(20)
                else:
                    df = df.head(20)

                for idx, row in df.iterrows():
                    # 인덱스가 종목 코드 (티커)
                    stock_code = str(idx)

                    # 종목명은 별도 API 호출로 조회
                    try:
                        result = stock.get_market_ticker_name(stock_code)
                        # DataFrame이 반환된 경우 None 처리
                        if isinstance(result, pd.DataFrame):
                            stock_name = None
                        else:
                            stock_name = result
                    except Exception:
                        stock_name = None

                    # stock_name이 None이거나 빈 값이면 stock_code로 대체
                    if stock_name is None or (isinstance(stock_name, str) and len(stock_name) == 0):
                        stock_name = stock_code
                    else:
                        stock_name = str(stock_name)

                    weight = float(row.get('비중', 0))
                    # '계약수' 또는 '주수' 컬럼 사용
                    shares_val = row.get('계약수', row.get('주수', 0))
                    shares = int(shares_val) if shares_val and not pd.isna(shares_val) else 0

                    if not stock_code:
                        continue

                    # Create Stock node (MERGE와 SET을 분리 - AGE 버그 우회)
                    cypher_stock_merge = """
                        MERGE (s:Stock {code: $code})
                        RETURN s
                    """
                    execute_cypher(cur, cypher_stock_merge, {
                        'code': stock_code
                    })

                    cypher_stock_set = """
                        MATCH (s:Stock {code: $code})
                        SET s.name = $name
                        RETURN s
                    """
                    execute_cypher(cur, cypher_stock_set, {
                        'code': stock_code,
                        'name': stock_name
                    })

                    # Create HOLDS edge (MERGE와 SET을 분리 - AGE 버그 우회)
                    cypher_holds_merge = """
                        MATCH (e:ETF {code: $etf_code})
                        MATCH (s:Stock {code: $stock_code})
                        MERGE (e)-[h:HOLDS {date: $date}]->(s)
                        RETURN h
                    """
                    execute_cypher(cur, cypher_holds_merge, {
                        'etf_code': ticker,
                        'stock_code': stock_code,
                        'date': date_str
                    })

                    cypher_holds_set = """
                        MATCH (e:ETF {code: $etf_code})-[h:HOLDS {date: $date}]->(s:Stock {code: $stock_code})
                        SET h.weight = $weight, h.shares = $shares
                        RETURN h
                    """
                    execute_cypher(cur, cypher_holds_set, {
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
    """Task 4: ETF 가격 데이터 수집 (KRX API 데이터 사용, 모든 ETF)"""
    ti = context['ti']
    krx_data_dicts = ti.xcom_pull(task_ids='fetch_krx_data')
    trading_date = ti.xcom_pull(task_ids='fetch_krx_data', key='trading_date')
    date_str = f"{trading_date[:4]}-{trading_date[4:6]}-{trading_date[6:8]}" if trading_date else context['ds']

    if not krx_data_dicts:
        log.warning("No KRX data available")
        return

    conn = get_db_connection()
    cur = conn.cursor()

    success_count = 0

    try:
        # 모든 KRX 데이터에 대해 가격 저장
        for krx_item in krx_data_dicts:
            try:

                cur.execute("""
                    INSERT INTO etf_prices (
                        etf_code, date, open_price, high_price, low_price, close_price,
                        volume, nav, market_cap, net_assets, trade_value
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (etf_code, date) DO UPDATE SET
                        open_price = EXCLUDED.open_price,
                        high_price = EXCLUDED.high_price,
                        low_price = EXCLUDED.low_price,
                        close_price = EXCLUDED.close_price,
                        volume = EXCLUDED.volume,
                        nav = EXCLUDED.nav,
                        market_cap = EXCLUDED.market_cap,
                        net_assets = EXCLUDED.net_assets,
                        trade_value = EXCLUDED.trade_value
                """, (
                    krx_item['code'],
                    date_str,
                    krx_item['open_price'],
                    krx_item['high_price'],
                    krx_item['low_price'],
                    krx_item['close_price'],
                    krx_item['volume'],
                    krx_item['nav'],
                    krx_item['market_cap'],
                    krx_item['net_assets'],
                    krx_item['trade_value']
                ))

                success_count += 1

            except Exception as e:
                log.warning(f"Failed to save prices for {krx_item.get('code', 'unknown')}: {e}")
                continue

        conn.commit()
        log.info(f"Price collection complete. Success: {success_count}")

    finally:
        cur.close()
        conn.close()


def detect_portfolio_changes(**context):
    """Task 5: 포트폴리오 변화 감지 및 AGE에 저장 (필터링된 ETF만)"""

    ti = context['ti']
    tickers = ti.xcom_pull(task_ids='filter_etf_list')
    trading_date = ti.xcom_pull(task_ids='fetch_krx_data', key='trading_date')
    today = f"{trading_date[:4]}-{trading_date[4:6]}-{trading_date[6:8]}" if trading_date else context['ds']
    # 이전 거래일 계산 (간단히 1일 전으로, 추후 개선 필요)
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

task_fetch_krx_data = PythonOperator(
    task_id='fetch_krx_data',
    python_callable=fetch_krx_data,
    dag=dag,
)

task_filter_etf_list = PythonOperator(
    task_id='filter_etf_list',
    python_callable=filter_etf_list,
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
# 1. ETF 목록(pykrx) + KRX 데이터를 병렬로 수집
# 2. 두 데이터를 기반으로 필터링
# 3. 필터링된 ETF만 메타데이터 + 구성종목 수집
# 4. 가격: 모든 ETF 수집 (KRX 데이터 기반)
start >> [task_collect_etf_list, task_fetch_krx_data]
[task_collect_etf_list, task_fetch_krx_data] >> task_filter_etf_list
task_filter_etf_list >> [task_collect_metadata, task_collect_holdings]
task_fetch_krx_data >> task_collect_prices  # 가격은 모든 ETF 대상
task_collect_holdings >> task_detect_changes >> end
[task_collect_prices, task_collect_metadata] >> end
