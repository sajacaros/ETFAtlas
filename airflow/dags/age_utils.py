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

RULE_ONLY_TAGS = ['코스피200', '코스닥150']

# 이름이 200/200TR/150으로 끝나는 ETF만 매칭 (TIGER 200 중공업 등 섹터 ETF 제외)
INDEX_TAG_PATTERNS = [
    (r'(?<!\d)200(?:TR)?\s*$', '코스피200'),
    (r'(?<!\d)200액티브', '코스피200'),
    (r'(?<!\d)150\s*$', '코스닥150'),
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
    """pykrx로 영업일 목록 조회. YYYYMMDD 리스트 반환."""
    from pykrx import stock
    business_days = stock.get_previous_business_days(fromdate=from_date, todate=to_date)
    return [d.strftime('%Y%m%d') for d in business_days]


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


# ──────────────────────────────────────────────
# 공용 수집 함수
# ──────────────────────────────────────────────

def collect_universe_and_prices(dates: list[str]) -> tuple[set[str], list[dict]]:
    """날짜별 KRX 데이터 → ETF 노드 + 메타데이터(보수율/운용사) + Price 노드 생성.

    Returns:
        (universe_codes, new_etfs_list)
    """
    from pykrx.website.krx.etx.core import ETF_전종목기본종목
    from math import ceil

    if not dates:
        return get_etf_codes_from_age(), []

    existing_codes = get_etf_codes_from_age()
    all_new_etfs = []

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
        log.warning(f"Failed to fetch ETF fee data: {e}")

    conn = get_db_connection()
    cur = init_age(conn)
    total_prices = 0

    try:
        for bd in dates:
            krx_items = _get_krx_data_for_exact_date(bd)
            if not krx_items:
                continue

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
                execute_cypher_batch(cur, """
                    MATCH (e:ETF {code: item.code})
                    MERGE (e)-[:HAS_PRICE]->(p:Price {date: item.date})
                    RETURN p
                """, price_items)
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
        return existing_codes, all_new_etfs

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
        valid_tickers = get_valid_ticker_set(bd)

        all_holds = []
        all_stock_codes = set()

        for ticker in etf_codes:
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
            log.info(f"[{bd}] No holdings data, skipping")
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
                    etf_tickers = set(pykrx_stock.get_etf_ticker_list(bd))
                    name_items = []
                    for code in new_stocks:
                        try:
                            is_etf = code in etf_tickers
                            if is_etf:
                                name = str(pykrx_stock.get_etf_ticker_name(code))
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
    """날짜별 Stock 가격 배치 저장."""
    from pykrx import stock as pykrx_stock

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
             f"across {len(dates)} dates")
    total_success = 0

    for bd in dates:
        conn = get_db_connection()
        cur = init_age(conn)
        try:
            date_str = f"{bd[:4]}-{bd[4:6]}-{bd[6:8]}"
            df = pykrx_stock.get_market_ohlcv_by_ticker(bd)
            if df is None or df.empty:
                continue

            items = []
            for code in stock_codes:
                if code in df.index:
                    row = df.loc[code]
                    items.append({
                        'code': code, 'date': date_str,
                        'open': float(row.get('시가', 0)),
                        'high': float(row.get('고가', 0)),
                        'low': float(row.get('저가', 0)),
                        'close': float(row.get('종가', 0)),
                        'volume': int(row.get('거래량', 0)),
                        'change_rate': float(row.get('등락률', 0)),
                    })

            if not items:
                continue

            execute_cypher_batch(cur, """
                MATCH (s:Stock {code: item.code})
                MERGE (s)-[:HAS_PRICE]->(p:Price {date: item.date})
                RETURN p
            """, items)
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


