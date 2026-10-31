"""
collect_prices — ETF 유니버스 갱신과 ETF·종목 Price 노드 수집 (KIS 일봉·현재가)

Price 노드는 (코드, 날짜)마다 하나다. 같은 날을 두 태스크가 동시에 만들면 중복되므로
AGE에 쓰는 태스크는 Airflow pool(age_db.AGE_WRITE_POOL, 슬롯 1)로 하나씩 돈다.
"""

import logging

from age_db import (age_cursor, execute_cypher_batch, fetch_price_keys, get_etf_codes_from_age,
                    get_last_collected_date, get_stock_codes_from_age)
from kis_api_client import fetch_etf_master, get_kis_client
from market_calendar import (compact_date, dash_date, days_before, get_business_days, last_settled_day,
                             now_kst, snapshot_is_settled)
from universe import (add_new_etfs, check_new_universe_candidates, passes_universe_name_filter,
                      refresh_etf_profiles, resolve_dividend_cycle, set_etf_property, sync_universe_listing)

log = logging.getLogger(__name__)

# 가격이 빠진 (ETF, 날짜)를 다시 받는 범위. 날짜 하나로 증분하면 일부 ETF만 실패한 날이 영구히 빈다
PRICE_REFILL_BUSINESS_DAYS = 10
STOCK_PRICE_COMMIT_EVERY = 50  # 종목 이만큼마다 저장
STOCK_ERROR_LOG_LIMIT = 5  # 종목별 실패 로그는 앞의 이만큼만

# Price 노드: 없으면 만들고 값을 덮어쓴다 (label: ETF·Stock, item.code·item.date)
CREATE_MISSING_PRICE = """
    MATCH (n:{label} {{code: item.code}})
    OPTIONAL MATCH (n)-[:HAS_PRICE]->(existing:Price {{date: item.date}})
    WITH n, existing, item WHERE existing IS NULL
    CREATE (n)-[:HAS_PRICE]->(:Price {{date: item.date}})
    RETURN n
"""
SET_ETF_PRICE = """
    MATCH (e:ETF {code: item.code})-[:HAS_PRICE]->(p:Price {date: item.date})
    SET p.open = item.open, p.high = item.high, p.low = item.low,
        p.close = item.close, p.volume = item.volume, p.nav = item.nav,
        p.market_cap = item.market_cap, p.net_assets = item.net_assets,
        p.trade_value = item.trade_value
    RETURN p
"""
SET_STOCK_PRICE = """
    MATCH (s:Stock {code: item.code})-[:HAS_PRICE]->(p:Price {date: item.date})
    SET p.open = item.open, p.high = item.high, p.low = item.low,
        p.close = item.close, p.volume = item.volume,
        p.change_rate = item.change_rate
    RETURN p
"""
SET_STOCK_QUOTE = """
    MATCH (s:Stock {code: item.code})
    SET s.listed_shares = item.listed_shares, s.kis_per = item.per, s.kis_eps = item.eps,
        s.kis_pbr = item.pbr, s.quote_date = item.quote_date
    RETURN s
"""


# ──────────────────────────────────────────────
# Price 항목 (순수 함수)
# ──────────────────────────────────────────────

def etf_price_item(code: str, bar, snap=None) -> dict:
    """ETF 일봉 → Price 항목. snap(현재가)을 넘기면 NAV·순자산·시가총액을 채운다 — 날짜 지정이 안 되므로 최근 거래일에만."""
    item = {
        'code': code, 'date': dash_date(bar.date),
        'open': bar.open, 'high': bar.high, 'low': bar.low, 'close': bar.close,
        'volume': bar.volume, 'trade_value': bar.trade_value,
        'nav': None, 'market_cap': None, 'net_assets': None,
    }
    if snap:
        item.update(nav=snap.nav, net_assets=snap.net_assets, market_cap=bar.close * snap.listed_shares)
    return item


