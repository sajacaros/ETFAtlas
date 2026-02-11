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

# ETF 이름 prefix → 운용사 매핑
ETF_COMPANY_MAP = {
    # 삼성
    'KODEX': '삼성자산운용',
    'KoAct': '삼성액티브자산운용',
    # 미래에셋
    'TIGER': '미래에셋자산운용',
    # KB
    'RISE': 'KB자산운용',
    # 한국투자
    'ACE': '한국투자신탁운용',
    # NH아문디
    'HANARO': 'NH아문디자산운용',
    # 신한
    'SOL': '신한자산운용',
    # 한화
    'PLUS': '한화자산운용',
    # 키움
    'KIWOOM': '키움자산운용',
    # 하나
    '1Q': '하나자산운용',
    # 타임폴리오
    'TIMEFOLIO': '타임폴리오자산운용',
    'TIME': '타임폴리오자산운용',
    # 우리
    'WON': '우리자산운용',
    # 기타
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
    """Task 1-1: KRX API에서 일별매매정보 조회 (누락 영업일 자동 백필)

    DB의 마지막 수집일 ~ 오늘 사이 누락된 영업일을 모두 수집.
    XCom:
      - trading_date: 최신 거래일 1개 (기존 downstream 호환)
      - trading_dates: 수집된 모든 거래일 리스트
      - return: 모든 날짜의 krx_data 통합 리스트
    """
    from datetime import datetime, timedelta

    date = context['ds_nodash']
    ti = context['ti']

    # 1. DB에서 마지막 수집일 조회
    last_collected = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT MAX(date) FROM etf_prices
            WHERE close_price > 0
        """)
        result = cur.fetchone()
        if result and result[0]:
            last_collected = result[0]  # datetime.date 객체
            log.info(f"Last collected date in DB: {last_collected}")
        cur.close()
        conn.close()
    except Exception as e:
        log.warning(f"Failed to query last collected date: {e}")

    # 2. 백필 시작일 결정
    INITIAL_BACKFILL_DAYS = 45  # 초기 적재 시 약 30 영업일 (6주 = 45일)
    base_date = datetime.strptime(date, '%Y%m%d').date()

    if not last_collected:
        # DB가 비어있으면 오늘 기준 INITIAL_BACKFILL_DAYS일 전부터 수집
        start_date = base_date - timedelta(days=INITIAL_BACKFILL_DAYS)
        log.info(f"No previous data in DB, initial backfill from {start_date} to {base_date}")
    else:
        start_date = last_collected + timedelta(days=1)

    if start_date > base_date:
        log.info("No missing dates to backfill")
        # 그래도 오늘 데이터는 수집 (이미 수집된 경우 ON CONFLICT로 처리)
        krx_data, actual_date = get_krx_daily_data(date)
        ti.xcom_push(key='trading_date', value=actual_date)
        ti.xcom_push(key='trading_dates', value=[actual_date] if actual_date else [])
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

    # 평일 날짜 리스트 생성 (월~금 = weekday 0~4)
    candidate_dates = []
    current = start_date
    while current <= base_date:
        if current.weekday() < 5:  # 월~금
            candidate_dates.append(current.strftime('%Y%m%d'))
        current += timedelta(days=1)

    log.info(f"Backfill candidates: {len(candidate_dates)} weekdays from {start_date} to {base_date}")

    # 4. 각 날짜별 KRX 데이터 수집
    all_krx_data = []
    collected_dates = []

    for candidate_date in candidate_dates:
        try:
            result = _get_krx_data_for_exact_date(candidate_date)
            if result:
                all_krx_data.extend(result)
                collected_dates.append(candidate_date)
                log.info(f"Collected {len(result)} ETFs for {candidate_date}")
            else:
                log.info(f"No data for {candidate_date} (likely holiday), skipping")
        except Exception as e:
            log.warning(f"Failed to fetch data for {candidate_date}: {e}")

    log.info(f"Backfill complete: collected {len(collected_dates)} trading days, {len(all_krx_data)} total records")

    # 5. 백필 결과가 없으면 최근 거래일 fallback (장 마감 전/공휴일 대비)
    if not collected_dates:
        log.info("No new data from backfill, falling back to latest trading day search")
        krx_data, actual_date = get_krx_daily_data(date)
        if krx_data:
            all_krx_data = krx_data
            collected_dates = [actual_date]
            log.info(f"Fallback: found {len(krx_data)} ETFs for {actual_date}")

    # 6. XCom push
    latest_date = collected_dates[-1] if collected_dates else ''
    ti.xcom_push(key='trading_date', value=latest_date)
    ti.xcom_push(key='trading_dates', value=collected_dates)

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
        for item in all_krx_data
    ]


def _get_krx_data_for_exact_date(date: str) -> list:
    """KRX API에서 정확히 해당 날짜의 데이터만 조회 (거래일 탐색 없음)

    Args:
        date: 조회일자 (YYYYMMDD 형식)

    Returns:
        ETFDailyData 리스트, 데이터 없으면 빈 리스트
    """
    import os
    from krx_api_client import KRXApiClient

    auth_key = os.environ.get('KRX_AUTH_KEY', '')
    if not auth_key:
        return []

    try:
        client = KRXApiClient(auth_key)
        result = client.get_etf_daily_trading(date)
        return result if result else []
    except Exception as e:
        log.warning(f"Failed to get KRX data for {date}: {e}")
        return []


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

                # Company 노드 생성 및 MANAGED_BY 관계 연결
                company = get_company_from_etf_name(name)
                cypher_company_merge = """
                    MERGE (c:Company {name: $company})
                    RETURN c
                """
                execute_cypher(cur, cypher_company_merge, {
                    'company': company
                })

                cypher_managed_by = """
                    MATCH (e:ETF {code: $code})
                    MATCH (c:Company {name: $company})
                    MERGE (e)-[:MANAGED_BY]->(c)
                    RETURN 1
                """
                execute_cypher(cur, cypher_managed_by, {
                    'code': ticker,
                    'company': company
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

    # ETF 티커 목록 조회 (보유종목이 ETF인지 확인용)
    etf_tickers = set(stock.get_etf_ticker_list(trading_date if trading_date else context['ds_nodash']))

    # 종목 -> (시장, 섹터) 매핑 생성
    stock_sector_map = {}
    query_date = trading_date if trading_date else context['ds_nodash']

    for market in ['KOSPI', 'KOSDAQ']:
        try:
            # 해당 시장의 업종 인덱스 목록 조회
            sector_codes = stock.get_index_ticker_list(query_date, market)
            for sector_code in sector_codes:
                try:
                    sector_name = stock.get_index_ticker_name(sector_code)
                    sector_tickers = stock.get_index_portfolio_deposit_file(sector_code, query_date)
                    if sector_tickers is not None:
                        for ticker in sector_tickers:
                            stock_sector_map[ticker] = (market, sector_name)
                except Exception:
                    continue
        except Exception as e:
            log.warning(f"Failed to get sector info for {market}: {e}")

    log.info(f"Built sector map for {len(stock_sector_map)} stocks")

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

                    # 보유종목이 ETF인지 확인
                    is_etf = stock_code in etf_tickers

                    # 종목명 조회 (ETF면 ETF명, 아니면 주식명)
                    try:
                        if is_etf:
                            result = stock.get_etf_ticker_name(stock_code)
                        else:
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
                        SET s.name = $name, s.is_etf = $is_etf
                        RETURN s
                    """
                    execute_cypher(cur, cypher_stock_set, {
                        'code': stock_code,
                        'name': stock_name,
                        'is_etf': is_etf
                    })

                    # Stock -> Sector -> Market 관계 생성 (ETF가 아닌 경우만)
                    if not is_etf and stock_code in stock_sector_map:
                        market, sector = stock_sector_map[stock_code]

                        # Market 노드 생성
                        cypher_market = """
                            MERGE (m:Market {name: $market})
                            RETURN m
                        """
                        execute_cypher(cur, cypher_market, {'market': market})

                        # Sector 노드 생성
                        cypher_sector = """
                            MERGE (sec:Sector {name: $sector})
                            RETURN sec
                        """
                        execute_cypher(cur, cypher_sector, {'sector': sector})

                        # Sector -> Market 관계 (PART_OF)
                        cypher_sector_market = """
                            MATCH (sec:Sector {name: $sector})
                            MATCH (m:Market {name: $market})
                            MERGE (sec)-[:PART_OF]->(m)
                            RETURN 1
                        """
                        execute_cypher(cur, cypher_sector_market, {
                            'sector': sector,
                            'market': market
                        })

                        # Stock -> Sector 관계 (BELONGS_TO)
                        cypher_stock_sector = """
                            MATCH (s:Stock {code: $code})
                            MATCH (sec:Sector {name: $sector})
                            MERGE (s)-[:BELONGS_TO]->(sec)
                            RETURN 1
                        """
                        execute_cypher(cur, cypher_stock_sector, {
                            'code': stock_code,
                            'sector': sector
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
    """Task 4: ETF 가격 데이터 수집 (KRX API 데이터 사용, 모든 ETF)

    각 krx_data item의 date 필드를 그대로 사용하여 멀티 날짜 INSERT 지원.
    """
    ti = context['ti']
    krx_data_dicts = ti.xcom_pull(task_ids='fetch_krx_data')

    if not krx_data_dicts:
        log.warning("No KRX data available")
        return

    conn = get_db_connection()
    cur = conn.cursor()

    success_count = 0

    try:
        for krx_item in krx_data_dicts:
            try:
                # 각 item의 date 필드 사용 (YYYYMMDD → YYYY-MM-DD)
                item_date = krx_item['date']
                date_str = f"{item_date[:4]}-{item_date[4:6]}-{item_date[6:8]}"

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


def collect_stock_prices(**context):
    """Task 6: Stock 가격 데이터 수집 (is_etf=false인 Stock만)

    XCom의 trading_dates 리스트를 사용하여 멀티 날짜 수집 지원.
    """
    from pykrx import stock

    ti = context['ti']
    trading_dates = ti.xcom_pull(task_ids='fetch_krx_data', key='trading_dates')
    if not trading_dates:
        # fallback: 단일 날짜
        trading_date = ti.xcom_pull(task_ids='fetch_krx_data', key='trading_date')
        trading_dates = [trading_date] if trading_date else [context['ds_nodash']]

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # 1. 그래프에서 is_etf=false인 Stock 코드 목록 조회
        cypher_stocks = """
            MATCH (s:Stock)
            WHERE s.is_etf = false
            RETURN s.code
        """
        results = execute_cypher(cur, cypher_stocks, {})
        stock_codes = set()
        for row in results:
            if row[0]:
                import json
                data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                if data:
                    stock_codes.add(str(data).strip('"'))

        if not stock_codes:
            log.warning("No stocks to collect prices for")
            return

        log.info(f"Collecting prices for {len(stock_codes)} stocks across {len(trading_dates)} dates")

        # 2. 각 날짜별로 pykrx OHLCV 조회 및 저장
        cur_db = conn.cursor()
        total_success = 0

        for td in trading_dates:
            try:
                date_str = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
                df = stock.get_market_ohlcv_by_ticker(td)

                if df is None or df.empty:
                    log.warning(f"No market OHLCV data for {td}")
                    continue

                date_success = 0
                for code in stock_codes:
                    if code in df.index:
                        try:
                            row = df.loc[code]
                            cur_db.execute("""
                                INSERT INTO stock_prices (
                                    stock_code, date, open_price, high_price, low_price, close_price,
                                    volume, change_rate
                                )
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (stock_code, date) DO UPDATE SET
                                    open_price = EXCLUDED.open_price,
                                    high_price = EXCLUDED.high_price,
                                    low_price = EXCLUDED.low_price,
                                    close_price = EXCLUDED.close_price,
                                    volume = EXCLUDED.volume,
                                    change_rate = EXCLUDED.change_rate
                            """, (
                                code,
                                date_str,
                                float(row.get('시가', 0)),
                                float(row.get('고가', 0)),
                                float(row.get('저가', 0)),
                                float(row.get('종가', 0)),
                                int(row.get('거래량', 0)),
                                float(row.get('등락률', 0))
                            ))
                            date_success += 1
                        except Exception as e:
                            log.warning(f"Failed to save stock price for {code} on {td}: {e}")
                            continue

                conn.commit()
                total_success += date_success
                log.info(f"Stock prices for {td}: {date_success} saved")

            except Exception as e:
                log.warning(f"Failed to collect stock prices for date {td}: {e}")
                continue

        cur_db.close()
        log.info(f"Stock price collection complete. Total success: {total_success}")

    finally:
        cur.close()
        conn.close()


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


def tag_new_etfs(**context):
    """Tag 미분류 ETF에 LLM 기반 태그 자동 부여

    1. AGE에서 TAGGED 관계가 없는 ETF 목록 조회
    2. 각 ETF의 보유종목 TOP 10 조회
    3. GPT-4.1-mini로 태그 분류 (10개씩 배치)
    4. Tag 노드 + TAGGED 관계 저장
    """
    import os
    import json as json_module
    import re

    def parse_agtype(value):
        """AGE agtype 값에서 ::vertex, ::edge 등 타입 접미사를 제거 후 JSON 파싱"""
        if not value:
            return None
        s = str(value)
        # ::vertex, ::edge, ::path 등 접미사 제거
        s = re.sub(r'::(?:vertex|edge|path|text|integer|float|boolean)\s*$', '', s)
        try:
            return json_module.loads(s)
        except (json_module.JSONDecodeError, ValueError):
            return s.strip('"')

    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        log.warning("OPENAI_API_KEY not set, skipping ETF tagging")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # 1. 전체 ETF 목록 조회 (노드 전체 반환 — execute_cypher는 단일 컬럼만 지원)
        all_etfs_result = execute_cypher(cur, """
            MATCH (e:ETF)
            RETURN e
        """)
        all_etfs = {}
        for row in all_etfs_result:
            if row[0]:
                data = parse_agtype(row[0])
                if isinstance(data, dict):
                    props = data.get('properties', data)
                    code = props.get('code', '')
                    name = props.get('name', '')
                    if code:
                        all_etfs[code] = name

        if not all_etfs:
            log.info("No ETFs found in graph")
            return

        # 2. 이미 태그된 ETF 제외
        tagged_result = execute_cypher(cur, """
            MATCH (e:ETF)-[:TAGGED]->(t:Tag)
            RETURN e.code
        """)
        tagged_codes = set()
        for row in tagged_result:
            if row[0]:
                data = parse_agtype(row[0])
                if data:
                    tagged_codes.add(str(data).strip('"'))

        untagged = {code: name for code, name in all_etfs.items() if code not in tagged_codes}
        if not untagged:
            log.info("All ETFs are already tagged")
            return

        log.info(f"Found {len(untagged)} untagged ETFs (total: {len(all_etfs)}, tagged: {len(tagged_codes)})")

        # 3. 각 ETF의 보유종목 TOP 10 조회 (종목명만 — 태그 분류에 충분)
        etf_holdings = {}
        for code in untagged:
            holdings_result = execute_cypher(cur, """
                MATCH (e:ETF {code: $code})-[h:HOLDS]->(s:Stock)
                RETURN s.name
                ORDER BY h.weight DESC
                LIMIT 10
            """, {'code': code})

            holdings = []
            for row in holdings_result:
                if row[0]:
                    stock_name = parse_agtype(row[0])
                    if stock_name and isinstance(stock_name, str):
                        holdings.append(stock_name)

            etf_holdings[code] = holdings

        # 4. LLM 배치 호출
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate
        from pydantic import BaseModel

        class ETFTagResult(BaseModel):
            code: str
            tags: list[str]

        class ETFTagBatchResult(BaseModel):
            results: list[ETFTagResult]

        llm = ChatOpenAI(
            model="gpt-4.1-mini",
            temperature=0,
            api_key=api_key,
        )
        structured_llm = llm.with_structured_output(ETFTagBatchResult)

        system_prompt = """한국 주식시장 ETF 분류 전문가입니다.
ETF 이름과 주요 보유종목을 보고, 적절한 태그를 1~3개 부여하세요.

태그 예시:
- 산업: 반도체, 2차전지, 바이오, 자동차, 금융, 건설, 화학, 에너지, 철강, 조선, 통신, 유통, 엔터
- 테마: AI, 로봇, 친환경, 우주항공, 방산, 원전, K뷰티
- 스타일: 대형주, 중소형주, 배당, 가치, 성장, 고배당
- 지수: 시장지수

규칙:
- 코스피200, 코스닥150 같은 시장 대표 지수 ETF는 "시장지수" 태그
- 가능한 구체적인 산업/테마 태그를 우선 사용
- 새로운 태그 생성 가능하되, 기존 태그와 중복되지 않도록 주의"""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "다음 ETF들을 분류해주세요:\n\n{etf_list}"),
        ])

        chain = prompt | structured_llm

        # 10개씩 배치 처리
        untagged_list = list(untagged.items())
        batch_size = 10
        total_tagged = 0

        for i in range(0, len(untagged_list), batch_size):
            batch = untagged_list[i:i + batch_size]

            # ETF 정보 텍스트 생성
            etf_texts = []
            for code, name in batch:
                holdings = etf_holdings.get(code, [])
                holdings_str = ", ".join(holdings[:10]) if holdings else "보유종목 정보 없음"
                etf_texts.append(f"- [{code}] {name}: {holdings_str}")

            etf_list_text = "\n".join(etf_texts)

            try:
                result = chain.invoke({"etf_list": etf_list_text})

                # 5. Tag 노드 + TAGGED 관계 저장
                for etf_tag in result.results:
                    for tag_name in etf_tag.tags:
                        # Tag 노드 MERGE
                        execute_cypher(cur, """
                            MERGE (t:Tag {name: $tag_name})
                            RETURN t
                        """, {'tag_name': tag_name})

                        # TAGGED 관계 MERGE
                        execute_cypher(cur, """
                            MATCH (e:ETF {code: $code})
                            MATCH (t:Tag {name: $tag_name})
                            MERGE (e)-[:TAGGED]->(t)
                            RETURN 1
                        """, {'code': etf_tag.code, 'tag_name': tag_name})

                    total_tagged += 1

                conn.commit()
                log.info(f"Tagged batch {i // batch_size + 1}: {len(batch)} ETFs")

            except Exception as e:
                log.warning(f"Failed to tag batch {i // batch_size + 1}: {e}")
                conn.rollback()
                continue

        log.info(f"ETF tagging complete. Tagged: {total_tagged}/{len(untagged)}")

    finally:
        cur.close()
        conn.close()


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

