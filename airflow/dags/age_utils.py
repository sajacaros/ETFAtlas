"""
age_utils — Apache AGE + KRX 공용 유틸리티

age_sync_universe / age_tagging / embed_code_examples DAG에서 공통으로 사용하는 함수들.
"""

import logging
import re
import os
from datetime import datetime, time, timedelta
from typing import Optional

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
# 바꾸면 챗봇 안내 문구(backend/app/services/answer/universe.py의 UNIVERSE_DESCRIPTION)도 같이 바꾼다
FOREIGN_NAME_KEYWORDS = [
    '미국', '중국', '차이나', '일본', '인도', '베트남', '대만', '유럽', '독일',
    '글로벌', 'Global', 'China', 'Japan', 'India', ' US', 'USA',
    'S&P', 'NASDAQ', '나스닥', '다우존스',
    'MSCI', '선진국', '신흥국', '아시아',
    '테슬라', 'Tesla', '엔비디아', 'NVIDIA', '구글', 'Google',
    '애플', 'Apple', '아마존', 'Amazon', '팔란티어', 'Palantir',
    '브로드컴', 'Broadcom', '알리바바', 'Alibaba', '버크셔', 'Berkshire',
    '월드', 'World', '국제금', '금액티브', 'TSMC',
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


# TR(분배금 재투자형) ETF는 분배하지 않지만 KIS 분배 주기는 3(분기)으로 나온다.
# 'TRF'(타깃리스크펀드) 같은 다른 약어와 구분하려고 뒤에 영문자가 오지 않는 TR만 잡는다.
TOTAL_RETURN_PATTERN = re.compile(r'TR(?![A-Za-z])')


def resolve_dividend_cycle(name: str, cycle: Optional[int]) -> Optional[int]:
    """KIS 분배 주기(개월)를 저장값으로 정리. TR ETF는 0(분배 없음), 미제공은 None."""
    return 0 if TOTAL_RETURN_PATTERN.search(name) else cycle


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
MARKET_OPEN_TIME = time(9, 0)
MARKET_SETTLED_TIME = time(16, 0)  # 15:30 종가 확정 후 여유
# KIS 구성종목(PDF)은 영업일 08:30에 그날 공시분(직전 영업일 장 마감 후 보유)으로 갱신된다 — 갱신 뒤에 받는다
HOLDINGS_PUBLISH_TIME = time(8, 35)


def last_settled_day(now: datetime) -> str:
    """종가가 확정된 마지막 날짜(YYYYMMDD). 장 마감 전이면 전날.

    KIS 일봉은 장중에도 당일 봉(미완성)을 돌려주므로 수집 범위 끝을 여기서 자른다.
    휴장일 여부는 보지 않는다 — get_business_days가 거른다.
    """
    day = now if now.time() >= MARKET_SETTLED_TIME else now - timedelta(days=1)
    return day.strftime('%Y%m%d')


def snapshot_is_settled(now: datetime) -> bool:
    """지금 받는 현재가(NAV·순자산)가 last_settled_day의 값인지. 장중(개장~종가 확정)에는 그날 움직이는 값이다."""
    return not (MARKET_OPEN_TIME <= now.time() < MARKET_SETTLED_TIME)


def get_business_days(from_date: str, to_date: str) -> list[str]:
    """KIS 일봉(기준 ETF)으로 영업일 목록 조회. YYYYMMDD 리스트 반환."""
    kis = get_kis_client()
    if kis is None:
        return []
    # 실패를 빈 목록으로 돌려주면 "이미 최신"으로 오인하므로 예외를 그대로 올려 태스크 재시도에 맡긴다
    bars = kis.get_daily_bars(BUSINESS_DAY_REFERENCE_CODE, from_date, to_date)
    return [b.date for b in bars]


def is_market_open(day) -> bool | None:
    """개장일 여부. market_calendar 캐시 → 없으면 KIS 국내휴장일조회(1일 1회 권장) 후 저장. 모르면 None."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT is_open FROM market_calendar WHERE date = %s", (day,))
        row = cur.fetchone()
        if row is not None:
            return row[0]

        kis = get_kis_client()
        if kis is None:
            return None
        try:
            is_open = kis.is_market_open(day.strftime('%Y%m%d'))
        except Exception as e:
            log.warning(f"KIS holiday lookup failed: {e}")
            return None
        if is_open is not None:
            cur.execute(
                "INSERT INTO market_calendar (date, is_open) VALUES (%s, %s) "
                "ON CONFLICT (date) DO UPDATE SET is_open = EXCLUDED.is_open, checked_at = NOW()",
                (day, is_open),
            )
            conn.commit()
        return is_open
    finally:
        cur.close()
        conn.close()


def holdings_target_date(now: datetime) -> str | None:
    """지금 받을 구성종목의 날짜(YYYYMMDD) — 수집한 날(그날 공시된 구성). 받으면 안 되는 때면 None.

    KIS 구성종목(PDF)은 영업일 08:30에 그날 적용할 내역(직전 영업일 장 마감 후 보유)으로 갱신되고
    다음 영업일 아침까지 그대로다. 그래서 개장일 08:35 이후면 언제 받아도 같은 내역이고, 그날 날짜로 적는다.
    주말·휴장일에는 갱신이 없으므로 받지 않는다. 비교는 ETF별 이전 수집일과 하므로 날짜가 비어도 된다.
    """
    if now.time() < HOLDINGS_PUBLISH_TIME:
        return None
    is_open = is_market_open(now.date())
    if is_open is None:
        raise RuntimeError(f"Cannot tell whether {now:%Y-%m-%d} is a trading day")
    return now.strftime('%Y%m%d') if is_open else None


def get_last_collected_date() -> str | None:
    """AGE에서 마지막 수집된 Price 날짜 조회. YYYYMMDD, Price가 하나도 없으면 None.

    조회 실패를 None(빈 AGE = 첫 실행)으로 돌려주면 빠진 날짜를 건너뛰므로 예외를 그대로 올린다.
    """
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


ETF_PROFILE_FIELDS = ('expense_ratio', 'description', 'base_index', 'listed_date', 'dividend_yield', 'dividend_per_share')


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

# 마스터에서 사라진 ETF가 이보다 많으면 마스터 파일 이상으로 보고 삭제하지 않는다
DELIST_MAX_RATIO = 0.1


def sync_universe_listing(cur, existing_codes: set[str], master: dict[str, str]) -> set[str]:
    """KIS 종목 마스터 기준으로 유니버스를 정리한다: 마스터에 없는(상장폐지) ETF는 노드째 지우고,
    이름이 바뀐 ETF는 이름(과 이름으로 정하는 운용사)을 고친다. 남은 유니버스 코드를 돌려준다.
    """
    import json

    delisted = sorted(existing_codes - master.keys())
    if delisted and len(delisted) > max(5, len(existing_codes) * DELIST_MAX_RATIO):
        log.warning(f"{len(delisted)}/{len(existing_codes)} universe ETFs missing from master — "
                    f"suspect a bad master file, skipping delisting: {delisted[:10]}")
        delisted = []
    if delisted:
        items = [{'code': c} for c in delisted]
        # 가격 노드는 ETF에만 매달려 있으니 함께 지우고, 나머지 관계(HOLDS·TAGGED·WATCHES 등)는 DETACH로 끊는다
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})-[:HAS_PRICE]->(p:Price)
            DETACH DELETE p
            RETURN 1
        """, items)
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})
            DETACH DELETE e
            RETURN 1
        """, items)
        log.info(f"Removed {len(delisted)} delisted ETFs: {delisted}")

    renamed = []
    for row in execute_cypher(cur, "MATCH (e:ETF) RETURN {code: e.code, name: e.name}"):
        if not row[0]:
            continue
        data = json.loads(_parse_age_value(row[0]))
        new_name = master.get(data['code'])
        if new_name and new_name != data.get('name'):
            renamed.append({'code': data['code'], 'name': new_name, 'old_name': data.get('name') or '',
                            'company': get_company_from_etf_name(new_name)})
    if renamed:
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})
            SET e.name = item.name
            RETURN 1
        """, renamed)
        moved = [r for r in renamed if r['company'] != get_company_from_etf_name(r['old_name'])]
        if moved:
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})-[r:MANAGED_BY]->(:Company)
                DELETE r
                RETURN 1
            """, moved)
            execute_cypher_batch(cur, """
                MERGE (c:Company {name: item.company}) RETURN c
            """, [{'company': c} for c in sorted({r['company'] for r in moved})])
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                MATCH (c:Company {name: item.company})
                MERGE (e)-[:MANAGED_BY]->(c)
                RETURN 1
            """, moved)
        log.info("Renamed ETFs: " + ", ".join(f"{r['code']} {r['old_name']} → {r['name']}" for r in renamed))

    return existing_codes - set(delisted)


