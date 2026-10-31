"""
collect_holdings — ETF 구성종목(KIS PDF)을 HOLDS(날짜별 이력)·CURRENT_HOLDS(최신)로 저장
"""

import logging
from itertools import groupby

from age_db import (age_cursor, execute_cypher_batch, fetch_values, get_etf_codes_from_age,
                    get_etf_names_from_age)
from kis_api_client import get_kis_client
from market_calendar import dash_date
from universe import is_listed_security_code

log = logging.getLogger(__name__)

HOLDINGS_TOP_N = 30  # ETF마다 HOLDS로 남기는 구성종목 수 (비중 큰 순). 챗봇 질의용이라 상위만 둔다
# KIS가 통째로 응답하지 않을 때 ETF마다 타임아웃을 기다리지 않도록, 연속으로 이만큼 실패하면 중단한다
HOLDINGS_MAX_CONSECUTIVE_FAILURES = 10
# 구성종목 조회 실패가 이 비율 이상이면 태스크를 실패시켜 Airflow 재시도로 빠진 ETF만 다시 받는다
HOLDINGS_RETRY_FAILURE_RATIO = 0.2
HOLDS_COMMIT_EVERY = 50  # ETF 이만큼의 HOLDS마다 커밋


def top_holdings(components: list, n: int = HOLDINGS_TOP_N) -> list:
    """상장 주식·ETF 구성종목(채권·현금·선물 제외)만 비중 큰 순으로 n개."""
    listed = [c for c in components if is_listed_security_code(c.stock_code)]
    listed.sort(key=lambda c: c.weight, reverse=True)
    return listed[:n]


def holdings_retry_needed(failed: int, total: int, last_try: bool) -> bool:
    """구성종목 실패가 많으면 태스크를 실패시켜 Airflow 재시도에 맡길지. 마지막 시도면 받은 것만으로 진행한다."""
    return bool(failed) and failed / total >= HOLDINGS_RETRY_FAILURE_RATIO and not last_try


def stock_name_items(codes, etf_codes: set[str], etf_names: dict[str, str], stock_names: dict[str, str]) -> list[dict]:
    """Stock 노드 이름·is_etf. ETF는 AGE 이름 우선, 주식은 KIS 종목명, 둘 다 없으면 코드."""
    items = []
    for code in codes:
        is_etf = code in etf_codes
        name = (etf_names.get(code) if is_etf else None) or stock_names.get(code) or code
        items.append({'code': code, 'name': name, 'is_etf': is_etf})
    return items


def collect_holdings(etf_codes: list[str], bd: str) -> list[str]:
    """KIS ETF 구성종목시세로 현재 구성종목을 조회해 bd(YYYYMMDD) 날짜의 HOLDS 엣지로 저장.

    KIS API는 날짜 지정이 불가능(호출 시점 스냅샷)하므로 과거 날짜 백필은 지원하지 않는다.
    bd에는 최근 거래일을 넘긴다. Stock 노드(이름/is_etf 포함)도 함께 생성.
    받은 것은 저장하고, 끝내 HOLDS를 못 쓴 ETF 코드를 돌려준다 — 재실행하면 이미 받은 ETF는 건너뛰고
    이 ETF들만 다시 받는다. 재시도할지는 호출 쪽(태스크)이 정한다.
    """
    if not etf_codes or not bd:
        return []

    kis = get_kis_client()
    if kis is None:
        raise RuntimeError("KIS credentials missing — cannot collect holdings")

    date_str = dash_date(bd)

    with age_cursor() as (conn, cur):
        # AGE에서 이미 HOLDS 엣지가 있는 ETF 스킵 (같은 날 재실행 대비)
        existing_holds = set(fetch_values(cur, """
            MATCH (e:ETF)-[h:HOLDS {date: $date}]->(:Stock)
            WITH DISTINCT e.code AS code
            RETURN code
        """, {'date': date_str}))
        conn.commit()

        remaining_etfs = [c for c in etf_codes if c not in existing_holds]
        if not remaining_etfs:
            log.info(f"[{bd}] All {len(etf_codes)} ETFs already have HOLDS, skipping")
            refresh_current_holds(conn, cur, date_str)
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
                for c in top_holdings(kis.get_etf_components(ticker)):
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
            refresh_current_holds(conn, cur, date_str)
            return failed_codes

        all_stock_codes = {h['stock_code'] for h in all_holds}

        # Stock 노드 MERGE + 이름/is_etf 갱신
        execute_cypher_batch(cur, """
            MERGE (s:Stock {code: item.code}) RETURN s
        """, [{'code': c} for c in all_stock_codes])
        etf_names = get_etf_names_from_age(cur)
        etf_tickers = get_etf_codes_from_age(cur)
        execute_cypher_batch(cur, """
            MATCH (s:Stock {code: item.code})
            SET s.name = item.name, s.is_etf = item.is_etf
            RETURN s
        """, stock_name_items(all_stock_codes, etf_tickers, etf_names, stock_names))
        conn.commit()

        # HOLDS 배치
        holds_sorted = sorted(all_holds, key=lambda x: x['etf_code'])
        etf_groups = [(etf_code, list(group)) for etf_code, group in groupby(holds_sorted, key=lambda x: x['etf_code'])]

        for i in range(0, len(etf_groups), HOLDS_COMMIT_EVERY):
            batch_groups = etf_groups[i:i + HOLDS_COMMIT_EVERY]
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

        log.info(f"[{bd}] {len(all_holds)} HOLDS edges "
                 f"({len(all_stock_codes)} stocks)")

        refresh_current_holds(conn, cur, date_str)
        return failed_codes


def refresh_current_holds(conn, cur, date_str: str):
    """date_str(YYYY-MM-DD) HOLDS를 ETF별 최신 구성종목(CURRENT_HOLDS)으로 갈아 끼운다.

    HOLDS는 날짜별 이력이라 계속 늘어나므로, "현재 보유" 조회는 ETF당 최대 HOLDINGS_TOP_N개인 CURRENT_HOLDS만 읽게 한다.
    그날 HOLDS가 있는 ETF만 바꾸므로 KIS 조회에 실패한 ETF는 이전 구성종목을 유지하고,
    이미 더 최근 날짜로 갱신된 ETF는 건드리지 않는다. 같은 날짜로 다시 돌려도 결과가 같다.
    """
    try:
        items = [{'code': code, 'date': date_str} for code in fetch_values(cur, """
            MATCH (e:ETF)-[:HOLDS {date: $date}]->(:Stock)
            WITH DISTINCT e
            OPTIONAL MATCH (e)-[c:CURRENT_HOLDS]->(:Stock)
            WITH e, max(c.date) AS current_date
            WHERE current_date IS NULL OR current_date <= $date
            RETURN e.code
        """, {'date': date_str})]
        if not items:
            conn.commit()
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
