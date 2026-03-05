"""
age_utils — Apache AGE + KRX 공용 유틸리티

age_backfill / age_sync_universe / age_tagging DAG에서 공통으로 사용하는 함수들.
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

RULE_ONLY_TAGS = ['코스피', '코스닥']

# 코스피 계열: 200, 200TR, 200액티브, 코스피, 코스피TR, 코스피액티브, 코스피100
# 코스닥 계열: 150
INDEX_TAG_PATTERNS = [
    (r'(?<!\d)200(?:TR)?\s*$', '코스피'),
    (r'(?<!\d)200액티브', '코스피'),
    (r'코스피(?:TR|액티브|100|50)?\s*$', '코스피'),
    (r'(?<!\d)150\s*$', '코스닥'),
]


# ──────────────────────────────────────────────
# DB / AGE 연결
# ──────────────────────────────────────────────

def get_db_connection():
    """Get database connection"""
    import psycopg2
    from urllib.parse import urlparse

    db_url = os.environ.get(
        'DATABASE_URL',
        'postgresql://postgres:postgres@db:5432/etf_atlas'
    )

    parsed = urlparse(db_url)
    conn = psycopg2.connect(
        host=parsed.hostname or 'db',
        port=parsed.port or 5432,
        database=parsed.path.lstrip('/') or 'etf_atlas',
        user=parsed.username or 'postgres',
        password=parsed.password or 'postgres',
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
        import re
        # 긴 키부터 치환하여 $code가 $code_name을 침범하는 것을 방지
        for key in sorted(params.keys(), key=len, reverse=True):
            value = params[key]
            if value is None:
                replacement = 'null'
            elif isinstance(value, bool):
                replacement = 'true' if value else 'false'
            elif isinstance(value, (int, float)):
                replacement = str(value)
            else:
                escaped = str(value).replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
                replacement = f"'{escaped}'"
            # 단어 경계를 사용하여 정확한 파라미터만 치환
            cypher_query = re.sub(rf'\${re.escape(key)}\b', replacement, cypher_query)

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
    """KOSPI + KOSDAQ + ETF 상장종목 코드 집합 반환 (채권/파생/현금 등 제외용)

    AGE 그래프의 ETF+Stock 코드를 primary로 사용하고,
    pykrx KRX 스크래핑은 fallback으로만 시도한다.
    """
    # Primary: AGE 그래프에서 조회
    etf_codes = get_etf_codes_from_age()
    stock_codes = get_stock_codes_from_age()
    valid = etf_codes | stock_codes

    if valid:
        log.info(f"Valid tickers from AGE: ETF={len(etf_codes)}, "
                 f"Stock={len(stock_codes)}, total={len(valid)}")
        return valid

    # Fallback: pykrx KRX 스크래핑 (AGE가 비어있을 때만)
    log.warning("AGE returned no tickers, falling back to pykrx KRX scraping")
    from pykrx import stock
    try:
        kospi = set(stock.get_market_ticker_list(date, market='KOSPI'))
        kosdaq = set(stock.get_market_ticker_list(date, market='KOSDAQ'))
        etfs = set(stock.get_etf_ticker_list(date))
        valid = kospi | kosdaq | etfs
        log.info(f"Valid tickers (pykrx fallback): KOSPI={len(kospi)}, "
                 f"KOSDAQ={len(kosdaq)}, ETF={len(etfs)}, total={len(valid)}")
    except Exception as e:
        log.warning(f"pykrx fallback also failed: {e}")
        valid = set()
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


# ──────────────────────────────────────────────
# AGE 공용 조회
# ──────────────────────────────────────────────

def _parse_age_value(raw):
    """AGE agtype 문자열에서 타입 접미사 제거"""
    import re
    raw = str(raw)
    raw = re.sub(r'::(?:numeric|integer|float|vertex|edge|path|text|boolean)\b', '', raw)
    return raw.strip('"')


def get_business_days(from_date: str, to_date: str) -> list[str]:
    """pykrx로 영업일 목록 조회. YYYYMMDD 리스트 반환.

    pykrx 내부 KRX 스크래핑 API가 불안정하므로,
    공개 API(get_market_ohlcv_by_date)로 영업일을 추출한다.
    """
    from pykrx import stock
    try:
        df = stock.get_market_ohlcv_by_date(from_date, to_date, '005930')
        return [d.strftime('%Y%m%d') for d in df.index]
    except Exception as e:
        log.warning(f"Failed to get business days via OHLCV: {e}")
        return []


def get_last_collected_date() -> str | None:
    """AGE에서 마지막 수집된 Price 날짜 조회. YYYYMMDD 또는 None."""
    conn = get_db_connection()
    cur = init_age(conn)
    try:
        results = execute_cypher(cur, """
            MATCH (e:ETF)-[:HAS_PRICE]->(p:Price)
            RETURN p.date
            ORDER BY p.date DESC
            LIMIT 1
        """)
        if results and results[0][0]:
            raw = _parse_age_value(results[0][0])
            if raw and raw != 'null':
                return raw.replace('-', '')
        return None
    except Exception as e:
        log.warning(f"Failed to query last collected date: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def get_previous_holds_date(before_date: str) -> str | None:
    """AGE에서 before_date 이전의 가장 최근 HOLDS 날짜 조회.

    Args:
        before_date: 기준일 (YYYY-MM-DD 형식)

    Returns:
        YYYYMMDD 문자열 또는 None
    """
    conn = get_db_connection()
    cur = init_age(conn)
    try:
        results = execute_cypher(cur, """
            MATCH ()-[h:HOLDS]->()
            WHERE h.date < $before_date
            WITH DISTINCT h.date AS d
            RETURN d
            ORDER BY d DESC
            LIMIT 1
        """, {'before_date': before_date})
        if results and results[0][0]:
            raw = _parse_age_value(results[0][0])
            if raw and raw != 'null':
                return raw.replace('-', '')
        return None
    except Exception as e:
        log.warning(f"Failed to query previous holds date: {e}")
        return None
    finally:
        cur.close()
        conn.close()


def get_etf_codes_from_age() -> set[str]:
    """AGE에서 ETF 유니버스 코드 조회."""
    conn = get_db_connection()
    cur = init_age(conn)
    try:
        results = execute_cypher(cur, "MATCH (e:ETF) RETURN e.code")
        codes = set()
        for row in results:
            if row[0]:
                code = _parse_age_value(row[0])
                if code:
                    codes.add(code)
        return codes
    finally:
        cur.close()
        conn.close()


def get_stock_codes_from_age() -> set[str]:
    """AGE에서 Stock 코드 집합 조회."""
    conn = get_db_connection()
    cur = init_age(conn)
    try:
        results = execute_cypher(cur, "MATCH (s:Stock) RETURN s.code")
        codes = set()
        for row in results:
            if row[0]:
                code = _parse_age_value(row[0])
                if code:
                    codes.add(code)
        return codes
    finally:
        cur.close()
        conn.close()


def get_etf_names_from_age() -> dict[str, str]:
    """AGE에서 ETF code→name 매핑 조회."""
    import json

    conn = get_db_connection()
    cur = init_age(conn)
    try:
        results = execute_cypher(cur, """
            MATCH (e:ETF) WHERE e.name IS NOT NULL
            RETURN {code: e.code, name: e.name}
        """)
        names = {}
        for row in results:
            if row[0]:
                data = json.loads(_parse_age_value(row[0]))
                if data.get('code') and data.get('name'):
                    names[data['code']] = data['name']
        return names
    finally:
        cur.close()
        conn.close()


# ──────────────────────────────────────────────
# 공용 수집 함수
# ──────────────────────────────────────────────

def collect_universe_and_prices(dates: list[str]) -> tuple[set[str], list[dict], list[str]]:
    """날짜별 KRX 데이터 → ETF 노드 + 메타데이터(보수율/운용사) + Price 노드 생성.

    Returns:
        (universe_codes, new_etfs_list, actual_dates)
    """
    from pykrx.website.krx.etx.core import ETF_전종목기본종목
    from math import ceil

    if not dates:
        return get_etf_codes_from_age(), [], []

    existing_codes = get_etf_codes_from_age()
    all_new_etfs = []
    actual_dates = []  # KRX API가 반환한 실제 거래일

    # 보수율 일괄 조회
    fee_map = {}
    try:
        fee_df = ETF_전종목기본종목().fetch()
        for _, row in fee_df.iterrows():
            code = row['ISU_SRT_CD']
            try:
                raw = float(row['ETF_TOT_FEE'])
                fee_map[code] = ceil(raw * 100) / 100
            except (ValueError, TypeError):
                pass
        log.info(f"Loaded expense ratio for {len(fee_map)} ETFs")
    except Exception as e:
        log.warning(f"Failed to fetch ETF fee data (pykrx KRX scraping may be broken): {e}")

    conn = get_db_connection()
    cur = init_age(conn)
    total_prices = 0

    try:
        seen_dates = set()  # 중복 수집 방지
        for bd in dates:
            krx_items, actual_date = get_krx_daily_data(bd)
            if not krx_items or not actual_date:
                continue
            if actual_date in seen_dates:
                log.info(f"[{bd}] Resolved to {actual_date} (already collected, skipping)")
                continue
            seen_dates.add(actual_date)
            if bd != actual_date:
                log.info(f"[{bd}] Resolved to actual trading date: {actual_date}")
            bd = actual_date  # 이후 모든 처리에 실제 거래일 사용
            actual_dates.append(actual_date)

            # ── 신규 ETF 노드 + 메타데이터 ──
            krx_dicts = [{'code': item.code, 'name': item.name,
                          'net_assets': item.net_assets} for item in krx_items]
            new_candidates = check_new_universe_candidates(krx_dicts, existing_codes)

            if new_candidates:
                items = [{'code': c['code']} for c in new_candidates]
                execute_cypher_batch(cur, """
                    MERGE (e:ETF {code: item.code}) RETURN e
                """, items)

                # name + expense_ratio
                with_fee = [{'code': c['code'], 'name': c['name'],
                             'expense_ratio': fee_map[c['code']]}
                            for c in new_candidates if c['code'] in fee_map]
                no_fee = [{'code': c['code'], 'name': c['name']}
                          for c in new_candidates if c['code'] not in fee_map]

                if with_fee:
                    execute_cypher_batch(cur, """
                        MATCH (e:ETF {code: item.code})
                        SET e.name = item.name, e.expense_ratio = item.expense_ratio
                        RETURN e
                    """, with_fee)
                if no_fee:
                    execute_cypher_batch(cur, """
                        MATCH (e:ETF {code: item.code})
                        SET e.name = item.name
                        RETURN e
                    """, no_fee)

                # Company + MANAGED_BY
                seen_companies = set()
                company_items = []
                etf_company_pairs = []
                for c in new_candidates:
                    company = get_company_from_etf_name(c['name'])
                    if company not in seen_companies:
                        company_items.append({'name': company})
                        seen_companies.add(company)
                    etf_company_pairs.append({'code': c['code'], 'company': company})

                if company_items:
                    execute_cypher_batch(cur, """
                        MERGE (c:Company {name: item.name}) RETURN c
                    """, company_items)
                if etf_company_pairs:
                    execute_cypher_batch(cur, """
                        MATCH (e:ETF {code: item.code})
                        MATCH (c:Company {name: item.company})
                        MERGE (e)-[:MANAGED_BY]->(c)
                        RETURN 1
                    """, etf_company_pairs)

                conn.commit()
                for c in new_candidates:
                    existing_codes.add(c['code'])
                all_new_etfs.extend([{'code': c['code'], 'name': c['name']}
                                     for c in new_candidates])
                log.info(f"[{bd}] Added {len(new_candidates)} new ETFs with metadata")

            # ── Price 노드 (유니버스만) ──
            date_str = f"{bd[:4]}-{bd[4:6]}-{bd[6:8]}"
            price_items = []
            for item in krx_items:
                if item.code not in existing_codes:
                    continue
                price_items.append({
                    'code': item.code, 'date': date_str,
                    'open': item.open_price, 'high': item.high_price,
                    'low': item.low_price, 'close': item.close_price,
                    'volume': item.volume, 'nav': item.nav,
                    'market_cap': item.market_cap, 'net_assets': item.net_assets,
                    'trade_value': item.trade_value,
                })

            if price_items:
                # Step 1: 없으면 생성
                execute_cypher_batch(cur, """
                    MATCH (e:ETF {code: item.code})
                    OPTIONAL MATCH (e)-[:HAS_PRICE]->(existing:Price {date: item.date})
                    WITH e, existing, item WHERE existing IS NULL
                    CREATE (e)-[:HAS_PRICE]->(:Price {date: item.date})
                    RETURN e
                """, price_items)
                # Step 2: 있으면 업데이트
                execute_cypher_batch(cur, """
                    MATCH (e:ETF {code: item.code})-[:HAS_PRICE]->(p:Price {date: item.date})
                    SET p.open = item.open, p.high = item.high, p.low = item.low,
                        p.close = item.close, p.volume = item.volume, p.nav = item.nav,
                        p.market_cap = item.market_cap, p.net_assets = item.net_assets,
                        p.trade_value = item.trade_value
                    RETURN p
                """, price_items)

                valid_na = [it for it in price_items
                            if it.get('net_assets') and it['net_assets'] > 0]
                if valid_na:
                    execute_cypher_batch(cur, """
                        MATCH (e:ETF {code: item.code})
                        SET e.net_assets = item.net_assets
                        RETURN e
                    """, valid_na)

                conn.commit()
                total_prices += len(price_items)
                log.info(f"[{bd}] {len(price_items)} ETF prices saved")

        log.info(f"Universe & prices: {len(existing_codes)} ETFs, "
                 f"{total_prices} price records")
        return existing_codes, all_new_etfs, actual_dates

    finally:
        cur.close()
        conn.close()


def collect_holdings_for_dates(etf_codes: list[str], dates: list[str]):
    """날짜별 HOLDS 엣지 + Stock 노드(이름/is_etf 포함) 배치 생성."""
    from pykrx import stock as pykrx_stock
    import pandas as pd
    import time
    from itertools import groupby

    if not etf_codes or not dates:
        return

    known_stocks = set()  # 이름 조회 완료된 Stock 코드 추적
    total_holds = 0

    for bd in dates:
        date_str = f"{bd[:4]}-{bd[4:6]}-{bd[6:8]}"

        # AGE에서 이미 HOLDS 엣지가 있는 ETF 스킵
        conn_chk = get_db_connection()
        cur_chk = init_age(conn_chk)
        try:
            results = execute_cypher(cur_chk, """
                MATCH (e:ETF)-[h:HOLDS {date: $date}]->(:Stock)
                WITH DISTINCT e.code AS code
                RETURN code
            """, {'date': date_str})
            existing_holds = set()
            for row in results:
                if row[0]:
                    code = _parse_age_value(row[0])
                    if code:
                        existing_holds.add(code)
        finally:
            cur_chk.close()
            conn_chk.close()

        remaining_etfs = [c for c in etf_codes if c not in existing_holds]
        if not remaining_etfs:
            log.info(f"[{bd}] All {len(etf_codes)} ETFs already have HOLDS, skipping")
            continue
        if existing_holds:
            log.info(f"[{bd}] Skipping {len(existing_holds)} ETFs with existing HOLDS, "
                     f"fetching {len(remaining_etfs)}")

        valid_tickers = get_valid_ticker_set(bd)

        all_holds = []
        all_stock_codes = set()

        for ticker in remaining_etfs:
            try:
                df = pykrx_stock.get_etf_portfolio_deposit_file(ticker, bd)
                if df is not None and not df.empty:
                    df = df[~df.index.astype(str).isin(['010010'])]  # 설정현금액 제외
                    df = df[df.index.astype(str).isin(valid_tickers)]
                    if '비중' in df.columns:
                        df = df.sort_values('비중', ascending=False).head(30)
                    else:
                        df = df.head(30)

                    for idx, row in df.iterrows():
                        stock_code = str(idx)
                        if not stock_code:
                            continue
                        weight = float(row.get('비중', 0))
                        shares_val = row.get('계약수', row.get('주수', 0))
                        shares = int(shares_val) if shares_val and not pd.isna(shares_val) else 0
                        all_holds.append({
                            'etf_code': ticker, 'stock_code': stock_code,
                            'date': date_str, 'weight': weight, 'shares': shares,
                        })
                        all_stock_codes.add(stock_code)

                time.sleep(0.1)
            except Exception as e:
                log.warning(f"Failed PDF for {ticker} on {bd}: {e}")

        if not all_holds:
            log.warning(f"[{bd}] No holdings data — pykrx get_etf_portfolio_deposit_file "
                        f"may be broken (KRX scraping API issue). Skipping.")
            continue

        conn = get_db_connection()
        cur = init_age(conn)

        try:
            # Stock 노드 MERGE
            if all_stock_codes:
                stock_items = [{'code': c} for c in all_stock_codes]
                execute_cypher_batch(cur, """
                    MERGE (s:Stock {code: item.code}) RETURN s
                """, stock_items)

                # 신규 Stock만 이름 조회 + is_etf 설정
                new_stocks = all_stock_codes - known_stocks
                if new_stocks:
                    # AGE 기반 ETF 코드/이름 매핑 (pykrx KRX 스크래핑 대체)
                    etf_tickers = get_etf_codes_from_age()
                    etf_name_map = get_etf_names_from_age()
                    name_items = []
                    for code in new_stocks:
                        try:
                            is_etf = code in etf_tickers
                            if is_etf:
                                name = etf_name_map.get(code) or str(pykrx_stock.get_etf_ticker_name(code))
                            else:
                                name = str(pykrx_stock.get_market_ticker_name(code))
                            if not name or isinstance(name, pd.DataFrame):
                                name = code
                        except Exception:
                            name = code
                            is_etf = code in etf_tickers
                        name_items.append({'code': code, 'name': name, 'is_etf': is_etf})

                    execute_cypher_batch(cur, """
                        MATCH (s:Stock {code: item.code})
                        SET s.name = item.name, s.is_etf = item.is_etf
                        RETURN s
                    """, name_items)
                    known_stocks.update(new_stocks)

                # is_etf IS NULL safety net (기존 Stock)
                execute_cypher_batch(cur, """
                    MATCH (s:Stock {code: item.code})
                    WHERE s.is_etf IS NULL
                    SET s.is_etf = false
                    RETURN s
                """, stock_items)
                conn.commit()

            # HOLDS 배치
            holds_sorted = sorted(all_holds, key=lambda x: x['etf_code'])
            COMMIT_EVERY = 50
            etf_groups = []
            for etf_code, group in groupby(holds_sorted, key=lambda x: x['etf_code']):
                etf_groups.append((etf_code, list(group)))

            for i in range(0, len(etf_groups), COMMIT_EVERY):
                batch_groups = etf_groups[i:i + COMMIT_EVERY]
                batch_items = [item for _, items in batch_groups for item in items]
                try:
                    execute_cypher_batch(cur, """
                        MATCH (e:ETF {code: item.etf_code})
                        MATCH (s:Stock {code: item.stock_code})
                        MERGE (e)-[h:HOLDS {date: item.date}]->(s)
                        RETURN h
                    """, batch_items)
                    execute_cypher_batch(cur, """
                        MATCH (e:ETF {code: item.etf_code})-[h:HOLDS {date: item.date}]->(s:Stock {code: item.stock_code})
                        SET h.weight = item.weight, h.shares = item.shares
                        RETURN h
                    """, batch_items)
                    conn.commit()
                except Exception as e:
                    log.warning(f"Failed HOLDS batch for {bd} at group {i}: {e}")
                    conn.rollback()
                    cur = init_age(conn)

            total_holds += len(all_holds)
            log.info(f"[{bd}] {len(all_holds)} HOLDS edges "
                     f"({len(all_stock_codes)} stocks)")

        finally:
            cur.close()
            conn.close()

    log.info(f"Holdings complete: {total_holds} edges across {len(dates)} dates")


def collect_stock_prices_for_dates(dates: list[str]):
    """날짜별 Stock 가격 배치 저장.

    pykrx Naver 백엔드(get_market_ohlcv_by_date)를 사용하여
    종목별로 가격을 조회한다. KRX 스크래핑 API(get_market_ohlcv_by_ticker)가
    깨져있으므로 이 방식을 사용.
    """
    from pykrx import stock as pykrx_stock
    import time

    if not dates:
        return

    # is_etf=false Stock 코드 조회
    conn = get_db_connection()
    cur = init_age(conn)
    try:
        results = execute_cypher(cur, """
            MATCH (s:Stock) WHERE s.is_etf = false RETURN s.code
        """, {})
        stock_codes = set()
        for row in results:
            if row[0]:
                code = _parse_age_value(row[0])
                if code:
                    stock_codes.add(code)
    finally:
        cur.close()
        conn.close()

    if not stock_codes:
        log.warning("No Stock nodes for price collection")
        return

    log.info(f"Collecting prices for {len(stock_codes)} stocks "
             f"across {len(dates)} dates (via Naver backend)")
    total_success = 0

    for bd in dates:
        conn = get_db_connection()
        cur = init_age(conn)
        try:
            date_str = f"{bd[:4]}-{bd[4:6]}-{bd[6:8]}"

            # AGE에서 이미 가격이 있는 종목 스킵
            existing_prices = set()
            try:
                results = execute_cypher(cur, """
                    MATCH (s:Stock)-[:HAS_PRICE]->(p:Price {date: $date})
                    RETURN s.code
                """, {'date': date_str})
                for row in results:
                    if row[0]:
                        code = _parse_age_value(row[0])
                        if code:
                            existing_prices.add(code)
            except Exception:
                pass

            remaining = stock_codes - existing_prices
            if not remaining:
                log.info(f"[{bd}] All {len(stock_codes)} stock prices already collected, skipping")
                continue
            if existing_prices:
                log.info(f"[{bd}] Skipping {len(existing_prices)} stocks with existing prices, "
                         f"fetching {len(remaining)}")

            # 종목별 Naver 백엔드로 가격 조회
            items = []
            error_count = 0
            for code in sorted(remaining):
                try:
                    df = pykrx_stock.get_market_ohlcv_by_date(bd, bd, code)
                    if df is not None and not df.empty:
                        row = df.iloc[0]
                        items.append({
                            'code': code, 'date': date_str,
                            'open': float(row.get('시가', 0)),
                            'high': float(row.get('고가', 0)),
                            'low': float(row.get('저가', 0)),
                            'close': float(row.get('종가', 0)),
                            'volume': int(row.get('거래량', 0)),
                            'change_rate': float(row.get('등락률', 0)),
                        })
                except Exception as e:
                    error_count += 1
                    if error_count <= 5:
                        log.warning(f"Failed price for {code} on {bd}: {e}")
                    elif error_count == 6:
                        log.warning(f"Suppressing further per-stock errors for {bd}...")
                time.sleep(0.3)

            if error_count > 5:
                log.warning(f"[{bd}] {error_count} total stock price errors")

            if not items:
                continue

            # Step 1: 없으면 생성
            execute_cypher_batch(cur, """
                MATCH (s:Stock {code: item.code})
                OPTIONAL MATCH (s)-[:HAS_PRICE]->(existing:Price {date: item.date})
                WITH s, existing, item WHERE existing IS NULL
                CREATE (s)-[:HAS_PRICE]->(:Price {date: item.date})
                RETURN s
            """, items)
            # Step 2: 있으면 업데이트
            execute_cypher_batch(cur, """
                MATCH (s:Stock {code: item.code})-[:HAS_PRICE]->(p:Price {date: item.date})
                SET p.open = item.open, p.high = item.high, p.low = item.low,
                    p.close = item.close, p.volume = item.volume,
                    p.change_rate = item.change_rate
                RETURN p
            """, items)

            conn.commit()
            total_success += len(items)
            log.info(f"[{bd}] {len(items)} stock prices saved")
        except Exception as e:
            log.warning(f"Failed stock prices for {bd}: {e}")
        finally:
            cur.close()
            conn.close()

    log.info(f"Stock prices complete: {total_success} records")


def record_collection_run(date_str: str) -> bool:
    """collection_runs 테이블에 수집 완료 기록 + pg_notify 발행.

    Returns: True if new record inserted, False if already existed.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO collection_runs (collected_at) VALUES (%s) "
            "ON CONFLICT (collected_at) DO NOTHING",
            (date_str,)
        )
        inserted = cur.rowcount > 0
        if inserted:
            cur.execute("NOTIFY new_collection, %s", (date_str,))
            log.info(f"Collection run recorded + notified: {date_str}")
        else:
            log.info(f"Collection run already exists: {date_str} — skipping notify")
        conn.commit()
        return inserted
    finally:
        cur.close()
        conn.close()


