"""
age_utils — Apache AGE + KRX 공용 유틸리티

age_sync_universe / age_tagging / embed_code_examples DAG에서 공통으로 사용하는 함수들.
"""

import logging
import re
import os
from datetime import datetime, time, timedelta

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
    '마이다스': '마이다스에셋자산운용',
    'MIDAS': '마이다스에셋자산운용',
    '파워': '교보악사자산운용',
    'BNK': 'BNK자산운용',
    'DAISHIN': '대신자산운용',  # DAISHIN343 포함
    'HK': '흥국자산운용',
    'UNICORN': '현대자산운용',
    'IBK': 'IBK자산운용',
    '아이엠에셋': 'iM에셋자산운용',
    'FOCUS': '브이아이자산운용',
    'DS ': '디에스자산운용',  # 공백 포함: DS로 시작하는 다른 브랜드와 구분
    '에셋플러스': '에셋플러스자산운용',
    '마이티': 'DB자산운용',
    'TREX': '유리자산운용',
    'TRUSTON': '트러스톤자산운용',
    '더제이': '더제이자산운용',
    'KCGI': 'KCGI자산운용',
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

# 코스피 계열: 200, 200TR, 200액티브, 코스피, 코스피TR, 코스피액티브, 코스피100, 코스피대형주, KRX300
# 코스닥 계열: 150, 코스닥, 코스닥액티브
INDEX_TAG_PATTERNS = [
    (r'(?<!\d)200(?:TR)?\s*$', '코스피'),
    (r'(?<!\d)200액티브', '코스피'),
    (r'코스피(?:TR|액티브|100|50|대형주)?\s*$', '코스피'),
    (r'KRX300', '코스피'),
    (r'(?<!\d)150\s*$', '코스닥'),
    (r'코스닥(?:TR|액티브|150)?\s*$', '코스닥'),
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
    escaped = escaped.replace('$$', '$ $')  # cypher()를 감싼 $$ 인용이 끊기지 않게
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
# 유니버스 필터링
# ──────────────────────────────────────────────

LISTED_CODE_RE = re.compile(r'^[0-9][0-9A-Z]{5}$')  # KRX 상장 단축코드 (예: 005930, 0131V0)
CASH_CODES = {'010010'}  # 설정현금액


def is_listed_security_code(code: str) -> bool:
    """KRX 상장 주식/ETF 단축코드 여부 (채권·선물·현금 등 구성요소 제외용)."""
    return bool(LISTED_CODE_RE.match(code)) and code not in CASH_CODES


# 유니버스 조건: 국내 주식형 ETF, 순자산 500억 이상
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

# 부분 문자열로는 오탐이 나는 제외 대상 (예: '은'은 '은행'과 겹친다)
EXCLUDE_PATTERNS = [
    r'(?:^|\s)은(?!행)',  # 은 현물/액티브 (1Q 은액티브, TIGER 은액티브)
]

MIN_AUM = 500 * 100_000_000  # 500억


def passes_universe_name_filter(name: str) -> bool:
    """제외 키워드(레버리지/채권/원자재 등)·해외 키워드가 없으면 True. API 호출 전 1차 필터."""
    name_lower = name.lower()
    if any(kw.lower() in name_lower for kw in EXCLUDE_KEYWORDS):
        return False
    if any(re.search(p, name) for p in EXCLUDE_PATTERNS):
        return False
    if any(kw.lower() in name_lower or kw in name for kw in FOREIGN_NAME_KEYWORDS):
        return False
    return True


def check_new_universe_candidates(etf_dicts: list, existing_codes: set) -> list:
    """새로운 유니버스 후보 ETF 확인 (기존 유니버스에 없음 + 이름 필터 통과 + 순자산 500억 이상)"""
    candidates = []
    for item in etf_dicts:
        if item['code'] in existing_codes:
            continue
        if item.get('net_assets', 0) < MIN_AUM:
            continue
        if not passes_universe_name_filter(item['name']):
            continue
        candidates.append({
            'code': item['code'],
            'name': item['name'],
            'index_name': '',
            'net_assets': item['net_assets'],
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


BUSINESS_DAY_REFERENCE_CODE = '069500'  # KODEX 200 — 모든 거래일에 거래됨
MARKET_SETTLED_TIME = time(16, 0)  # 15:30 종가 확정 후 여유


def last_settled_day(now: datetime) -> str:
    """종가가 확정된 마지막 날짜(YYYYMMDD). 장 마감 전이면 전날.

    KIS 일봉은 장중에도 당일 봉(미완성)을 돌려주므로 수집 범위 끝을 여기서 자른다.
    휴장일 여부는 보지 않는다 — get_business_days가 거른다.
    """
    day = now if now.time() >= MARKET_SETTLED_TIME else now - timedelta(days=1)
    return day.strftime('%Y%m%d')


def get_business_days(from_date: str, to_date: str) -> list[str]:
    """KIS 일봉(기준 ETF)으로 영업일 목록 조회. YYYYMMDD 리스트 반환."""
    kis = get_kis_client()
    if kis is None:
        return []
    try:
        bars = kis.get_daily_bars(BUSINESS_DAY_REFERENCE_CODE, from_date, to_date)
        return [b.date for b in bars]
    except Exception as e:
        log.warning(f"Failed to get business days via KIS daily bars: {e}")
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


ETF_PROFILE_FIELDS = ('expense_ratio', 'description', 'base_index', 'listed_date')


def set_etf_profiles(cur, profiles: dict[str, dict]):
    """ETF 프로필 필드를 ETF 노드 속성으로 저장. 값이 없는 필드는 기존 값을 그대로 둔다."""
    for field in ETF_PROFILE_FIELDS:
        items = [{'code': code, 'value': p[field]}
                 for code, p in profiles.items() if p.get(field) is not None]
        execute_cypher_batch(cur, f"""
            MATCH (e:ETF {{code: item.code}})
            SET e.{field} = item.value
            RETURN 1
        """, items)


def diff_etf_profiles(current: dict[str, dict], fetched: dict[str, dict]) -> dict[str, dict]:
    """조회한 프로필 중 저장된 값과 다른 필드만 남긴다. 바뀐 필드가 없는 ETF는 빠진다."""
    changed = {}
    for code, profile in fetched.items():
        old = current.get(code, {})
        diff = {f: v for f, v in profile.items() if old.get(f) != v}
        if diff:
            changed[code] = diff
    return changed


def refresh_etf_profiles(cur, codes) -> int:
    """네이버에서 ETF 프로필을 조회해 기존 값과 다른 필드만 SET. 갱신된 ETF 수 반환.

    ETF당 값 하나(노드 속성)만 두며 이력은 남기지 않는다. 조회 실패·빈 필드는 기존 값 유지.
    """
    import json
    from naver_client import fetch_etf_profiles

    fields = ", ".join(f"{f}: e.{f}" for f in ETF_PROFILE_FIELDS)
    current = {}
    for row in execute_cypher(cur, f"MATCH (e:ETF) RETURN {{code: e.code, {fields}}}"):
        if row[0]:
            props = json.loads(_parse_age_value(row[0]))
            current[props['code']] = props
    changed = diff_etf_profiles(current, fetch_etf_profiles(sorted(codes)))
    set_etf_profiles(cur, changed)
    return len(changed)


# ──────────────────────────────────────────────
# 공용 수집 함수
# ──────────────────────────────────────────────

def collect_universe_and_prices(dates: list[str]) -> tuple[set[str], list[dict], list[str]]:
    """KIS 기반 ETF 유니버스 갱신 + ETF Price 노드 생성.

    - 목록: KIS 종목 마스터 파일(ETF 그룹) — 인증 불필요
    - 신규 편입: 이름 필터 통과 후보만 ETF 현재가(순자산)를 조회해 500억 이상이면 추가
    - 가격: 날짜별 OHLCV·거래대금은 KIS 일봉, NAV/순자산/시가총액은 ETF 현재가(최근 거래일에만)
    - 보수율·설명·기초지수·상장일: 유니버스 전체를 네이버 증권에서 조회해 바뀐 필드만 갱신

    Args:
        dates: 수집할 영업일 목록 (YYYYMMDD, get_business_days 결과)

    Returns:
        (universe_codes, new_etfs_list, actual_dates)
    """
    from kis_api_client import fetch_etf_master
    if not dates:
        return get_etf_codes_from_age(), [], []

    kis = get_kis_client()
    if kis is None:
        log.warning("Skipping universe/prices (KIS credentials missing)")
        return get_etf_codes_from_age(), [], []

    dates = sorted(dates)
    latest = dates[-1]
    existing_codes = get_etf_codes_from_age()
    all_new_etfs = []

    # ── 1. 현재 시점 스냅샷: 기존 유니버스 + 이름 필터 통과 후보 ──
    master = dict(fetch_etf_master())
    log.info(f"ETF master: {len(master)} ETFs")
    targets = [c for c in master if c in existing_codes or passes_universe_name_filter(master[c])]
    snapshots = {}
    for code in targets:
        try:
            snapshots[code] = kis.get_etf_snapshot(code)
        except Exception as e:
            log.warning(f"Failed ETF snapshot for {code}: {e}")
    log.info(f"ETF snapshots: {len(snapshots)}/{len(targets)}")

    conn = get_db_connection()
    cur = init_age(conn)
    total_prices = 0

    try:
        # ── 2. 신규 ETF 노드 + 메타데이터 ──
        snapshot_dicts = [{'code': c, 'name': master[c], 'net_assets': snap.net_assets}
                          for c, snap in snapshots.items()]
        new_candidates = check_new_universe_candidates(snapshot_dicts, existing_codes)

        if new_candidates:
            items = [{'code': c['code']} for c in new_candidates]
            execute_cypher_batch(cur, """
                MERGE (e:ETF {code: item.code}) RETURN e
            """, items)

            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                SET e.name = item.name
                RETURN e
            """, [{'code': c['code'], 'name': c['name']} for c in new_candidates])

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
            log.info(f"[{latest}] Added {len(new_candidates)} new ETFs with metadata")

        # ── 2-1. 프로필(보수율·설명·기초지수·상장일): 유니버스 전체 조회 후 바뀐 필드만 갱신 ──
        changed = refresh_etf_profiles(cur, existing_codes)
        conn.commit()
        log.info(f"[{latest}] ETF profile changed: {changed} ETFs")

        # ── 3. Price 노드 (유니버스 ETF) ──
        price_items = []
        for code in sorted(existing_codes):
            try:
                bars = kis.get_daily_bars(code, dates[0], latest)
            except Exception as e:
                log.warning(f"Failed ETF daily bars for {code}: {e}")
                continue
            snap = snapshots.get(code)
            for bar in bars:
                if bar.date not in dates:
                    continue
                item = {
                    'code': code, 'date': f"{bar.date[:4]}-{bar.date[4:6]}-{bar.date[6:8]}",
                    'open': bar.open, 'high': bar.high, 'low': bar.low, 'close': bar.close,
                    'volume': bar.volume, 'trade_value': bar.trade_value,
                    'nav': None, 'market_cap': None, 'net_assets': None,
                }
                if bar.date == latest and snap:
                    # 현재가 API는 날짜 지정이 안 되므로 최근 거래일에만 반영
                    item.update(nav=snap.nav, net_assets=snap.net_assets,
                                market_cap=bar.close * snap.listed_shares)
                price_items.append(item)

        if price_items:
            # Step 1: 없으면 생성
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                OPTIONAL MATCH (e)-[:HAS_PRICE]->(existing:Price {date: item.date})
                WITH e, existing, item WHERE existing IS NULL
                CREATE (e)-[:HAS_PRICE]->(:Price {date: item.date})
                RETURN e
            """, price_items)
            # Step 2: 값 갱신
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})-[:HAS_PRICE]->(p:Price {date: item.date})
                SET p.open = item.open, p.high = item.high, p.low = item.low,
                    p.close = item.close, p.volume = item.volume, p.nav = item.nav,
                    p.market_cap = item.market_cap, p.net_assets = item.net_assets,
                    p.trade_value = item.trade_value
                RETURN p
            """, price_items)

            valid_na = [it for it in price_items if it.get('net_assets')]
            if valid_na:
                execute_cypher_batch(cur, """
                    MATCH (e:ETF {code: item.code})
                    SET e.net_assets = item.net_assets
                    RETURN e
                """, valid_na)

            conn.commit()
            total_prices = len(price_items)

        actual_dates = sorted({it['date'].replace('-', '') for it in price_items})
        log.info(f"Universe & prices: {len(existing_codes)} ETFs, "
                 f"{total_prices} price records, dates={actual_dates}")
        return existing_codes, all_new_etfs, actual_dates

    finally:
        cur.close()
        conn.close()


def get_kis_client():
    """환경변수 기반 KIS 클라이언트 (토큰은 kis_tokens 테이블에 캐시). 키가 없으면 None."""
    import os
    from kis_api_client import KISApiClient, PostgresTokenCache, DEFAULT_BASE_URL

    app_key = os.environ.get('KIS_APP_KEY', '')
    app_secret = os.environ.get('KIS_APP_SECRET', '')
    if not app_key or not app_secret:
        log.warning("KIS_APP_KEY/KIS_APP_SECRET not set")
        return None
    return KISApiClient(
        app_key, app_secret,
        base_url=os.environ.get('KIS_BASE_URL') or DEFAULT_BASE_URL,
        token_cache=PostgresTokenCache(get_db_connection),
    )


def collect_holdings(etf_codes: list[str], bd: str):
    """KIS ETF 구성종목시세로 현재 구성종목을 조회해 bd(YYYYMMDD) 날짜의 HOLDS 엣지로 저장.

    KIS API는 날짜 지정이 불가능(호출 시점 스냅샷)하므로 과거 날짜 백필은 지원하지 않는다.
    bd에는 최근 거래일을 넘긴다. Stock 노드(이름/is_etf 포함)도 함께 생성.
    """
    from itertools import groupby

    if not etf_codes or not bd:
        return

    kis = get_kis_client()
    if kis is None:
        log.warning("Skipping holdings collection (KIS credentials missing)")
        return

    date_str = f"{bd[:4]}-{bd[4:6]}-{bd[6:8]}"

    # AGE에서 이미 HOLDS 엣지가 있는 ETF 스킵 (같은 날 재실행 대비)
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
        refresh_current_holds(date_str)
        return
    if existing_holds:
        log.info(f"[{bd}] Skipping {len(existing_holds)} ETFs with existing HOLDS, "
                 f"fetching {len(remaining_etfs)}")

    all_holds = []
    stock_names = {}  # stock_code -> KIS 종목명
    failed = 0

    for ticker in remaining_etfs:
        try:
            components = [
                c for c in kis.get_etf_components(ticker)
                if is_listed_security_code(c.stock_code)  # 주식/ETF만 (채권·현금·선물 제외)
            ]
            components.sort(key=lambda c: c.weight, reverse=True)
            for c in components[:30]:
                all_holds.append({
                    'etf_code': ticker, 'stock_code': c.stock_code,
                    'date': date_str, 'weight': c.weight, 'shares': c.shares,
                })
                if c.stock_name:
                    stock_names.setdefault(c.stock_code, c.stock_name)
        except Exception as e:
            failed += 1
            log.warning(f"Failed KIS components for {ticker}: {e}")

    if failed:
        log.warning(f"[{bd}] KIS component fetch failed for {failed}/{len(remaining_etfs)} ETFs")
    if not all_holds:
        log.warning(f"[{bd}] No holdings data from KIS. Skipping.")
        refresh_current_holds(date_str)
        return

    all_stock_codes = {h['stock_code'] for h in all_holds}

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # Stock 노드 MERGE
        if all_stock_codes:
            stock_items = [{'code': c} for c in all_stock_codes]
            execute_cypher_batch(cur, """
                MERGE (s:Stock {code: item.code}) RETURN s
            """, stock_items)

            # Stock 이름/is_etf 갱신 (ETF는 AGE 이름 우선, 주식은 KIS 종목명)
            new_stocks = all_stock_codes
            if new_stocks:
                etf_tickers = get_etf_codes_from_age()
                etf_name_map = get_etf_names_from_age()
                name_items = []
                for code in new_stocks:
                    is_etf = code in etf_tickers
                    name = (etf_name_map.get(code) if is_etf else None) or stock_names.get(code) or code
                    name_items.append({'code': code, 'name': name, 'is_etf': is_etf})

                execute_cypher_batch(cur, """
                    MATCH (s:Stock {code: item.code})
                    SET s.name = item.name, s.is_etf = item.is_etf
                    RETURN s
                """, name_items)

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

        log.info(f"[{bd}] {len(all_holds)} HOLDS edges "
                 f"({len(all_stock_codes)} stocks)")

    finally:
        cur.close()
        conn.close()

    refresh_current_holds(date_str)


def refresh_current_holds(date_str: str):
    """date_str(YYYY-MM-DD) HOLDS를 ETF별 최신 구성종목(CURRENT_HOLDS)으로 갈아 끼운다.

    HOLDS는 날짜별 이력이라 계속 늘어나므로, "현재 보유" 조회는 ETF당 최대 30개인 CURRENT_HOLDS만 읽게 한다.
    그날 HOLDS가 있는 ETF만 바꾸므로 KIS 조회에 실패한 ETF는 이전 구성종목을 유지하고,
    이미 더 최근 날짜로 갱신된 ETF는 건드리지 않는다. 같은 날짜로 다시 돌려도 결과가 같다.
    """
    conn = get_db_connection()
    cur = init_age(conn)
    try:
        rows = execute_cypher(cur, """
            MATCH (e:ETF)-[:HOLDS {date: $date}]->(:Stock)
            WITH DISTINCT e
            OPTIONAL MATCH (e)-[c:CURRENT_HOLDS]->(:Stock)
            WITH e, max(c.date) AS current_date
            WHERE current_date IS NULL OR current_date <= $date
            RETURN e.code
        """, {'date': date_str})
        items = [{'code': _parse_age_value(r[0]), 'date': date_str} for r in rows if r[0]]
        if not items:
            return
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})-[c:CURRENT_HOLDS]->(:Stock)
            DELETE c RETURN 1
        """, items)
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})-[h:HOLDS {date: item.date}]->(s:Stock)
            CREATE (e)-[:CURRENT_HOLDS {date: h.date, weight: h.weight, shares: h.shares}]->(s)
            RETURN 1
        """, items)
        conn.commit()
        log.info(f"[{date_str}] CURRENT_HOLDS refreshed for {len(items)} ETFs")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def collect_stock_prices_for_dates(dates: list[str]):
    """Stock(is_etf=false) 일봉을 KIS 기간별시세로 조회해 날짜별 Price 노드로 저장.

    종목당 기간 전체를 한 번(100일 단위)에 조회하고, 이미 저장된 (종목, 날짜)는 건너뛴다.
    """
    if not dates:
        return

    kis = get_kis_client()
    if kis is None:
        log.warning("Skipping stock prices (KIS credentials missing)")
        return

    date_strs = {f"{d[:4]}-{d[4:6]}-{d[6:8]}" for d in dates}

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

        # 이미 저장된 (종목, 날짜)
        existing = set()
        results = execute_cypher(cur, """
            MATCH (s:Stock)-[:HAS_PRICE]->(p:Price)
            WHERE s.is_etf = false AND p.date >= $from_date AND p.date <= $to_date
            RETURN s.code + '|' + p.date
        """, {'from_date': min(date_strs), 'to_date': max(date_strs)})
        for row in results:
            key = _parse_age_value(row[0]) if row[0] else ''
            if '|' in key:
                code, date_str = key.split('|', 1)
                existing.add((code, date_str))
    finally:
        cur.close()
        conn.close()

    if not stock_codes:
        log.warning("No Stock nodes for price collection")
        return

    targets = sorted(c for c in stock_codes
                     if any((c, d) not in existing for d in date_strs))
    log.info(f"Collecting prices for {len(targets)}/{len(stock_codes)} stocks "
             f"across {len(dates)} dates (via KIS daily bars)")

    total_success = 0
    error_count = 0
    COMMIT_EVERY = 50
    pending_items = []

    def flush(items):
        if not items:
            return
        conn = get_db_connection()
        cur = init_age(conn)
        try:
            # Step 1: 없으면 생성
            execute_cypher_batch(cur, """
                MATCH (s:Stock {code: item.code})
                OPTIONAL MATCH (s)-[:HAS_PRICE]->(existing:Price {date: item.date})
                WITH s, existing, item WHERE existing IS NULL
                CREATE (s)-[:HAS_PRICE]->(:Price {date: item.date})
                RETURN s
            """, items)
            # Step 2: 값 갱신
            execute_cypher_batch(cur, """
                MATCH (s:Stock {code: item.code})-[:HAS_PRICE]->(p:Price {date: item.date})
                SET p.open = item.open, p.high = item.high, p.low = item.low,
                    p.close = item.close, p.volume = item.volume,
                    p.change_rate = item.change_rate
                RETURN p
            """, items)
            conn.commit()
        finally:
            cur.close()
            conn.close()

    for i, code in enumerate(targets, 1):
        try:
            for bar in kis.get_daily_bars(code, min(dates), max(dates)):
                date_str = f"{bar.date[:4]}-{bar.date[4:6]}-{bar.date[6:8]}"
                if date_str not in date_strs or (code, date_str) in existing:
                    continue
                pending_items.append({
                    'code': code, 'date': date_str,
                    'open': float(bar.open), 'high': float(bar.high),
                    'low': float(bar.low), 'close': float(bar.close),
                    'volume': bar.volume, 'change_rate': bar.change_rate,
                })
        except Exception as e:
            error_count += 1
            if error_count <= 5:
                log.warning(f"Failed KIS daily bars for {code}: {e}")
            elif error_count == 6:
                log.warning("Suppressing further per-stock errors...")

        if i % COMMIT_EVERY == 0 or i == len(targets):
            try:
                flush(pending_items)
                total_success += len(pending_items)
            except Exception as e:
                log.warning(f"Failed stock price batch at {i}: {e}")
            pending_items = []

    if error_count:
        log.warning(f"{error_count} stocks failed")
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


DISCORD_MAX_CONTENT = 2000  # 디스코드 메시지 content 최대 길이


def _load_discord_settings(conn) -> dict:
    """디스코드 알림 설정. 웹(관리자 페이지)에서 저장한 discord_settings가 우선,
    저장 전이거나 주소가 비었으면 환경변수 DISCORD_WEBHOOK_URL을 쓴다."""
    settings = {'enabled': True, 'webhook_url': None, 'threshold': 3.0}
    cur = conn.cursor()
    try:
        cur.execute("SELECT enabled, webhook_url, threshold FROM discord_settings WHERE id = 1")
        row = cur.fetchone()
    finally:
        cur.close()
    if row:
        settings.update(enabled=row[0], webhook_url=row[1], threshold=row[2])
    if not settings['webhook_url']:
        settings['webhook_url'] = os.environ.get('DISCORD_WEBHOOK_URL')
    return settings


def _split_discord_messages(header: str, blocks: list[str], limit: int = DISCORD_MAX_CONTENT) -> list[str]:
    """헤더 + ETF별 블록을 limit 이하 메시지들로 나눈다.

    블록은 쪼개지 않고 통째로 담고, 블록 하나가 limit을 넘을 때만 줄 단위로 나눈다
    (이어지는 조각엔 ETF 제목에 '(계속)'을 붙인다). 둘째 메시지부터는 헤더에 (n/N)을 단다.
    """
    # 헤더 자리(+ " (10/10)\n\n")를 남긴 만큼이 본문에 쓸 수 있는 길이
    room = limit - len(header) - 12
    pieces = []
    for block in blocks:
        if len(block) <= room:
            pieces.append(block)
            continue
        title, *lines = block.split("\n")
        cur = title
        for line in lines:
            line = line[:room - len(title) - 10]  # 한 줄이 room을 넘는 극단적 경우 대비
            if len(cur) + 1 + len(line) > room:
                pieces.append(cur)
                cur = f"{title} (계속)"
            cur += "\n" + line
        pieces.append(cur)

    messages, cur = [], ""
    for piece in pieces:
        if cur and len(cur) + 2 + len(piece) > room:
            messages.append(cur)
            cur = piece
        else:
            cur = f"{cur}\n\n{piece}" if cur else piece
    if cur:
        messages.append(cur)

    total = len(messages)
    if total == 1:
        return [f"{header}\n\n{messages[0]}"]
    return [f"{header} ({i}/{total})\n\n{m}" for i, m in enumerate(messages, 1)]


def send_discord_notification(date_str: str):
    """admin 유저의 즐겨찾기 기반 비중변화를 디스코드로 발송."""
    import httpx
    import json

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        settings = _load_discord_settings(conn)
        if not settings['enabled']:
            log.info("Discord notification disabled — skipping")
            return
        webhook_url = settings['webhook_url']
        if not webhook_url:
            log.info("Discord webhook URL not set — skipping Discord notification")
            return
        threshold = settings['threshold']

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

                if abs(diff) <= threshold:
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

        # 디스코드 메시지 발송 — 2000자 제한에 맞춰 나눠 보낸다
        messages = _split_discord_messages(f"📊 **ETF 비중 변화 알림** ({date_str})", changes_summary)

        with httpx.Client(timeout=10) as client:
            for message in messages:
                resp = client.post(webhook_url, json={"content": message})
                if resp.status_code == 429:  # rate limit — 안내된 만큼 기다렸다 한 번 재시도
                    import time as _time
                    _time.sleep(float(resp.json().get('retry_after', 1)))
                    resp = client.post(webhook_url, json={"content": message})
                resp.raise_for_status()

        log.info(f"Discord notification sent: {len(changes_summary)} ETFs with changes in {len(messages)} message(s)")

    except httpx.HTTPError as e:
        # httpx 예외 메시지엔 웹훅 주소(토큰 포함)가 들어가므로 종류·상태코드만 남긴다
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
        log.warning(f"Discord notification failed: {type(e).__name__} status={status}")
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