def etf_price_items(code: str, bars: list, dates: list[str], latest: str, snap=None) -> list[dict]:
    """dates(YYYYMMDD) 안의 일봉만 Price 항목으로. latest 날짜에만 snap 값을 붙인다."""
    return [etf_price_item(code, bar, snap if bar.date == latest else None) for bar in bars if bar.date in dates]


def stock_price_item(code: str, bar) -> dict:
    return {
        'code': code, 'date': dash_date(bar.date),
        'open': float(bar.open), 'high': float(bar.high),
        'low': float(bar.low), 'close': float(bar.close),
        'volume': bar.volume, 'change_rate': bar.change_rate,
    }


def stock_quote_item(code: str, bars: list, quote) -> dict | None:
    """Stock 노드에 남길 시세. 상장주수는 늘 남기고, KIS PER·EPS·PBR은 현재가가 받은 마지막 일봉 종가와 같을 때만
    (장중에 돌면 아직 확정되지 않은 가격 기준이라 비운다). quote_date는 그 지표의 기준일 = 마지막 일봉 날짜."""
    if quote is None or not bars:
        return None
    last = bars[-1]
    settled = quote.price == last.close
    return {
        'code': code, 'listed_shares': quote.listed_shares, 'quote_date': dash_date(last.date),
        'per': quote.per if settled else None, 'eps': quote.eps if settled else None,
        'pbr': quote.pbr if settled else None,
    }


def find_missing_price_dates(codes, days: list[str], existing: set[tuple[str, str]]) -> dict[str, list[str]]:
    """ETF마다 days(YYYYMMDD) 중 existing((코드, YYYYMMDD))에 없는 날짜. 빠진 날이 없는 ETF는 뺀다."""
    missing = {}
    for code in sorted(codes):
        gaps = [d for d in days if (code, d) not in existing]
        if gaps:
            missing[code] = gaps
    return missing


def snapshot_property_items(codes, snapshots: dict, value) -> list[dict]:
    """유니버스 ETF 중 스냅샷이 있고 value(code, snap)가 None이 아닌 것 → [{code, value}]. 값이 없으면 기존 값을 둔다."""
    return [{'code': c, 'value': v} for c in sorted(codes) if c in snapshots
            if (v := value(c, snapshots[c])) is not None]


def save_prices(cur, label: str, items: list[dict], set_values: str) -> None:
    """Price 노드를 없으면 만들고(1단계) 값을 덮어쓴다(2단계)."""
    execute_cypher_batch(cur, CREATE_MISSING_PRICE.format(label=label), items)
    execute_cypher_batch(cur, set_values, items)


def save_net_assets(cur, items: list[dict]) -> None:
    """Price 항목의 순자산을 ETF 노드에도 남긴다 (값이 있는 것만)."""
    set_etf_property(cur, 'net_assets', [{'code': it['code'], 'value': it['net_assets']}
                                         for it in items if it.get('net_assets')])


def save_stock_quotes(cur, quotes: list[dict]) -> None:
    """stock_quote_item 목록을 Stock 노드에 쓴다 (커밋은 부르는 쪽이 한다). 값이 None이면 그 속성이 지워진다."""
    execute_cypher_batch(cur, SET_STOCK_QUOTE, quotes)