def collect_universe_and_prices(dates: list[str]) -> tuple[set[str], list[dict], list[str]]:
    """KIS 기반 ETF 유니버스 갱신 + ETF Price 노드 생성.

    - 목록: KIS 종목 마스터 파일(ETF 그룹) — 인증 불필요
    - 신규 편입: 이름 필터 통과 후보만 ETF 현재가(순자산)를 조회해 500억 이상이면 추가
    - 가격: 날짜별 OHLCV·거래대금은 KIS 일봉, NAV/순자산/시가총액은 ETF 현재가(최근 거래일에만)
    - 보수율·설명·기초지수·상장일: 유니버스 전체를 네이버 증권에서 조회해 바뀐 필드만 갱신
    - 분배 주기: ETF 현재가의 KIS 분배 주기(개월)를 매번 갱신, TR ETF는 0

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
        # ── 1-1. 상장폐지 ETF 제거, 이름 변경 반영 ──
        existing_codes = sync_universe_listing(cur, existing_codes, master)
        conn.commit()

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

        # ── 2-1. 프로필(보수율·설명·기초지수·상장일·분배율): 유니버스 전체 조회 후 바뀐 필드만 갱신 ──
        changed = refresh_etf_profiles(cur, existing_codes)
        conn.commit()
        log.info(f"[{latest}] ETF profile changed: {changed} ETFs")

        # ── 2-2. 분배 주기: 스냅샷의 KIS 분배 주기를 SET (이력 없음, 미제공이면 기존 값 유지) ──
        cycle_items = [{'code': c, 'value': cycle} for c in sorted(existing_codes) if c in snapshots
                       if (cycle := resolve_dividend_cycle(master[c], snapshots[c].dividend_cycle)) is not None]
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})
            SET e.dividend_cycle = item.value
            RETURN 1
        """, cycle_items)
        conn.commit()

        # ── 2-3. 구성종목 수: KIS가 주는 전체 개수 (HOLDS는 상위 30개까지만 있다) ──
        count_items = [{'code': c, 'value': snapshots[c].component_count} for c in sorted(existing_codes)
                       if c in snapshots and snapshots[c].component_count]
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})
            SET e.component_count = item.value
            RETURN 1
        """, count_items)
        conn.commit()

        # ── 2-4. 액티브 여부: KIS 분류(bstp_kor_isnm), 분류가 비면 기존 값 유지 ──
        active_items = [{'code': c, 'value': snapshots[c].active} for c in sorted(existing_codes)
                        if c in snapshots and snapshots[c].active is not None]
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})
            SET e.active = item.value
            RETURN 1
        """, active_items)
        conn.commit()

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


