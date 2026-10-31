"""
universe — ETF 유니버스(국내 주식형, 순자산 500억 이상) 규칙과 AGE의 ETF·운용사·규칙 태그

유니버스 조건·운용사 매핑·지수 태그 규칙은 순수 함수로 두고, AGE에 쓰는 함수는 커서를 받는다(커밋은 부르는 쪽).
"""

import logging
import re
from typing import Optional

from age_db import execute_cypher_batch, fetch_maps

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


def index_tag(name: str) -> Optional[str]:
    """지수 추종 ETF 이름이면 그 시장 태그(코스피·코스닥). 아니면 None."""
    for pattern, tag_name in INDEX_TAG_PATTERNS:
        if re.search(pattern, name):
            return tag_name
    return None


# ──────────────────────────────────────────────
# 유니버스 필터링
# ──────────────────────────────────────────────

LISTED_CODE_RE = re.compile(r'^[0-9][0-9A-Z]{5}$')  # KRX 상장 단축코드 (예: 005930, 0131V0)
CASH_CODES = {'010010'}  # 설정현금액


def is_listed_security_code(code: str) -> bool:
    """KRX 상장 주식/ETF 단축코드 여부 (채권·선물·현금 등 구성요소 제외용)."""
    return bool(LISTED_CODE_RE.match(code)) and code not in CASH_CODES


# 유니버스 조건: 국내 주식형 ETF, 순자산 500억 이상
# 바꾸면 챗봇 안내 문구(backend/app/domain/universe.py의 UNIVERSE_DESCRIPTION)도 같이 바꾼다
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
# AGE의 ETF 노드
# ──────────────────────────────────────────────

# 마스터에서 사라진 ETF가 이보다 많으면 마스터 파일 이상으로 보고 삭제하지 않는다
DELIST_MAX_RATIO = 0.1
DELIST_MIN_SUSPECT = 5  # 유니버스가 작아도 이만큼까지는 상장폐지로 본다


def delisted_codes(existing_codes: set[str], master: dict[str, str]) -> list[str]:
    """마스터에 없는(상장폐지) 유니버스 ETF. 너무 많이 사라졌으면 마스터 이상으로 보고 빈 목록."""
    delisted = sorted(existing_codes - master.keys())
    if delisted and len(delisted) > max(DELIST_MIN_SUSPECT, len(existing_codes) * DELIST_MAX_RATIO):
        log.warning(f"{len(delisted)}/{len(existing_codes)} universe ETFs missing from master — "
                    f"suspect a bad master file, skipping delisting: {delisted[:10]}")
        return []
    return delisted


def renamed_etfs(current: list[dict], master: dict[str, str]) -> list[dict]:
    """AGE의 {code, name} 중 마스터 이름과 다른 것 → [{code, name, old_name, company}]."""
    renamed = []
    for data in current:
        new_name = master.get(data['code'])
        if new_name and new_name != data.get('name'):
            renamed.append({'code': data['code'], 'name': new_name, 'old_name': data.get('name') or '',
                            'company': get_company_from_etf_name(new_name)})
    return renamed


def link_companies(cur, pairs: list[dict]) -> None:
    """[{code, company}]의 Company 노드를 만들고 ETF와 MANAGED_BY로 잇는다."""
    if not pairs:
        return
    execute_cypher_batch(cur, """
        MERGE (c:Company {name: item.company}) RETURN c
    """, [{'company': c} for c in sorted({p['company'] for p in pairs})])
    execute_cypher_batch(cur, """
        MATCH (e:ETF {code: item.code})
        MATCH (c:Company {name: item.company})
        MERGE (e)-[:MANAGED_BY]->(c)
        RETURN 1
    """, pairs)


def sync_universe_listing(cur, existing_codes: set[str], master: dict[str, str]) -> set[str]:
    """KIS 종목 마스터 기준으로 유니버스를 정리한다: 마스터에 없는(상장폐지) ETF는 노드째 지우고,
    이름이 바뀐 ETF는 이름(과 이름으로 정하는 운용사)을 고친다. 남은 유니버스 코드를 돌려준다.
    """
    delisted = delisted_codes(existing_codes, master)
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

    renamed = renamed_etfs(fetch_maps(cur, "MATCH (e:ETF) RETURN {code: e.code, name: e.name}"), master)
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
            link_companies(cur, moved)
        log.info("Renamed ETFs: " + ", ".join(f"{r['code']} {r['old_name']} → {r['name']}" for r in renamed))

    return existing_codes - set(delisted)


def add_new_etfs(cur, candidates: list[dict]) -> None:
    """신규 편입 ETF 노드(코드·이름)와 운용사(MANAGED_BY)를 만든다."""
    execute_cypher_batch(cur, """
        MERGE (e:ETF {code: item.code}) RETURN e
    """, [{'code': c['code']} for c in candidates])
    execute_cypher_batch(cur, """
        MATCH (e:ETF {code: item.code})
        SET e.name = item.name
        RETURN e
    """, [{'code': c['code'], 'name': c['name']} for c in candidates])
    link_companies(cur, [{'code': c['code'], 'company': get_company_from_etf_name(c['name'])} for c in candidates])


def set_etf_property(cur, prop: str, items: list[dict]) -> None:
    """[{code, value}]를 ETF 노드 속성 prop에 쓴다. prop은 코드에 적힌 고정 이름만 넘긴다(쿼리에 그대로 들어간다)."""
    execute_cypher_batch(cur, f"""
        MATCH (e:ETF {{code: item.code}})
        SET e.{prop} = item.value
        RETURN 1
    """, items)


def apply_rule_tags(cur, etfs: list[dict]) -> int:
    """신규 ETF에 지수 규칙 태그(코스피/코스닥)를 붙인다. 붙인 ETF 수를 돌려준다."""
    execute_cypher_batch(cur, """
        MERGE (t:Tag {name: item.name}) RETURN t
    """, [{'name': t} for t in RULE_ONLY_TAGS])
    tagged_pairs = [{'code': etf['code'], 'tag_name': tag}
                    for etf in etfs if (tag := index_tag(etf['name']))]
    execute_cypher_batch(cur, """
        MATCH (e:ETF {code: item.code})
        MATCH (t:Tag {name: item.tag_name})
        MERGE (e)-[:TAGGED]->(t)
        RETURN 1
    """, tagged_pairs)
    return len(tagged_pairs)


# ──────────────────────────────────────────────
# ETF 프로필 (네이버)
# ──────────────────────────────────────────────

ETF_PROFILE_FIELDS = ('expense_ratio', 'description', 'base_index', 'listed_date', 'dividend_yield', 'dividend_per_share')


def set_etf_profiles(cur, profiles: dict[str, dict]):
    """ETF 프로필 필드를 ETF 노드 속성으로 저장. 값이 없는 필드는 기존 값을 그대로 둔다."""
    for field in ETF_PROFILE_FIELDS:
        set_etf_property(cur, field, [{'code': code, 'value': p[field]}
                                      for code, p in profiles.items() if p.get(field) is not None])


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
    from naver_client import fetch_etf_profiles

    fields = ", ".join(f"{f}: e.{f}" for f in ETF_PROFILE_FIELDS)
    current = {p['code']: p for p in fetch_maps(cur, f"MATCH (e:ETF) RETURN {{code: e.code, {fields}}}")}
    changed = diff_etf_profiles(current, fetch_etf_profiles(sorted(codes)))
    set_etf_profiles(cur, changed)
    return len(changed)