# ──────────────────────────────────────────────
# ETF 유니버스 + 가격
# ──────────────────────────────────────────────

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

    with age_cursor() as (conn, cur):
        # ── 1-1. 상장폐지 ETF 제거, 이름 변경 반영 ──
        existing_codes = sync_universe_listing(cur, existing_codes, master)
        conn.commit()

        # ── 2. 신규 ETF 노드 + 메타데이터 ──
        snapshot_dicts = [{'code': c, 'name': master[c], 'net_assets': snap.net_assets}
                          for c, snap in snapshots.items()]
        new_candidates = check_new_universe_candidates(snapshot_dicts, existing_codes)

        if new_candidates:
            add_new_etfs(cur, new_candidates)
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
        set_etf_property(cur, 'dividend_cycle', snapshot_property_items(
            existing_codes, snapshots, lambda c, snap: resolve_dividend_cycle(master[c], snap.dividend_cycle)))
        conn.commit()

        # ── 2-3. 구성종목 수: KIS가 주는 전체 개수 (HOLDS는 상위 HOLDINGS_TOP_N개까지만 있다) ──
        set_etf_property(cur, 'component_count', snapshot_property_items(
            existing_codes, snapshots, lambda c, snap: snap.component_count or None))
        conn.commit()

        # ── 2-4. 액티브 여부: KIS 분류(bstp_kor_isnm), 분류가 비면 기존 값 유지 ──
        set_etf_property(cur, 'active', snapshot_property_items(
            existing_codes, snapshots, lambda c, snap: snap.active))
        conn.commit()

        # ── 3. Price 노드 (유니버스 ETF) ──
        price_items = []
        for code in sorted(existing_codes):
            try:
                bars = kis.get_daily_bars(code, dates[0], latest)
            except Exception as e:
                log.warning(f"Failed ETF daily bars for {code}: {e}")
                continue
            price_items.extend(etf_price_items(code, bars, dates, latest, snapshots.get(code)))

        if price_items:
            save_prices(cur, 'ETF', price_items, SET_ETF_PRICE)
            save_net_assets(cur, price_items)
            conn.commit()

        actual_dates = sorted({compact_date(it['date']) for it in price_items})
        log.info(f"Universe & prices: {len(existing_codes)} ETFs, "
                 f"{len(price_items)} price records, dates={actual_dates}")
        return existing_codes, all_new_etfs, actual_dates


def refill_missing_etf_prices() -> int:
    """최근 PRICE_REFILL_BUSINESS_DAYS 영업일 중 Price가 빠진 (ETF, 날짜)를 KIS 일봉으로 채운다. 채운 개수를 돌려준다."""
    if get_kis_client() is None:
        log.warning("Skipping price refill (KIS credentials missing)")
        return 0
    end = last_settled_day(now_kst())
    start = days_before(end, PRICE_REFILL_BUSINESS_DAYS * 2)
    return fill_missing_etf_prices(get_business_days(start, end)[-PRICE_REFILL_BUSINESS_DAYS:])


def backfill_price_days(calendar_days: int) -> list[str]:
    """지난 calendar_days일의 영업일 중 최근 PRICE_REFILL_BUSINESS_DAYS 영업일을 뺀 날들 (YYYYMMDD).

    최근 영업일은 정기 수집(age_sync_universe)이 쓰는 범위라, 백필과 겹쳐 같은 날 Price가 둘 생기지 않게 뺀다.
    """
    end = last_settled_day(now_kst())
    return get_business_days(days_before(end, calendar_days), end)[:-PRICE_REFILL_BUSINESS_DAYS]


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

    with age_cursor() as (conn, cur):
        codes = get_etf_codes_from_age(cur)
        existing = {(code, compact_date(d))
                    for code, d in fetch_price_keys(cur, 'ETF', dash_date(days[0]), dash_date(days[-1]))}

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
                'code': code, 'date': dash_date(bar.date),
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