# 가격이 빠진 (ETF, 날짜)를 다시 받는 범위. 날짜 하나로 증분하면 일부 ETF만 실패한 날이 영구히 빈다
PRICE_REFILL_BUSINESS_DAYS = 10


def find_missing_price_dates(codes, days: list[str], existing: set[tuple[str, str]]) -> dict[str, list[str]]:
    """ETF마다 days(YYYYMMDD) 중 existing((코드, YYYYMMDD))에 없는 날짜. 빠진 날이 없는 ETF는 뺀다."""
    missing = {}
    for code in sorted(codes):
        gaps = [d for d in days if (code, d) not in existing]
        if gaps:
            missing[code] = gaps
    return missing


def refill_missing_etf_prices() -> int:
    """최근 PRICE_REFILL_BUSINESS_DAYS 영업일 중 Price가 빠진 (ETF, 날짜)를 KIS 일봉으로 채운다. 채운 개수를 돌려준다."""
    if get_kis_client() is None:
        log.warning("Skipping price refill (KIS credentials missing)")
        return 0
    end = last_settled_day(datetime.now())
    start = (datetime.strptime(end, '%Y%m%d') - timedelta(days=PRICE_REFILL_BUSINESS_DAYS * 2)).strftime('%Y%m%d')
    return fill_missing_etf_prices(get_business_days(start, end)[-PRICE_REFILL_BUSINESS_DAYS:])


def backfill_price_days(calendar_days: int) -> list[str]:
    """지난 calendar_days일의 영업일 중 최근 PRICE_REFILL_BUSINESS_DAYS 영업일을 뺀 날들 (YYYYMMDD).

    최근 영업일은 정기 수집(age_sync_universe)이 쓰는 범위라, 백필과 겹쳐 같은 날 Price가 둘 생기지 않게 뺀다.
    """
    end = last_settled_day(datetime.now())
    start = (datetime.strptime(end, '%Y%m%d') - timedelta(days=calendar_days)).strftime('%Y%m%d')
    return get_business_days(start, end)[:-PRICE_REFILL_BUSINESS_DAYS]


