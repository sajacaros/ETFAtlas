"""
age_utils — Apache AGE + KRX 공용 유틸리티

sync_universe_age / rebuild_graph_age DAG에서 공통으로 사용하는 함수들.
"""

import logging
import os

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# ETF 운용사 매핑
# ──────────────────────────────────────────────

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


# ──────────────────────────────────────────────
# 룰 기반 태그 상수
# ──────────────────────────────────────────────

RULE_ONLY_TAGS = ['코스피200', '코스닥150']

# 이름이 200/200TR/150으로 끝나는 ETF만 매칭 (TIGER 200 중공업 등 섹터 ETF 제외)
INDEX_TAG_PATTERNS = [
    (r'(?<!\d)200(?:TR)?\s*$', '코스피200'),
    (r'(?<!\d)150\s*$', '코스닥150'),
]


# ──────────────────────────────────────────────
# DB / AGE 연결
# ──────────────────────────────────────────────

def get_db_connection():
    """Get database connection"""
    import psycopg2

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
        for key, value in params.items():
            if value is None:
                cypher_query = cypher_query.replace(f'${key}', 'null')
            elif isinstance(value, bool):
                cypher_query = cypher_query.replace(f'${key}', 'true' if value else 'false')
            elif isinstance(value, (int, float)):
                cypher_query = cypher_query.replace(f'${key}', str(value))
            else:
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


# ──────────────────────────────────────────────
# 배치 헬퍼
# ──────────────────────────────────────────────

def _escape_cypher_value(value):
    """Cypher 리터럴로 변환"""
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        import math
        if math.isnan(value) or math.isinf(value):
            return 'null'
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
    return f"'{escaped}'"


def build_cypher_list(items: list[dict]) -> str:
    """[{code: 'A'}, {code: 'B'}] 형태의 Cypher 리스트 리터럴 생성"""
    parts = []
    for item in items:
        props = ", ".join(
            f"{k}: {_escape_cypher_value(v)}" for k, v in item.items()
        )
        parts.append("{" + props + "}")
    return "[" + ", ".join(parts) + "]"


def execute_cypher_batch(cur, cypher_template: str, items: list[dict],
                         batch_size: int = 100):
    """UNWIND + cypher_template로 배치 실행.

    template에서 'item' 변수를 사용.
    예: MERGE (e:ETF {code: item.code}) RETURN e
    """
    if not items:
        return []

    all_results = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        cypher_list = build_cypher_list(batch)
        query = f"UNWIND {cypher_list} AS item\n{cypher_template}"
        results = execute_cypher(cur, query)
        all_results.extend(results)
    return all_results


# ──────────────────────────────────────────────
# KRX 데이터 조회
# ──────────────────────────────────────────────

def get_krx_daily_data(date: str) -> tuple[list, str]:
    """KRX Open API에서 ETF 일별매매정보 조회 (최근 거래일 자동 탐색)

    Args:
        date: 기준일자 (YYYYMMDD 형식)

    Returns:
        tuple: (ETFDailyData 리스트, 실제 조회된 날짜), 실패 시 (빈 리스트, 빈 문자열)
    """
    from datetime import datetime, timedelta
    from krx_api_client import KRXApiClient

    auth_key = os.environ.get('KRX_AUTH_KEY', '')
    if not auth_key:
        log.warning("KRX_AUTH_KEY not set, cannot fetch KRX data")
        return [], ''

    try:
        client = KRXApiClient(auth_key)

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


def _get_krx_data_for_exact_date(date: str) -> list:
    """KRX API에서 정확히 해당 날짜의 데이터만 조회 (거래일 탐색 없음)"""
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


# ──────────────────────────────────────────────
# 유니버스 필터링
# ──────────────────────────────────────────────

def get_valid_ticker_set(date: str) -> set:
    """KOSPI + KOSDAQ + ETF 상장종목 코드 집합 반환 (채권/파생/현금 등 제외용)"""
    from pykrx import stock

    kospi = set(stock.get_market_ticker_list(date, market='KOSPI'))
    kosdaq = set(stock.get_market_ticker_list(date, market='KOSDAQ'))
    etfs = set(stock.get_etf_ticker_list(date))
    valid = kospi | kosdaq | etfs
    log.info(f"Valid tickers: KOSPI={len(kospi)}, KOSDAQ={len(kosdaq)}, "
             f"ETF={len(etfs)}, total={len(valid)}")
    return valid


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
        '글로벌', 'Global', 'China', 'Japan', 'India', ' US', 'USA',
        'S&P', 'NASDAQ', '나스닥', '다우존스',
        'MSCI', '선진국', '신흥국', '아시아',
        '테슬라', 'Tesla', '엔비디아', 'NVIDIA', '구글', 'Google',
        '애플', 'Apple', '아마존', 'Amazon', '팔란티어', 'Palantir',
        '브로드컴', 'Broadcom', '알리바바', 'Alibaba', '버크셔', 'Berkshire',
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

        if net_assets < MIN_AUM:
            continue
        if any(kw.lower() in name_lower for kw in EXCLUDE_KEYWORDS):
            continue
        if any(kw.lower() in name_lower or kw in name for kw in FOREIGN_NAME_KEYWORDS):
            continue

        candidates.append({
            'code': code,
            'name': name,
            'index_name': '',
            'net_assets': net_assets
        })

    return candidates