def refresh_latest_snapshot_values() -> int:
    """마지막 수집일 Price의 NAV·순자산·시가총액을 지금 받은 현재가로 다시 쓴다. 고친 개수를 돌려준다.

    장 마감 뒤 실행이 그날 Price를 만들면 다음 날 아침 실행은 새 날짜가 없어 현재가를 받지 않으므로
    NAV·순자산이 장 마감 직후 값으로 남는다. 새 날짜가 없는 실행이 이 함수로 마지막 수집일 값을 다시 쓴다.
    장중에는 현재가가 그날 값이라 쓰지 않는다(snapshot_is_settled).
    """
    if not snapshot_is_settled(now_kst()):
        log.info("Skipping snapshot refresh during market hours")
        return 0
    kis = get_kis_client()
    if kis is None:
        log.warning("Skipping snapshot refresh (KIS credentials missing)")
        return 0

    with age_cursor() as (conn, cur):
        last = get_last_collected_date(cur)
        if not last:
            return 0
        codes = get_etf_codes_from_age(cur)
        conn.commit()  # 현재가를 받는 동안 조회 트랜잭션을 열어 두지 않는다

        items = []
        for code in sorted(codes):
            try:
                snap = kis.get_etf_snapshot(code)
            except Exception as e:
                log.warning(f"Failed ETF snapshot for refresh {code}: {e}")
                continue
            items.append({'code': code, 'date': dash_date(last), 'nav': snap.nav,
                          'net_assets': snap.net_assets, 'listed_shares': snap.listed_shares})

        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})-[:HAS_PRICE]->(p:Price {date: item.date})
            SET p.nav = item.nav, p.net_assets = item.net_assets,
                p.market_cap = p.close * item.listed_shares
            RETURN p
        """, items)
        save_net_assets(cur, items)
        conn.commit()
        log.info(f"Snapshot refresh: {len(items)} ETFs on {last}")
        return len(items)


# ──────────────────────────────────────────────
# 종목 가격
# ──────────────────────────────────────────────

def collect_stock_prices_for_dates(dates: list[str]):
    """Stock(is_etf=false) 일봉을 KIS 기간별시세로 조회해 날짜별 Price 노드로 저장.

    종목당 기간 전체를 한 번(100일 단위)에 조회하고, 이미 저장된 (종목, 날짜)는 건너뛴다.
    같은 응답의 시세(output1)로 Stock 노드의 상장주수와 KIS PER·EPS·PBR도 갱신한다 (stock_quote_item).
    """
    if not dates:
        return

    kis = get_kis_client()
    if kis is None:
        log.warning("Skipping stock prices (KIS credentials missing)")
        return

    date_strs = {dash_date(d) for d in dates}

    with age_cursor() as (conn, cur):
        stock_codes = get_stock_codes_from_age(cur, exclude_etfs=True)
        # 이미 저장된 (종목, 날짜)
        existing = fetch_price_keys(cur, 'Stock', min(date_strs), max(date_strs), where='n.is_etf = false AND ')
        conn.commit()

        if not stock_codes:
            log.warning("No Stock nodes for price collection")
            return

        targets = sorted(c for c in stock_codes
                         if any((c, d) not in existing for d in date_strs))
        log.info(f"Collecting prices for {len(targets)}/{len(stock_codes)} stocks "
                 f"across {len(dates)} dates (via KIS daily bars)")

        total_success = 0
        error_count = 0
        pending_items = []
        pending_quotes = []

        for i, code in enumerate(targets, 1):
            try:
                bars, quote = kis.get_daily_bars_with_quote(code, min(dates), max(dates))
                quote_item = stock_quote_item(code, bars, quote)
                if quote_item:
                    pending_quotes.append(quote_item)
                pending_items.extend(stock_price_item(code, bar) for bar in bars
                                     if dash_date(bar.date) in date_strs and (code, dash_date(bar.date)) not in existing)
            except Exception as e:
                error_count += 1
                if error_count <= STOCK_ERROR_LOG_LIMIT:
                    log.warning(f"Failed KIS daily bars for {code}: {e}")
                elif error_count == STOCK_ERROR_LOG_LIMIT + 1:
                    log.warning("Suppressing further per-stock errors...")

            if i % STOCK_PRICE_COMMIT_EVERY == 0 or i == len(targets):
                try:
                    save_stock_quotes(cur, pending_quotes)
                    if pending_items:
                        save_prices(cur, 'Stock', pending_items, SET_STOCK_PRICE)
                    conn.commit()
                    total_success += len(pending_items)
                except Exception as e:
                    log.warning(f"Failed stock price batch at {i}: {e}")
                    conn.rollback()
                pending_items = []
                pending_quotes = []

    if error_count:
        log.warning(f"{error_count} stocks failed")
    log.info(f"Stock prices complete: {total_success} records")
