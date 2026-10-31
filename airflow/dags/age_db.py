"""
age_db — Apache AGE 연결과 Cypher 실행

값은 backend의 app.utils.cypher(literal·bind)로 끼워 넣는다 — backend와 같은 이스케이프 규칙을 쓴다.
"""

import json
import logging
import re
from contextlib import contextmanager
from typing import Optional

from app.utils.cypher import bind

from rdb import get_db_connection

log = logging.getLogger(__name__)

GRAPH_NAME = 'etf_graph'
# AGE에 쓰는 태스크를 하나씩 돌리는 Airflow pool(슬롯 1). 같은 (코드, 날짜) Price가 동시에 둘 생기지 않게 한다.
# 코드 밖 설정이다 — 만드는 법은 docs/dags.md. 없으면 이 pool을 쓰는 태스크가 스케줄되지 않는다
AGE_WRITE_POOL = 'age_write'
CYPHER_BATCH_SIZE = 100
_AGE_SUFFIX_RE = re.compile(r'::(?:numeric|integer|float|vertex|edge|path|text|boolean)\b')


def init_age(conn):
    """Initialize Apache AGE for the connection"""
    cur = conn.cursor()
    cur.execute("LOAD 'age';")
    cur.execute("SET search_path = ag_catalog, '$user', public;")
    conn.commit()
    return cur


@contextmanager
def age_cursor():
    """with age_cursor() as (conn, cur): — AGE를 켠 연결과 커서. 나올 때 닫는다. 커밋은 부르는 쪽이 한다."""
    conn = get_db_connection()
    cur = init_age(conn)
    try:
        yield conn, cur
    finally:
        cur.close()
        conn.close()


@contextmanager
def _reuse_or_open(cur):
    """받은 커서가 있으면 그대로, 없으면 새 연결을 열고 닫는다 — 조회 헬퍼가 연결을 함부로 늘리지 않게."""
    if cur is not None:
        yield cur
        return
    with age_cursor() as (_, own):
        yield own


def execute_cypher(cur, cypher_query, params=None):
    """Execute Cypher query via Apache AGE. params의 $이름 자리는 한 번에 리터럴로 치환한다."""
    sql = f"""
        SELECT * FROM cypher('{GRAPH_NAME}', $$
            {bind(cypher_query, params)}
        $$) as (result agtype);
    """
    cur.execute(sql)
    return cur.fetchall()


def execute_cypher_batch(cur, cypher_template: str, items: list[dict],
                         batch_size: int = CYPHER_BATCH_SIZE, params: Optional[dict] = None):
    """UNWIND + cypher_template로 배치 실행.

    template에서 'item' 변수를 사용. params가 있으면 template의 $이름도 함께 치환한다.
    예: MERGE (e:ETF {code: item.code}) RETURN e
    """
    if not items:
        return []

    all_results = []
    for i in range(0, len(items), batch_size):
        # 목록도 파라미터로 넘긴다 — 미리 끼워 넣으면 값 안의 $이름이 다시 치환될 수 있다
        query = f"UNWIND $_batch AS item\n{cypher_template}"
        all_results.extend(execute_cypher(cur, query, {**(params or {}), '_batch': items[i:i + batch_size]}))
    return all_results


def parse_age_value(raw):
    """AGE agtype 문자열에서 타입 접미사 제거"""
    return _AGE_SUFFIX_RE.sub('', str(raw)).strip('"')


def fetch_values(cur, cypher_query, params=None) -> list[str]:
    """값 하나를 돌려주는 쿼리의 결과 (빈 값은 뺀다)."""
    values = []
    for row in execute_cypher(cur, cypher_query, params):
        if row[0]:
            value = parse_age_value(row[0])
            if value:
                values.append(value)
    return values


def rows_to_maps(rows) -> list[dict]:
    """맵 {..}을 돌려준 cypher 결과 행 → dict 목록."""
    return [json.loads(parse_age_value(row[0])) for row in rows if row[0]]


def fetch_maps(cur, cypher_query, params=None) -> list[dict]:
    """맵 {..}을 돌려주는 쿼리의 결과."""
    return rows_to_maps(execute_cypher(cur, cypher_query, params))


# ──────────────────────────────────────────────
# AGE 공용 조회 — cur를 넘기면 그 연결을 쓰고, 없으면 새로 연다
# ──────────────────────────────────────────────

def get_etf_codes_from_age(cur=None) -> set[str]:
    """AGE에서 ETF 유니버스 코드 조회."""
    with _reuse_or_open(cur) as c:
        return set(fetch_values(c, "MATCH (e:ETF) RETURN e.code"))


def get_stock_codes_from_age(cur=None, *, exclude_etfs: bool = False) -> set[str]:
    """AGE에서 Stock 코드 집합 조회. exclude_etfs면 is_etf=false인 종목만."""
    where = " WHERE s.is_etf = false" if exclude_etfs else ""
    with _reuse_or_open(cur) as c:
        return set(fetch_values(c, f"MATCH (s:Stock){where} RETURN s.code"))


def get_etf_names_from_age(cur=None) -> dict[str, str]:
    """AGE에서 ETF code→name 매핑 조회."""
    with _reuse_or_open(cur) as c:
        rows = fetch_maps(c, """
            MATCH (e:ETF) WHERE e.name IS NOT NULL
            RETURN {code: e.code, name: e.name}
        """)
    return {d['code']: d['name'] for d in rows if d.get('code') and d.get('name')}


def get_last_collected_date(cur=None) -> str | None:
    """AGE에서 마지막 수집된 Price 날짜 조회. YYYYMMDD, Price가 하나도 없으면 None.

    조회 실패를 None(빈 AGE = 첫 실행)으로 돌려주면 빠진 날짜를 건너뛰므로 예외를 그대로 올린다.
    """
    with _reuse_or_open(cur) as c:
        results = execute_cypher(c, """
            MATCH (e:ETF)-[:HAS_PRICE]->(p:Price)
            RETURN p.date
            ORDER BY p.date DESC
            LIMIT 1
        """)
    if results and results[0][0]:
        raw = parse_age_value(results[0][0])
        if raw and raw != 'null':
            return raw.replace('-', '')
    return None


def fetch_price_keys(cur, label: str, from_date: str, to_date: str, where: str = '') -> set[tuple[str, str]]:
    """label(ETF·Stock) 노드의 from_date~to_date(YYYY-MM-DD) Price가 있는 (코드, YYYY-MM-DD)."""
    keys = set()
    for key in fetch_values(cur, f"""
        MATCH (n:{label})-[:HAS_PRICE]->(p:Price)
        WHERE {where}p.date >= $from_date AND p.date <= $to_date
        RETURN n.code + '|' + p.date
    """, {'from_date': from_date, 'to_date': to_date}):
        if '|' in key:
            keys.add(tuple(key.split('|', 1)))
    return keys