def fill_missing_etf_prices(days: list[str]) -> int:
    """days(YYYYMMDD) 중 Price가 빠진 (ETF, 날짜)를 KIS 일봉으로 채운다. 채운 개수를 돌려준다.

    빠진 날만 새로 만들고 이미 있는 Price는 건드리지 않는다. NAV·순자산·시가총액은 현재가 API라
    날짜 지정이 안 되므로 채운 날에는 비워 둔다. 상장 전이거나 거래정지인 날은 KIS가 봉을 주지 않아 빈 채로 남는다.
    """
    kis = get_kis_client()
    if kis is None:
        log.warning("Skipping price fill (KIS credentials missing)")
        return 0
    if not days:
        return 0

    conn = get_db_connection()
    cur = init_age(conn)
    try:
        codes = get_etf_codes_from_age()
        existing = set()
        results = execute_cypher(cur, """
            MATCH (e:ETF)-[:HAS_PRICE]->(p:Price)
            WHERE p.date >= $from_date AND p.date <= $to_date
            RETURN e.code + '|' + p.date
        """, {'from_date': _dash_date(days[0]), 'to_date': _dash_date(days[-1])})
        for row in results:
            key = _parse_age_value(row[0]) if row[0] else ''
            if '|' in key:
                code, date_str = key.split('|', 1)
                existing.add((code, date_str.replace('-', '')))

        missing = find_missing_price_dates(codes, days, existing)
        log.info(f"Price refill: {len(missing)}/{len(codes)} ETFs miss prices in {days[0]}~{days[-1]}")

        items = []
        for code, gaps in missing.items():
            try:
                bars = kis.get_daily_bars(code, gaps[0], gaps[-1])
            except Exception as e:
                log.warning(f"Failed ETF daily bars for refill {code}: {e}")
                continue
            items.extend({
                'code': code, 'date': _dash_date(bar.date),
                'open': bar.open, 'high': bar.high, 'low': bar.low, 'close': bar.close,
                'volume': bar.volume, 'trade_value': bar.trade_value,
            } for bar in bars if bar.date in gaps)

        if items:
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                OPTIONAL MATCH (e)-[:HAS_PRICE]->(existing:Price {date: item.date})
                WITH e, existing, item WHERE existing IS NULL
                CREATE (e)-[:HAS_PRICE]->(:Price {date: item.date, open: item.open, high: item.high,
                    low: item.low, close: item.close, volume: item.volume, trade_value: item.trade_value})
                RETURN e
            """, items)
            conn.commit()
        filled = sorted({it['code'] for it in items})
        log.info(f"Price refill: filled {len(items)} prices for {len(filled)} ETFs {filled}")
        return len(items)
    finally:
        cur.close()
        conn.close()


def refresh_latest_snapshot_values() -> int:
    """마지막 수집일 Price의 NAV·순자산·시가총액을 지금 받은 현재가로 다시 쓴다. 고친 개수를 돌려준다.

    장 마감 뒤 실행이 그날 Price를 만들면 다음 날 아침 실행은 새 날짜가 없어 현재가를 받지 않으므로
    NAV·순자산이 장 마감 직후 값으로 남는다. 새 날짜가 없는 실행이 이 함수로 마지막 수집일 값을 다시 쓴다.
    장중에는 현재가가 그날 값이라 쓰지 않는다(snapshot_is_settled).
    """
    if not snapshot_is_settled(datetime.now()):
        log.info("Skipping snapshot refresh during market hours")
        return 0
    kis = get_kis_client()
    if kis is None:
        log.warning("Skipping snapshot refresh (KIS credentials missing)")
        return 0
    last = get_last_collected_date()
    if not last:
        return 0

    items = []
    for code in sorted(get_etf_codes_from_age()):
        try:
            snap = kis.get_etf_snapshot(code)
        except Exception as e:
            log.warning(f"Failed ETF snapshot for refresh {code}: {e}")
            continue
        items.append({'code': code, 'date': _dash_date(last), 'nav': snap.nav,
                      'net_assets': snap.net_assets, 'listed_shares': snap.listed_shares})

    conn = get_db_connection()
    cur = init_age(conn)
    try:
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})-[:HAS_PRICE]->(p:Price {date: item.date})
            SET p.nav = item.nav, p.net_assets = item.net_assets,
                p.market_cap = p.close * item.listed_shares
            RETURN p
        """, items)
        valid_na = [it for it in items if it['net_assets']]
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})
            SET e.net_assets = item.net_assets
            RETURN e
        """, valid_na)
        conn.commit()
        log.info(f"Snapshot refresh: {len(items)} ETFs on {last}")
        return len(items)
    finally:
        cur.close()
        conn.close()


def _dash_date(d: str) -> str:
    """YYYYMMDD → YYYY-MM-DD (Price.date 형식)."""
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


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


# KIS가 통째로 응답하지 않을 때 ETF마다 타임아웃을 기다리지 않도록, 연속으로 이만큼 실패하면 중단한다
HOLDINGS_MAX_CONSECUTIVE_FAILURES = 10


def collect_holdings(etf_codes: list[str], bd: str) -> list[str]:
    """KIS ETF 구성종목시세로 현재 구성종목을 조회해 bd(YYYYMMDD) 날짜의 HOLDS 엣지로 저장.

    KIS API는 날짜 지정이 불가능(호출 시점 스냅샷)하므로 과거 날짜 백필은 지원하지 않는다.
    bd에는 최근 거래일을 넘긴다. Stock 노드(이름/is_etf 포함)도 함께 생성.
    받은 것은 저장하고, 끝내 HOLDS를 못 쓴 ETF 코드를 돌려준다 — 재실행하면 이미 받은 ETF는 건너뛰고
    이 ETF들만 다시 받는다. 재시도할지는 호출 쪽(태스크)이 정한다.
    """
    from itertools import groupby

    if not etf_codes or not bd:
        return []

    kis = get_kis_client()
    if kis is None:
        raise RuntimeError("KIS credentials missing — cannot collect holdings")

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
        return []
    if existing_holds:
        log.info(f"[{bd}] Skipping {len(existing_holds)} ETFs with existing HOLDS, "
                 f"fetching {len(remaining_etfs)}")

    all_holds = []
    stock_names = {}  # stock_code -> KIS 종목명
    failed_codes = []
    consecutive = 0

    for idx, ticker in enumerate(remaining_etfs):
        if consecutive >= HOLDINGS_MAX_CONSECUTIVE_FAILURES:
            log.warning(f"[{bd}] {consecutive} consecutive KIS failures — aborting, "
                        f"{len(remaining_etfs) - idx} ETFs not attempted")
            failed_codes.extend(remaining_etfs[idx:])
            break
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
            consecutive = 0
        except Exception as e:
            failed_codes.append(ticker)
            consecutive += 1
            log.warning(f"Failed KIS components for {ticker}: {e}")

    if failed_codes:
        log.warning(f"[{bd}] KIS component fetch failed for {len(failed_codes)}/{len(remaining_etfs)} ETFs")
    if not all_holds:
        log.warning(f"[{bd}] No holdings data from KIS.")
        refresh_current_holds(date_str)
        return failed_codes

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
                failed_codes.extend(code for code, _ in batch_groups)
                conn.rollback()
                cur = init_age(conn)

        log.info(f"[{bd}] {len(all_holds)} HOLDS edges "
                 f"({len(all_stock_codes)} stocks)")

    finally:
        cur.close()
        conn.close()

    refresh_current_holds(date_str)
    return failed_codes


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


DISCORD_MAX_CONTENT = 2000  # 디스코드 메시지 content 최대 길이


AI_ENV_DEFAULTS = {
    'llm_api_base': ('LLM_API_BASE', 'http://localhost:4000'),
    'llm_api_key': ('LLM_API_KEY', ''),
    'llm_model': ('LLM_MODEL', 'qwen38-27b'),
    'embedding_api_base': ('EMBEDDING_API_BASE', 'http://localhost:4000'),
    'embedding_api_key': ('EMBEDDING_API_KEY', ''),
    'embedding_model': ('EMBEDDING_MODEL', 'embedding-gemma-300m'),
}


def load_ai_config(conn) -> dict:
    """LLM/임베딩 접속 설정. 웹(관리자 페이지)에서 저장한 ai_settings가 우선,
    저장 전이거나 비어 있는 항목은 환경변수를 쓴다. API 키는 암호문이라 복호화한다."""
    # backend 암호화 유틸 (컨테이너 PYTHONPATH=/opt/backend)
    from app.utils.encryption import decrypt_value

    config = {name: os.environ.get(env, default) for name, (env, default) in AI_ENV_DEFAULTS.items()}
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT {', '.join(AI_ENV_DEFAULTS)} FROM ai_settings WHERE id = 1")
        row = cur.fetchone()
    finally:
        cur.close()
    for name, value in zip(AI_ENV_DEFAULTS, row or ()):
        if not value:
            continue
        if name.endswith('_api_key'):
            try:
                value = decrypt_value(value)
            except Exception:
                log.warning("Failed to decrypt ai_settings.%s; using environment", name)
                continue
        config[name] = value
    return config


def _load_discord_settings(conn) -> dict:
    """디스코드 알림 설정. 웹(관리자 페이지)에서 저장한 discord_settings가 우선,
    저장 전이거나 주소가 비었으면 환경변수 DISCORD_WEBHOOK_URL을 쓴다."""
    settings = {'enabled': True, 'webhook_url': None, 'threshold': 3.0, 'added_threshold': 2.0, 'rise_threshold': 3.0}
    cur = conn.cursor()
    try:
        cur.execute("SELECT enabled, webhook_url, threshold, added_threshold, rise_threshold "
                    "FROM discord_settings WHERE id = 1")
        row = cur.fetchone()
    finally:
        cur.close()
    if row:
        settings.update(enabled=row[0], webhook_url=row[1], threshold=row[2],
                        added_threshold=row[3], rise_threshold=row[4])
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


CHANGE_TYPE_LABELS = {'added': '신규편입', 'removed': '편출', 'increased': '증가', 'decreased': '감소'}


def _record_discord_notification(conn, date_str: str, threshold: float, items,
                                 message_count: int, error: str | None = None, kind: str = 'weight_change'):
    """디스코드로 보낸(또는 보내다 실패한) 알림을 discord_notification_logs에 남긴다."""
    import json

    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO discord_notification_logs "
            "(kind, base_date, status, threshold, items, message_count, error, sent_at) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, now() AT TIME ZONE 'utc')",
            (kind, date_str, 'failed' if error else 'sent', threshold,
             json.dumps(items, ensure_ascii=False), message_count, error),
        )
        conn.commit()
    finally:
        cur.close()


def _weight_change_type(prev: Optional[dict], curr: Optional[dict], diff: float) -> str:
    if curr and not prev:
        return 'added'
    if prev and not curr:
        return 'removed'
    return 'increased' if diff > 0 else 'decreased'


def compute_weight_changes():
    """액티브 ETF의 이전 수집일(공시일) 대비 보유종목 비중 변화를 계산해 weight_changes에 저장.

    weight_change_dates에 없는(아직 계산하지 않은) HOLDS 날짜를 모두 처리하므로 첫 실행이면 과거 전체를 채운다.
    가장 최근 날짜는 이미 계산했어도 다시 계산한다 — KIS는 과거 구성종목을 주지 않으므로 나중에 HOLDS가
    채워질 수 있는 날(수집 재시도로 빠진 ETF를 채운 경우)은 가장 최근 날짜뿐이다.
    변화가 있는 종목은 크기와 상관없이 모두 저장하고, 기준값은 읽는 쪽(웹·디스코드)이 적용한다.
    이전 HOLDS가 없는 ETF(유니버스 신규 편입 첫날 등)는 비교하지 않는다.
    """
    import json
    from collections import defaultdict

    conn = get_db_connection()
    cur = init_age(conn)
    rdb_cur = conn.cursor()
    try:
        date_rows = execute_cypher(cur, """
            MATCH (e:ETF)-[h:HOLDS]->(:Stock)
            WHERE e.active = true
            WITH DISTINCT h.date as d
            RETURN {date: d}
        """)
        all_dates = sorted(json.loads(_parse_age_value(r[0]))['date'] for r in date_rows if r[0])
        rdb_cur.execute("SELECT base_date FROM weight_change_dates")
        done = {r[0] for r in rdb_cur.fetchall()}
        pending = [d for d in all_dates if d not in done or d == all_dates[-1]]
        if not pending:
            log.info("No HOLDS dates for active ETFs")
            return
        since = pending[0]

        holdings = defaultdict(lambda: defaultdict(dict))  # etf_code -> date -> stock_code -> {name, weight}
        etf_names = {}

        def add_rows(rows):
            for row in rows:
                if not row[0]:
                    continue
                data = json.loads(_parse_age_value(row[0]))
                etf_names[data['etf_code']] = data.get('etf_name') or data['etf_code']
                holdings[data['etf_code']][data['date']][data['stock_code']] = {
                    'name': data.get('stock_name') or data['stock_code'],
                    'weight': float(data['weight']) if data.get('weight') else 0,
                }

        add_rows(execute_cypher(cur, """
            MATCH (e:ETF)-[h:HOLDS]->(s:Stock)
            WHERE e.active = true AND h.date >= $since
            RETURN {etf_code: e.code, etf_name: e.name, date: h.date,
                    stock_code: s.code, stock_name: s.name, weight: h.weight}
        """, {'since': since}))
        # 첫 계산일의 비교 대상: ETF별로 그 이전의 마지막 HOLDS (며칠 빠졌던 ETF도 이전 데이터와 비교한다)
        prev_dates = []
        for row in execute_cypher(cur, """
            MATCH (e:ETF)-[h:HOLDS]->(:Stock)
            WHERE e.active = true AND h.date < $since
            WITH e.code as code, max(h.date) as d
            RETURN {etf_code: code, date: d}
        """, {'since': since}):
            if row[0]:
                prev_dates.append(json.loads(_parse_age_value(row[0])))
        add_rows(execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.etf_code})-[h:HOLDS {date: item.date}]->(s:Stock)
            RETURN {etf_code: e.code, etf_name: e.name, date: h.date,
                    stock_code: s.code, stock_name: s.name, weight: h.weight}
        """, prev_dates))

        for base_date in pending:
            rows = []
            for etf_code, by_date in holdings.items():
                today_h = by_date.get(base_date)
                prev_dates = [d for d in by_date if d < base_date]
                if not today_h or not prev_dates:
                    continue
                prev_date = max(prev_dates)
                prev_h = by_date[prev_date]
                for code in set(today_h) | set(prev_h):
                    curr, prev = today_h.get(code), prev_h.get(code)
                    cw = curr['weight'] if curr else 0
                    pw = prev['weight'] if prev else 0
                    diff = round(cw - pw, 4)
                    if diff == 0:
                        continue
                    rows.append((base_date, prev_date, etf_code, etf_names[etf_code], code, (curr or prev)['name'],
                                 _weight_change_type(prev, curr, diff), pw, cw, diff))

            rdb_cur.execute("DELETE FROM weight_changes WHERE base_date = %s", (base_date,))
            if rows:
                rdb_cur.executemany(
                    "INSERT INTO weight_changes (base_date, prev_date, etf_code, etf_name, stock_code, stock_name, "
                    "change_type, previous_weight, current_weight, weight_change) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    rows,
                )
            rdb_cur.execute(
                "INSERT INTO weight_change_dates (base_date, computed_at) VALUES (%s, now() AT TIME ZONE 'utc') "
                "ON CONFLICT (base_date) DO UPDATE SET computed_at = EXCLUDED.computed_at",
                (base_date,),
            )
            conn.commit()
            log.info(f"Weight changes {base_date}: {len(rows)} rows")
    finally:
        rdb_cur.close()
        cur.close()
        conn.close()