task_collect_stock_prices = PythonOperator(
    task_id='collect_stock_prices',
    python_callable=collect_stock_prices,
    dag=dag,
)

task_sync_etfs_to_rdb = PythonOperator(
    task_id='sync_etfs_to_rdb',
    python_callable=sync_etfs_to_rdb,
    dag=dag,
)

task_tag_new_etfs = PythonOperator(
    task_id='tag_new_etfs',
    python_callable=tag_new_etfs,
    dag=dag,
)

# Define dependencies
# 1. ETF 목록(pykrx) + KRX 데이터를 병렬로 수집
# 2. 두 데이터를 기반으로 필터링
# 3. 필터링된 ETF만 메타데이터 + 구성종목 수집
# 4. 가격: 모든 ETF 수집 (KRX 데이터 기반)
# 5. RDB sync: 모든 ETF 메타를 etfs 테이블에 동기화 (KRX 데이터 기반)
# 6. Stock 가격: 구성종목 수집 후 is_etf=false인 Stock만 수집
# 7. ETF 태깅: 메타데이터 + 구성종목 수집 완료 후 LLM 기반 태그 분류
# NOTE: 포트폴리오 스냅샷은 portfolio_snapshot DAG로 분리됨
start >> [task_collect_etf_list, task_fetch_krx_data]
[task_collect_etf_list, task_fetch_krx_data] >> task_filter_etf_list
task_filter_etf_list >> [task_collect_metadata, task_collect_holdings]
task_fetch_krx_data >> [task_collect_prices, task_sync_etfs_to_rdb]  # 가격 + RDB sync는 모든 ETF 대상
task_collect_holdings >> [task_collect_stock_prices, task_detect_changes]
[task_collect_metadata, task_collect_holdings] >> task_tag_new_etfs  # 메타+구성종목 완료 후 태깅
[task_sync_etfs_to_rdb, task_collect_stock_prices, task_detect_changes, task_collect_prices, task_tag_new_etfs] >> end
