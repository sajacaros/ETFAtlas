"""
returns — ETF 1D/1W/1M 수익률·1주 시가총액 변화 (ETF 노드 속성)
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from age_db import age_cursor, execute_cypher_batch, fetch_maps
from market_calendar import now_kst

log = logging.getLogger(__name__)

# 수익률 계산에 읽는 기간 (1개월 수익률 + 휴장일 여유)
RETURNS_LOOKBACK_DAYS = 70
RETURNS_MAX_PRICES = 45  # ETF마다 최근 이만큼의 가격만 본다 (1개월 ≈ 20거래일)


def pct_change(latest: float, prev: float) -> float | None:
    return round((latest - prev) / prev * 100, 2) if prev > 0 else None


def etf_returns(code: str, prices: list[dict]) -> dict | None:
    """최근 날짜부터 정렬된 {date, close, market_cap} 목록 → ETF 노드에 쓸 수익률. 계산할 수 없으면 None."""
    if not prices:
        return None
    latest_close = float(prices[0]['close'])
    if latest_close == 0:
        return None

    latest_date = datetime.strptime(prices[0]['date'], '%Y-%m-%d')
    target_1w = (latest_date - timedelta(days=7)).strftime('%Y-%m-%d')
    target_1m = (latest_date - timedelta(days=30)).strftime('%Y-%m-%d')

    item = {
        'code': code, 'close_price': latest_close,
        'return_1d': None, 'return_1w': None, 'return_1m': None,
        'market_cap_change_1w': None,
    }

    if len(prices) > 1:
        item['return_1d'] = pct_change(latest_close, float(prices[1]['close']))

    for p in prices[1:]:
        if p['date'] <= target_1w:
            item['return_1w'] = pct_change(latest_close, float(p['close']))
            latest_mc = prices[0].get('market_cap')
            prev_mc = p.get('market_cap')
            if latest_mc and prev_mc:
                item['market_cap_change_1w'] = round(
                    (float(latest_mc) - float(prev_mc)) / float(prev_mc) * 100, 2)
            break

    for p in prices[1:]:
        if p['date'] <= target_1m:
            item['return_1m'] = pct_change(latest_close, float(p['close']))
            break

    return item


def group_recent_prices(rows: list[dict]) -> dict[str, list[dict]]:
    """날짜 내림차순 {code, date, close, market_cap} → ETF별 최근 RETURNS_MAX_PRICES개."""
    etf_prices = defaultdict(list)
    for parsed in rows:
        if parsed.get('close') is not None and parsed.get('date') is not None:
            code = parsed['code']
            if len(etf_prices[code]) < RETURNS_MAX_PRICES:
                etf_prices[code].append(parsed)
    return etf_prices


def update_etf_returns():
    """ETF 1D/1W/1M 수익률 계산 및 저장."""
    with age_cursor() as (conn, cur):
        # 전체 ETF의 최근 RETURNS_LOOKBACK_DAYS일 가격을 한 번에 조회 (백필한 1년치를 다 읽지 않게 날짜로 먼저 자른다)
        since = (now_kst() - timedelta(days=RETURNS_LOOKBACK_DAYS)).strftime('%Y-%m-%d')
        rows = fetch_maps(cur, """
            MATCH (e:ETF)-[:HAS_PRICE]->(p:Price)
            WHERE p.date >= $since
            WITH e.code AS code, p.date AS date, p.close AS close, p.market_cap AS market_cap
            ORDER BY date DESC
            RETURN {code: code, date: date, close: close, market_cap: market_cap}
        """, {'since': since})

        if not rows:
            log.warning("No price data for returns calculation")
            return

        etf_prices = group_recent_prices(rows)
        log.info(f"Calculating returns for {len(etf_prices)} ETFs")
        update_items = []
        for code, prices in etf_prices.items():
            try:
                item = etf_returns(code, prices)
            except Exception as e:
                log.warning(f"Failed returns for {code}: {e}")
                continue
            if item:
                update_items.append(item)

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