def _post_discord_messages(webhook_url: str, messages: list[str]) -> str | None:
    """메시지들을 차례로 보낸다. 실패하면 오류 설명을 돌려준다(성공이면 None).

    httpx 예외 메시지엔 웹훅 주소(토큰 포함)가 들어가므로 종류·상태코드만 남긴다.
    """
    import httpx

    try:
        with httpx.Client(timeout=10) as client:
            for message in messages:
                resp = client.post(webhook_url, json={"content": message})
                if resp.status_code == 429:  # rate limit — 안내된 만큼 기다렸다 한 번 재시도
                    import time as _time
                    _time.sleep(float(resp.json().get('retry_after', 1)))
                    resp = client.post(webhook_url, json={"content": message})
                resp.raise_for_status()
    except httpx.HTTPError as e:
        status = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else None
        return f"{type(e).__name__} status={status}"
    return None


def send_discord_notification(date_str: str):
    """weight_changes에 저장된 액티브 ETF 비중변화 중 기준값을 넘는 것을 디스코드로 발송.

    이미 보낸 날짜(발송 이력에 성공 기록)면 건너뛴다. 발송에 실패하면 이력에 남기고 예외를 올려
    Airflow 재시도가 다시 보내게 한다.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        settings = _load_discord_settings(conn)
        if not settings['enabled']:
            log.info("Discord notification disabled — skipping")
            return
        webhook_url = settings['webhook_url']
        if not webhook_url:
            log.info("Discord webhook URL not set — skipping Discord notification")
            return
        threshold, added_threshold = settings['threshold'], settings['added_threshold']

        cur.execute("SELECT 1 FROM discord_notification_logs "
                    "WHERE kind = 'weight_change' AND base_date = %s AND status = 'sent' LIMIT 1",
                    (date_str,))
        if cur.fetchone():
            log.info(f"Discord notification for {date_str} already sent — skipping")
            return

        cur.execute(
            "SELECT etf_code, etf_name, prev_date, stock_code, stock_name, change_type, "
            "previous_weight, current_weight, weight_change "
            "FROM weight_changes WHERE base_date = %s "
            "AND abs(weight_change) > CASE WHEN change_type = 'added' THEN %s ELSE %s END "
            "ORDER BY abs(weight_change) DESC",
            (date_str, added_threshold, threshold),
        )
        # ETF는 가장 큰 변화가 큰 순, 종목은 변화량 큰 순
        items, by_etf = [], {}
        for etf_code, etf_name, prev_date, stock_code, stock_name, ct, pw, cw, diff in cur.fetchall():
            if etf_code not in by_etf:
                by_etf[etf_code] = {'etf_code': etf_code, 'etf_name': etf_name, 'prev_date': prev_date, 'changes': []}
                items.append(by_etf[etf_code])
            by_etf[etf_code]['changes'].append({
                'stock_code': stock_code,
                'stock_name': stock_name,
                'change_type': ct,
                'previous_weight': pw,
                'current_weight': cw,
                'weight_change': diff,
            })

        if not items:
            log.info("No significant changes — skipping Discord notification")
            return

        changes_summary = [
            f"**{item['etf_name']}** ({item['etf_code']})\n" + "\n".join(
                f"  {CHANGE_TYPE_LABELS[c['change_type']]} {c['stock_name']}: "
                f"{c['previous_weight']:.1f}% → {c['current_weight']:.1f}% ({c['weight_change']:+.1f}%p)"
                for c in item['changes']
            )
            for item in items
        ]

        # 디스코드 메시지 발송 — 2000자 제한에 맞춰 나눠 보낸다
        # 날짜는 구성종목 공시일 — 실제 매매는 직전 영업일 장중에 일어난 것
        messages = _split_discord_messages(f"📊 **ETF 비중 변화 알림** ({date_str} 공시)", changes_summary)

        error = _post_discord_messages(webhook_url, messages)
        if error:
            _record_discord_notification(conn, date_str, threshold, items, len(messages), error)
            # 예외 체인에도 웹훅 주소가 남지 않게 새 예외로 올린다
            raise RuntimeError(f"Discord notification failed: {error}")

        _record_discord_notification(conn, date_str, threshold, items, len(messages))
        log.info(f"Discord notification sent: {len(items)} ETFs with changes in {len(messages)} message(s)")
    finally:
        cur.close()
        conn.close()


# 일일 리포트: 목록에 보일 상승 ETF 수, 특징 요약에 넘길 최대 ETF 수, 상승 ETF마다 넘길 구성종목 수
REPORT_TOP_RISING = 10
REPORT_LLM_MAX_ETFS = 100
REPORT_TOP_HOLDINGS = 5


def daily_return(prices: list[tuple[str, float]], date_str: str) -> float | None:
    """(날짜, 종가) 목록에서 date_str(YYYY-MM-DD) 종가의 직전 거래일 대비 수익률(%). 그날 가격이나 직전 가격이 없으면 None."""
    by_date = dict(prices)
    close = by_date.get(date_str)
    prev = [d for d in by_date if d < date_str]
    if not close or not prev:
        return None
    prev_close = by_date[max(prev)]
    if not prev_close:
        return None
    return round((close - prev_close) / prev_close * 100, 2)


def find_rising_etfs(prices: dict[str, list[tuple[str, float]]], names: dict[str, str],
                     date_str: str, threshold: float) -> list[dict]:
    """ETF별 (날짜, 종가)로 date_str 1일 수익률이 threshold(%) 이상인 ETF. 많이 오른 순."""
    rising = []
    for code, rows in prices.items():
        ret = daily_return(rows, date_str)
        if ret is not None and ret >= threshold:
            rising.append({'etf_code': code, 'etf_name': names.get(code) or code, 'return_1d': ret})
    rising.sort(key=lambda r: r['return_1d'], reverse=True)
    return rising


def _price_rows(rows) -> dict[str, list[tuple[str, float]]]:
    """{code, date, close} agtype 행 → code별 (날짜, 종가) 목록."""
    import json
    from collections import defaultdict

    out = defaultdict(list)
    for row in rows:
        if not row[0]:
            continue
        data = json.loads(_parse_age_value(row[0]))
        if data.get('date') and data.get('close') is not None:
            out[data['code']].append((data['date'], float(data['close'])))
    return out


def collect_daily_report(date_str: str, rise_threshold: float) -> dict:
    """date_str(YYYY-MM-DD)에 rise_threshold(%) 이상 오른 ETF(상위 구성종목·등락 포함)와 시장(KODEX 200) 수익률."""
    import json

    since = (datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=14)).strftime('%Y-%m-%d')
    conn = get_db_connection()
    cur = init_age(conn)
    try:
        names = {}
        for row in execute_cypher(cur, "MATCH (e:ETF) RETURN {code: e.code, name: e.name}"):
            if row[0]:
                data = json.loads(_parse_age_value(row[0]))
                names[data['code']] = data.get('name')

        etf_prices = _price_rows(execute_cypher(cur, """
            MATCH (e:ETF)-[:HAS_PRICE]->(p:Price)
            WHERE p.date >= $from_date AND p.date <= $to_date
            RETURN {code: e.code, date: p.date, close: p.close}
        """, {'from_date': since, 'to_date': date_str}))

        rising = find_rising_etfs(etf_prices, names, date_str, rise_threshold)
        for etf in rising:
            holdings, stock_prices = {}, {}
            for row in execute_cypher(cur, """
                MATCH (e:ETF {code: $code})-[h:CURRENT_HOLDS]->(s:Stock)
                OPTIONAL MATCH (s)-[:HAS_PRICE]->(p:Price)
                WHERE p.date >= $from_date AND p.date <= $to_date
                RETURN {code: s.code, name: s.name, weight: h.weight, date: p.date, close: p.close}
            """, {'code': etf['etf_code'], 'from_date': since, 'to_date': date_str}):
                if not row[0]:
                    continue
                data = json.loads(_parse_age_value(row[0]))
                holdings[data['code']] = {'stock_name': data.get('name') or data['code'],
                                          'weight': data.get('weight') or 0}
                if data.get('date') and data.get('close') is not None:
                    stock_prices.setdefault(data['code'], []).append((data['date'], float(data['close'])))
            top = sorted(holdings.items(), key=lambda kv: kv[1]['weight'], reverse=True)[:REPORT_TOP_HOLDINGS]
            etf['holdings'] = [{'stock_code': code, **h, 'return_1d': daily_return(stock_prices.get(code, []), date_str)}
                               for code, h in top]
    finally:
        cur.close()
        conn.close()

    market_return = daily_return(etf_prices.get(BUSINESS_DAY_REFERENCE_CODE, []), date_str)
    return {'rising': rising, 'market_return': market_return}


def summarize_rising_etfs(rising: list[dict], market_return: float | None) -> list[str]:
    """상승 ETF 전체와 시장 수익률(KODEX 200)을 보고 오늘 장만의 특징을 LLM으로 몇 줄 정리한다.

    LLM 설정이 없거나 호출이 실패하면 빈 목록 — 리포트는 특징 없이도 보낸다.
    """
    from openai import OpenAI
    from pydantic import BaseModel

    if not rising:
        return []
    conn = get_db_connection()
    try:
        ai = load_ai_config(conn)
    finally:
        conn.close()
    if not ai['llm_api_key']:
        log.warning("LLM API key not set (admin page or LLM_API_KEY), skipping daily features")
        return []

    class DailyFeatures(BaseModel):
        features: list[str]

    system_prompt = """한국 ETF 시장 분석가입니다.
