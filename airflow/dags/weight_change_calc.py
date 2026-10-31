"""
weight_change_calc — 액티브 ETF의 공시일별 보유 비중 변화를 weight_changes(RDB)에 저장

비교 규칙은 backend의 app.domain.weight_diff(웹 화면과 같은 함수)를 쓴다.
"""

import logging
from collections import defaultdict

from app.domain.weight_diff import diff_holdings

from age_db import age_cursor, execute_cypher_batch, fetch_maps, rows_to_maps

log = logging.getLogger(__name__)

INSERT_WEIGHT_CHANGE = (
    "INSERT INTO weight_changes (base_date, prev_date, etf_code, etf_name, stock_code, stock_name, "
    "change_type, previous_weight, current_weight, weight_change) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


def pending_dates(all_dates: list[str], done: set[str]) -> list[str]:
    """계산할 HOLDS 날짜: 아직 계산하지 않은 날 + 가장 최근 날짜(이미 계산했어도 — 수집 재시도로 HOLDS가 늘 수 있다)."""
    all_dates = sorted(all_dates)
    return [d for d in all_dates if d not in done or d == all_dates[-1]]


def add_holding_rows(holdings, etf_names: dict, rows: list[dict]) -> None:
    """{etf_code, etf_name, date, stock_code, stock_name, weight} 행 → holdings[etf][date][stock] = {name, weight}."""
    for data in rows:
        etf_names[data['etf_code']] = data.get('etf_name') or data['etf_code']
        holdings[data['etf_code']][data['date']][data['stock_code']] = {
            'name': data.get('stock_name') or data['stock_code'],
            'weight': float(data['weight']) if data.get('weight') else 0,
        }


def weight_change_rows(holdings, etf_names: dict, base_date: str) -> list[tuple]:
    """base_date의 ETF별 직전 수집일 대비 변화 → weight_changes 행. 이전 HOLDS가 없는 ETF는 비교하지 않는다."""
    rows = []
    for etf_code, by_date in holdings.items():
        today_h = by_date.get(base_date)
        prev_dates = [d for d in by_date if d < base_date]
        if not today_h or not prev_dates:
            continue
        prev_date = max(prev_dates)
        for c in diff_holdings(by_date[prev_date], today_h):
            rows.append((base_date, prev_date, etf_code, etf_names[etf_code], c['stock_code'], c['stock_name'],
                         c['change_type'], c['previous_weight'], c['current_weight'], c['weight_change']))
    return rows


def compute_weight_changes():
    """액티브 ETF의 이전 수집일(공시일) 대비 보유종목 비중 변화를 계산해 weight_changes에 저장.

    weight_change_dates에 없는(아직 계산하지 않은) HOLDS 날짜를 모두 처리하므로 첫 실행이면 과거 전체를 채운다.
    가장 최근 날짜는 이미 계산했어도 다시 계산한다 — KIS는 과거 구성종목을 주지 않으므로 나중에 HOLDS가
    채워질 수 있는 날(수집 재시도로 빠진 ETF를 채운 경우)은 가장 최근 날짜뿐이다.
    변화가 있는 종목은 크기와 상관없이 모두 저장하고, 기준값은 읽는 쪽(웹·디스코드)이 적용한다.
    이전 HOLDS가 없는 ETF(유니버스 신규 편입 첫날 등)는 비교하지 않는다.
    """
    with age_cursor() as (conn, cur):
        all_dates = [d['date'] for d in fetch_maps(cur, """
            MATCH (e:ETF)-[h:HOLDS]->(:Stock)
            WHERE e.active = true
            WITH DISTINCT h.date as d
            RETURN {date: d}
        """)]
        cur.execute("SELECT base_date FROM weight_change_dates")
        done = {r[0] for r in cur.fetchall()}
        if not all_dates:
            log.info("No HOLDS dates for active ETFs")
            return
        pending = pending_dates(all_dates, done)
        since = pending[0]

        holdings = defaultdict(lambda: defaultdict(dict))  # etf_code -> date -> stock_code -> {name, weight}
        etf_names = {}
        add_holding_rows(holdings, etf_names, fetch_maps(cur, """
            MATCH (e:ETF)-[h:HOLDS]->(s:Stock)
            WHERE e.active = true AND h.date >= $since
            RETURN {etf_code: e.code, etf_name: e.name, date: h.date,
                    stock_code: s.code, stock_name: s.name, weight: h.weight}
        """, {'since': since}))
        # 첫 계산일의 비교 대상: ETF별로 그 이전의 마지막 HOLDS (며칠 빠졌던 ETF도 이전 데이터와 비교한다)
        prev_dates = fetch_maps(cur, """
            MATCH (e:ETF)-[h:HOLDS]->(:Stock)
            WHERE e.active = true AND h.date < $since
            WITH e.code as code, max(h.date) as d
            RETURN {etf_code: code, date: d}
        """, {'since': since})
        add_holding_rows(holdings, etf_names, rows_to_maps(execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.etf_code})-[h:HOLDS {date: item.date}]->(s:Stock)
            RETURN {etf_code: e.code, etf_name: e.name, date: h.date,
                    stock_code: s.code, stock_name: s.name, weight: h.weight}
        """, prev_dates)))

        for base_date in pending:
            rows = weight_change_rows(holdings, etf_names, base_date)
            cur.execute("DELETE FROM weight_changes WHERE base_date = %s", (base_date,))
            if rows:
                cur.executemany(INSERT_WEIGHT_CHANGE, rows)
            cur.execute(
                "INSERT INTO weight_change_dates (base_date, computed_at) VALUES (%s, now() AT TIME ZONE 'utc') "
                "ON CONFLICT (base_date) DO UPDATE SET computed_at = EXCLUDED.computed_at",
                (base_date,),
            )
            conn.commit()
            log.info(f"Weight changes {base_date}: {len(rows)} rows")