def _query_holdings(cur, etf_code: str, date_str: str) -> dict:
    """특정 날짜의 보유종목 비중 조회. {stock_code: {name, weight}} 딕셔너리 반환."""
    import json

    results = execute_cypher(cur, """
        MATCH (e:ETF {code: $etf_code})-[h:HOLDS {date: $date}]->(s:Stock)
        RETURN {code: s.code, name: s.name, weight: h.weight}
    """, {'etf_code': etf_code, 'date': date_str})

    holdings = {}
    for row in results:
        if row[0]:
            data = json.loads(_parse_age_value(row[0]))
            holdings[data['code']] = {
                'name': data['name'],
                'weight': float(data['weight']) if data.get('weight') else 0,
            }
    return holdings


def send_discord_notification(date_str: str):
    """admin 유저의 즐겨찾기 기반 비중변화를 디스코드로 발송."""
    import httpx
    import json

    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        log.info("DISCORD_WEBHOOK_URL not set — skipping Discord notification")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # RDB에서 admin user_id 조회
        rdb_cur = conn.cursor()
        rdb_cur.execute(
            "SELECT ur.user_id FROM user_roles ur "
            "JOIN roles r ON r.id = ur.role_id "
            "WHERE r.name = 'admin'"
        )
        admin_ids = [row[0] for row in rdb_cur.fetchall()]
        rdb_cur.close()

        if not admin_ids:
            log.info("No admin users found — skipping Discord notification")
            return

        # AGE에서 admin 유저의 WATCHES 조회
        watches = []
        for uid in admin_ids:
            results = execute_cypher(cur, """
                MATCH (u:User {user_id: $user_id})-[:WATCHES]->(e:ETF)
                RETURN {user_id: u.user_id, etf_code: e.code, etf_name: e.name}
            """, {'user_id': uid})
            for row in results:
                if row[0]:
                    data = json.loads(_parse_age_value(row[0]))
                    watches.append(data)

        if not watches:
            log.info("No admin watches found — skipping Discord notification")
            return

        # 1주일 전 HOLDS 날짜 조회 (가장 가까운 거래일)
        if watches:
            from datetime import datetime, timedelta
            one_week_ago = (datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=7)).strftime('%Y-%m-%d')
            first_etf = watches[0]['etf_code']
            prev_results = execute_cypher(cur, """
                MATCH (e:ETF {code: $code})-[h:HOLDS]->(:Stock)
                WITH DISTINCT h.date as d
                WHERE d <= $target_date
                RETURN {date: d}
                ORDER BY d DESC
                LIMIT 1
            """, {'code': first_etf, 'target_date': one_week_ago})
            prev_date = None
            if prev_results:
                raw = _parse_age_value(prev_results[0][0])
                prev_data = json.loads(raw)
                prev_date = prev_data.get('date')

        if not prev_date:
            log.info("No previous date found — skipping Discord notification")
            return

        # ETF별 비중변화 수집
        changes_summary = []
        for w in watches:
            etf_code = w['etf_code']
            etf_name = w['etf_name']

            # 현재 날짜 holdings
            today_h = _query_holdings(cur, etf_code, date_str)
            prev_h = _query_holdings(cur, etf_code, prev_date)

            if not today_h or not prev_h:
                continue

            etf_changes = []
            all_codes = set(today_h.keys()) | set(prev_h.keys())
            for code in all_codes:
                curr = today_h.get(code)
                prev = prev_h.get(code)
                cw = curr['weight'] if curr else 0
                pw = prev['weight'] if prev else 0
                diff = cw - pw

                if abs(diff) <= 3:
                    continue

                if curr and not prev:
                    ct = "신규편입"
                elif prev and not curr:
                    ct = "편출"
                elif diff > 0:
                    ct = "증가"
                else:
                    ct = "감소"

                name = (curr or prev)['name']
                etf_changes.append(f"  {ct} {name}: {pw:.1f}% → {cw:.1f}% ({diff:+.1f}%p)")

            if etf_changes:
                changes_summary.append(f"**{etf_name}** ({etf_code})\n" + "\n".join(etf_changes))

        if not changes_summary:
            log.info("No significant changes — skipping Discord notification")
            return

        # 디스코드 메시지 발송
        message = f"📊 **ETF 비중 변화 알림** ({date_str})\n\n" + "\n\n".join(changes_summary)

        with httpx.Client() as client:
            resp = client.post(webhook_url, json={"content": message})
            resp.raise_for_status()

        log.info(f"Discord notification sent: {len(changes_summary)} ETFs with changes")

    except Exception as e:
        log.warning(f"Discord notification failed: {e}")
    finally:
        cur.close()
        conn.close()