그날 시장 수익률(KODEX 200)과 많이 오른 ETF 목록(이름, 1일 수익률, 비중 상위 구성종목의 비중·1일 수익률)을 받습니다.
오늘 장에서만 볼 수 있는 특징을 1~3개 항목으로 정리합니다.

규칙:
- 시장보다 뚜렷하게 더 오른 테마 묶음, 그 묶음을 끌어올린 종목, 혼자 크게 튄 종목·ETF를 쓴다
- 시장만큼 오른 ETF(지수 추종, 시가총액 상위 종목 위주 ETF)는 쓰지 않는다. 대형주 비중이 커서 함께 올랐다는 식의 구조 설명도 쓰지 않는다
- 비슷한 ETF는 하나로 묶고 개별 ETF를 하나씩 나열하지 않는다
- 항목끼리 같은 내용을 되풀이하지 않는다. 쓸 만한 특징이 하나뿐이면 하나만 쓴다
- 주어진 숫자만 쓴다. 지수 내 비중처럼 주어지지 않은 숫자를 만들지 않고, 뉴스·실적·정책 같은 상승 원인도 추측하지 않는다
- 항목마다 한 문장, "~했다" 체로 쓴다"""

    def describe(etf: dict) -> str:
        parts = [f"{h['stock_name']} {h['weight']:.1f}%"
                 + (f" {h['return_1d']:+.2f}%" if h['return_1d'] is not None else "")
                 for h in etf.get('holdings', [])]
        return f"- {etf['etf_name']} {etf['return_1d']:+.2f}%: " + ", ".join(parts)

    shown = rising[:REPORT_LLM_MAX_ETFS]
    user = [f"시장(KODEX 200) {market_return:+.2f}%" if market_return is not None else "시장 수익률 없음",
            f"상승 ETF {len(rising)}개" + (f" (많이 오른 {len(shown)}개만)" if len(shown) < len(rising) else "")]
    user += [describe(e) for e in shown]

    client = OpenAI(base_url=ai['llm_api_base'], api_key=ai['llm_api_key'], timeout=120)
    try:
        completion = client.chat.completions.parse(
            model=ai['llm_model'],
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "\n".join(user)},
            ],
            response_format=DailyFeatures,
            temperature=0.3,
            max_tokens=2048,
            # 숫자를 묶어 옮기는 짧은 글이라 추론을 끈다 — 켜 두면 추론만으로 토큰 한도를 넘긴다
            extra_body={'chat_template_kwargs': {'enable_thinking': False}},
        )
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise ValueError("LLM returned no parsable result")
    except Exception as e:
        log.warning(f"Daily features failed: {e}")
        return []
    features = [f.strip() for f in parsed.features if f.strip()]
    log.info(f"Daily features: {len(features)} items from {len(rising)} rising ETFs")
    return features


def format_daily_report(date_str: str, report: dict, threshold: float, new_etfs: list[dict]) -> tuple[str, list[str]]:
    """일일 리포트 → (디스코드 헤더, 블록들). 블록은 _split_discord_messages가 2,000자에 맞춰 묶는다."""
    blocks = []
    if new_etfs:
        blocks.append("신규 편입: " + ", ".join(f"{e['name']}({e['code']})" for e in new_etfs))

    rising = report['rising']
    if not rising:
        blocks.append(f"1일 {threshold:+.1f}% 이상 오른 ETF가 없습니다.")
        return f"📈 **ETF 일일 리포트** ({date_str})", blocks
    if report.get('features'):
        blocks.append("**오늘의 특징**\n" + "\n".join(f"• {f}" for f in report['features']))
    top = rising[:REPORT_TOP_RISING]
    title = f"**상승 ETF** (1일 {threshold:+.1f}% 이상 {len(rising)}개"
    title += f" 중 상위 {len(top)}개)" if len(top) < len(rising) else ")"
    blocks.append(title + "\n" + "\n".join(
        f"{i}. {etf['etf_name']} ({etf['etf_code']}) {etf['return_1d']:+.2f}%" for i, etf in enumerate(top, 1)))
    return f"📈 **ETF 일일 리포트** ({date_str})", blocks


def send_daily_report(date_str: str, new_etfs: list[dict] | None = None):
    """date_str(YYYY-MM-DD) 오늘의 특징과 상승 ETF를 디스코드로 보낸다. 알림이 꺼져 있거나 이미 보낸 날짜면 건너뛴다.

    발송에 실패하면 이력에 남기고 예외를 올려 Airflow 재시도가 다시 보내게 한다.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        settings = _load_discord_settings(conn)
        if not settings['enabled']:
            log.info("Discord notification disabled — skipping daily report")
            return
        webhook_url = settings['webhook_url']
        if not webhook_url:
            log.info("Discord webhook URL not set — skipping daily report")
            return
        cur.execute("SELECT 1 FROM discord_notification_logs "
                    "WHERE kind = 'daily_report' AND base_date = %s AND status = 'sent' LIMIT 1",
                    (date_str,))
        if cur.fetchone():
            log.info(f"Daily report for {date_str} already sent — skipping")
            return
    finally:
        cur.close()
        conn.close()

    threshold = settings['rise_threshold']
    report = collect_daily_report(date_str, threshold)
    report['features'] = summarize_rising_etfs(report['rising'], report['market_return'])
    header, blocks = format_daily_report(date_str, report, threshold, new_etfs or [])
    messages = _split_discord_messages(header, blocks)

    error = _post_discord_messages(webhook_url, messages)
    conn = get_db_connection()
    try:
        _record_discord_notification(conn, date_str, threshold, report, len(messages), error, kind='daily_report')
    finally:
        conn.close()
    if error:
        raise RuntimeError(f"Discord daily report failed: {error}")
    log.info(f"Daily report sent: {len(report['rising'])} rising ETFs in {len(messages)} message(s)")


# 수익률 계산에 읽는 기간 (1개월 수익률 + 휴장일 여유)
RETURNS_LOOKBACK_DAYS = 70


def update_etf_returns():
    """ETF 1D/1W/1M 수익률 계산 및 저장."""
    import json
    from collections import defaultdict
    from datetime import datetime, timedelta

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # 전체 ETF의 최근 45일 가격을 한 번에 조회 (백필한 1년치를 다 읽지 않게 날짜로 먼저 자른다)
        since = (datetime.now() - timedelta(days=RETURNS_LOOKBACK_DAYS)).strftime('%Y-%m-%d')
        rows = execute_cypher(cur, """
            MATCH (e:ETF)-[:HAS_PRICE]->(p:Price)
            WHERE p.date >= $since
            WITH e.code AS code, p.date AS date, p.close AS close, p.market_cap AS market_cap
            ORDER BY date DESC
            RETURN {code: code, date: date, close: close, market_cap: market_cap}
        """, {'since': since})

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