def detect_changes_for_dates(etf_codes: list[str], dates: list[str]):
    """연속 영업일 간 HOLDS 비교 → Change 노드 생성.

    dates[0]은 비교 대상(전일)이 없으므로 dates[1]부터 감지.
    """
    import uuid

    if len(dates) < 2 or not etf_codes:
        log.info("Need at least 2 dates for change detection")
        return

    # YYYY-MM-DD 형식 변환
    date_strs = [f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in dates]

    total_changes = 0

    for i in range(1, len(date_strs)):
        today = date_strs[i]
        yesterday = date_strs[i - 1]

        conn = get_db_connection()
        cur = init_age(conn)

        try:
            change_items = []
            for ticker in etf_codes:
                try:
                    today_h = _query_holdings(cur, ticker, today)
                    yesterday_h = _query_holdings(cur, ticker, yesterday)

                    if not today_h or not yesterday_h:
                        continue

                    changes = _compare_holdings(today_h, yesterday_h)

                    for change in changes:
                        change_items.append({
                            'etf_code': ticker,
                            'change_id': str(uuid.uuid4()),
                            'stock_code': change['stock_code'],
                            'stock_name': change['stock_name'],
                            'change_type': change['type'],
                            'before_weight': change['before_weight'] or 0,
                            'after_weight': change['after_weight'] or 0,
                            'weight_change': change.get('weight_change', 0),
                            'detected_at': today,
                        })
                except Exception as e:
                    log.warning(f"Failed changes for {ticker} ({yesterday}→{today}): {e}")

            if change_items:
                try:
                    execute_cypher_batch(cur, """
                        MATCH (e:ETF {code: item.etf_code})
                        CREATE (c:Change {
                            id: item.change_id,
                            stock_code: item.stock_code,
                            stock_name: item.stock_name,
                            change_type: item.change_type,
                            before_weight: item.before_weight,
                            after_weight: item.after_weight,
                            weight_change: item.weight_change,
                            detected_at: item.detected_at
                        })
                        CREATE (e)-[:HAS_CHANGE]->(c)
                        RETURN c
                    """, change_items)
                    conn.commit()
                except Exception as e:
                    log.warning(f"Failed batch change creation ({yesterday}→{today}): {e}")
                    conn.rollback()
                    cur = init_age(conn)

            total_changes += len(change_items)
            if change_items:
                log.info(f"[{yesterday}→{today}] {len(change_items)} changes detected")

        finally:
            cur.close()
            conn.close()

    log.info(f"Change detection complete: {total_changes} changes "
             f"across {len(dates) - 1} date pairs")


def _query_holdings(cur, etf_code: str, date: str) -> dict:
    """AGE에서 특정 ETF의 특정 날짜 HOLDS 조회 → {stock_code: {name, weight}}"""
    import json

    results = execute_cypher(cur, """
        MATCH (e:ETF {code: $etf_code})-[h:HOLDS {date: $date}]->(s:Stock)
        RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight}
    """, {'etf_code': etf_code, 'date': date})

    holdings = {}
    for row in results:
        if row[0]:
            raw = _parse_age_value(row[0])
            data = json.loads(raw)
            if isinstance(data, dict):
                code = data.get('stock_code', '')
                if code:
                    holdings[code] = {
                        'name': data.get('stock_name', ''),
                        'weight': float(data.get('weight', 0)),
                    }
    return holdings


def _compare_holdings(today_h: dict, yesterday_h: dict) -> list:
    """두 스냅샷 비교 → 편입/제외/비중변화 리스트."""
    changes = []

    for code, data in today_h.items():
        if code not in yesterday_h:
            changes.append({
                'type': 'added', 'stock_code': code, 'stock_name': data['name'],
                'before_weight': None, 'after_weight': data['weight'],
                'weight_change': data['weight'],
            })

    for code, data in yesterday_h.items():
        if code not in today_h:
            changes.append({
                'type': 'removed', 'stock_code': code, 'stock_name': data['name'],
                'before_weight': data['weight'], 'after_weight': None,
                'weight_change': -data['weight'],
            })

    for code, today_data in today_h.items():
        if code in yesterday_h:
            diff = today_data['weight'] - yesterday_h[code]['weight']
            if abs(diff) >= 5.0:
                changes.append({
                    'type': 'increased' if diff > 0 else 'decreased',
                    'stock_code': code, 'stock_name': today_data['name'],
                    'before_weight': yesterday_h[code]['weight'],
                    'after_weight': today_data['weight'],
                    'weight_change': diff,
                })

    return changes


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