def update_etf_returns():
    """ETF 1D/1W/1M 수익률 계산 및 저장."""
    import json
    from collections import defaultdict
    from datetime import datetime, timedelta

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # 전체 ETF의 최근 45일 가격을 한 번에 조회
        rows = execute_cypher(cur, """
            MATCH (e:ETF)-[:HAS_PRICE]->(p:Price)
            WITH e.code AS code, p.date AS date, p.close AS close, p.market_cap AS market_cap
            ORDER BY date DESC
            RETURN {code: code, date: date, close: close, market_cap: market_cap}
        """)

        if not rows:
            log.warning("No price data for returns calculation")
            return

        # ETF별 가격 그룹핑 (최근 45개만)
        etf_prices = defaultdict(list)
        for r in rows:
            if not r[0]:
                continue
            parsed = json.loads(_parse_age_value(r[0]))
            if parsed.get('close') is not None and parsed.get('date') is not None:
                code = parsed['code']
                if len(etf_prices[code]) < 45:
                    etf_prices[code].append(parsed)

        log.info(f"Calculating returns for {len(etf_prices)} ETFs")
        update_items = []

        for code, prices in etf_prices.items():
            try:
                if not prices:
                    continue

                latest_close = float(prices[0]['close'])
                if latest_close == 0:
                    continue

                latest_date = datetime.strptime(prices[0]['date'], '%Y-%m-%d')
                target_1w = (latest_date - timedelta(days=7)).strftime('%Y-%m-%d')
                target_1m = (latest_date - timedelta(days=30)).strftime('%Y-%m-%d')

                item = {
                    'code': code, 'close_price': latest_close,
                    'return_1d': None, 'return_1w': None, 'return_1m': None,
                    'market_cap_change_1w': None,
                }

                if len(prices) > 1:
                    prev = float(prices[1]['close'])
                    if prev > 0:
                        item['return_1d'] = round((latest_close - prev) / prev * 100, 2)

                for p in prices[1:]:
                    if p['date'] <= target_1w:
                        prev = float(p['close'])
                        if prev > 0:
                            item['return_1w'] = round((latest_close - prev) / prev * 100, 2)
                        latest_mc = prices[0].get('market_cap')
                        prev_mc = p.get('market_cap')
                        if latest_mc and prev_mc:
                            item['market_cap_change_1w'] = round(
                                (float(latest_mc) - float(prev_mc)) / float(prev_mc) * 100, 2)
                        break

                for p in prices[1:]:
                    if p['date'] <= target_1m:
                        prev = float(p['close'])
                        if prev > 0:
                            item['return_1m'] = round((latest_close - prev) / prev * 100, 2)
                        break

                update_items.append(item)
            except Exception as e:
                log.warning(f"Failed returns for {code}: {e}")

        if update_items:
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                SET e.close_price = item.close_price,
                    e.return_1d = item.return_1d,
                    e.return_1w = item.return_1w,
                    e.return_1m = item.return_1m,
                    e.market_cap_change_1w = item.market_cap_change_1w
                RETURN e
            """, update_items)
            conn.commit()
            log.info(f"Updated returns for {len(update_items)} ETFs")
        else:
            log.warning("No return data to update")

    finally:
        cur.close()
        conn.close()
