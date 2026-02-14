"""
ETF Universe Sync DAG (Apache AGE) — 경량화 + 배치
- ETF 목록 수집
- 구성종목(PDF) 수집 (HOLDS 엣지만, 배치 UNWIND)
- 가격 데이터 수집 (배치 UNWIND)
- 포트폴리오 변화 감지

메타데이터/구조 재구축은 rebuild_graph_age DAG(주간)에서 수행.
RDB 동기화는 sync_metadata_rdb DAG에서 독립 수행.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
import logging

from age_utils import (
    get_db_connection, init_age, execute_cypher, execute_cypher_batch,
    check_new_universe_candidates, get_krx_daily_data, _get_krx_data_for_exact_date,
    get_valid_ticker_set,
)

log = logging.getLogger(__name__)

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 3,
    'retry_delay': timedelta(minutes=5),
    'email_on_failure': False,
}

dag = DAG(
    'sync_universe_age',
    default_args=default_args,
    description='ETF 데이터 일일 수집 파이프라인 (Apache AGE)',
    schedule_interval='0 8 * * 1-5',  # 평일 08:00 KST
    catchup=False,
    tags=['etf', 'daily', 'age'],
)


# ──────────────────────────────────────────────
# Task 함수
# ──────────────────────────────────────────────

def fetch_krx_data(**context):
    """KRX API에서 일별매매정보 조회 (누락 영업일 자동 백필)

    DB의 마지막 수집일 ~ 오늘 사이 누락된 영업일을 모두 수집.
    XCom:
      - trading_date: 최신 거래일 1개 (기존 downstream 호환)
      - trading_dates: 수집된 모든 거래일 리스트
      - return: 모든 날짜의 krx_data 통합 리스트
    """
    from datetime import datetime, timedelta
    import re as re_mod

    date = context['ds_nodash']
    ti = context['ti']

    # 1. AGE에서 마지막 수집일 조회
    last_collected = None
    try:
        conn = get_db_connection()
        cur = init_age(conn)
        results = execute_cypher(cur, """
            MATCH (e:ETF)-[:HAS_PRICE]->(p:Price)
            RETURN p.date
            ORDER BY p.date DESC
            LIMIT 1
        """)
        if results and results[0][0]:
            raw = str(results[0][0])
            raw = re_mod.sub(r'::(?:numeric|integer|float|vertex|edge|path)\b', '', raw)
            raw = raw.strip('"')
            if raw and raw != 'null':
                last_collected = datetime.strptime(raw, '%Y-%m-%d').date()
                log.info(f"Last collected date in AGE: {last_collected}")
        cur.close()
        conn.close()
    except Exception as e:
        log.warning(f"Failed to query last collected date: {e}")

    # 2. 백필 시작일 결정
    INITIAL_BACKFILL_START = datetime(2026, 1, 2).date()
    base_date = datetime.strptime(date, '%Y%m%d').date()

    if not last_collected:
        start_date = INITIAL_BACKFILL_START
        log.info(f"No previous data in DB, initial backfill from {start_date} to {base_date}")
    else:
        start_date = last_collected + timedelta(days=1)

    if start_date > base_date:
        log.info("No missing dates to backfill, already up to date")
        ti.xcom_push(key='trading_date', value=last_collected.strftime('%Y%m%d') if last_collected else '')
        ti.xcom_push(key='trading_dates', value=[])
        return []

    # 평일 날짜 리스트 생성
    candidate_dates = []
    current = start_date
    while current <= base_date:
        if current.weekday() < 5:
            candidate_dates.append(current.strftime('%Y%m%d'))
        current += timedelta(days=1)

    log.info(f"Backfill candidates: {len(candidate_dates)} weekdays from {start_date} to {base_date}")

    # 각 날짜별 KRX 데이터 수집
    all_krx_data = []
    collected_dates = []

    for candidate_date in candidate_dates:
        try:
            result = _get_krx_data_for_exact_date(candidate_date)
            if result:
                all_krx_data.extend(result)
                collected_dates.append(candidate_date)
                log.info(f"Collected {len(result)} ETFs for {candidate_date}")
            else:
                log.info(f"No data for {candidate_date} (likely holiday), skipping")
        except Exception as e:
            log.warning(f"Failed to fetch data for {candidate_date}: {e}")

    log.info(f"Backfill complete: collected {len(collected_dates)} trading days, "
             f"{len(all_krx_data)} total records")

    # 백필 결과가 없고, DB에 이전 데이터도 없는 경우만 fallback
    if not collected_dates and not last_collected:
        log.info("No previous data and no backfill results, falling back to latest trading day search")
        krx_data, actual_date = get_krx_daily_data(date)
        if krx_data:
            all_krx_data = krx_data
            collected_dates = [actual_date]
            log.info(f"Fallback: found {len(krx_data)} ETFs for {actual_date}")
    elif not collected_dates:
        log.info("No new trading days to collect, skipping")

    latest_date = collected_dates[-1] if collected_dates else ''
    ti.xcom_push(key='trading_date', value=latest_date)
    ti.xcom_push(key='trading_dates', value=collected_dates)

    return [
        {
            'date': item.date,
            'code': item.code,
            'name': item.name,
            'close_price': item.close_price,
            'open_price': item.open_price,
            'high_price': item.high_price,
            'low_price': item.low_price,
            'volume': item.volume,
            'trade_value': item.trade_value,
            'nav': item.nav,
            'market_cap': item.market_cap,
            'net_assets': item.net_assets,
        }
        for item in all_krx_data
    ]


def filter_etf_list(**context):
    """AGE 기반 ETF 유니버스 필터링 (배치)"""
    import re as re_mod

    ti = context['ti']
    krx_data_dicts = ti.xcom_pull(task_ids='fetch_krx_data')

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        results = execute_cypher(cur, """
            MATCH (e:ETF)
            RETURN e.code
        """)
        existing_codes = set()
        for row in results:
            if row[0]:
                raw = str(row[0])
                raw = re_mod.sub(r'::(?:numeric|integer|float|vertex|edge|path)\b', '', raw)
                raw = raw.strip('"')
                if raw:
                    existing_codes.add(raw)
        log.info(f"Existing universe (AGE ETF nodes): {len(existing_codes)} ETFs")

        if krx_data_dicts:
            new_candidates = check_new_universe_candidates(krx_data_dicts, existing_codes)

            if new_candidates:
                # 배치로 신규 ETF 노드 생성
                items = [{'code': c['code']} for c in new_candidates]
                execute_cypher_batch(cur, """
                    MERGE (e:ETF {code: item.code})
                    RETURN e
                """, items)

                set_items = [{'code': c['code'], 'name': c['name']}
                             for c in new_candidates]
                execute_cypher_batch(cur, """
                    MATCH (e:ETF {code: item.code})
                    SET e.name = item.name
                    RETURN e
                """, set_items)

                conn.commit()
                for c in new_candidates:
                    existing_codes.add(c['code'])
                log.info(f"Added {len(new_candidates)} new ETFs to universe (AGE)")
                ti.xcom_push(key='new_etfs', value=[
                    {'code': c['code'], 'name': c['name']} for c in new_candidates
                ])

        universe_tickers = list(existing_codes)
        log.info(f"Total universe: {len(universe_tickers)} ETFs")
        return universe_tickers

    finally:
        cur.close()
        conn.close()


def collect_holdings(**context):
    """ETF 구성종목 수집 — HOLDS 엣지만 배치 생성

    경량화: 섹터 맵/이름 맵/Stock 구조 생성은 rebuild_graph_age 주간 DAG에서 수행.
    Safety net: Stock 노드 코드만 배치 MERGE (이름/섹터 SET 없이).
    """
    from pykrx import stock
    import pandas as pd
    import time

    ti = context['ti']
    tickers = ti.xcom_pull(task_ids='filter_etf_list')
    trading_date = ti.xcom_pull(task_ids='fetch_krx_data', key='trading_date')
    date_str = (f"{trading_date[:4]}-{trading_date[4:6]}-{trading_date[6:8]}"
                if trading_date else context['ds'])

    if not tickers:
        log.warning("No tickers to process")
        return

    # ── 유효 종목코드 집합 (채권/파생/현금 제외) ──
    query_date = trading_date if trading_date else context['ds_nodash']
    valid_tickers = get_valid_ticker_set(query_date)

    # ── Pass 1: 모든 ETF holdings 데이터 수집 ──
    holdings_data = {}
    for ticker in tickers:
        try:
            df = stock.get_etf_portfolio_deposit_file(ticker)
            if df is not None and not df.empty:
                df = df[~df.index.astype(str).isin(['010010'])]
                # 상장종목만 필터 (채권/파생/현금 제외)
                df = df[df.index.astype(str).isin(valid_tickers)]
                if '비중' in df.columns:
                    df = df.sort_values('비중', ascending=False).head(30)
                else:
                    df = df.head(30)
                holdings_data[ticker] = df
            else:
                log.warning(f"No holdings data for {ticker}")
            time.sleep(0.1)
        except Exception as e:
            log.warning(f"Failed to fetch holdings for {ticker}: {e}")

    log.info(f"Fetched holdings for {len(holdings_data)}/{len(tickers)} ETFs")

    # ── 고유 Stock 코드 추출 ──
    all_stock_codes = set()
    for df in holdings_data.values():
        all_stock_codes.update(str(c) for c in df.index)

    log.info(f"Unique stock codes (filtered): {len(all_stock_codes)}")

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # Safety net: Stock 노드 배치 MERGE + is_etf 기본값 설정
        # (주간 rebuild_graph_age 전까지 collect_stock_prices에서 누락되지 않도록)
        if all_stock_codes:
            stock_items = [{'code': c} for c in all_stock_codes]
            execute_cypher_batch(cur, """
                MERGE (s:Stock {code: item.code})
                RETURN s
            """, stock_items)
            execute_cypher_batch(cur, """
                MATCH (s:Stock {code: item.code})
                WHERE s.is_etf IS NULL
                SET s.is_etf = false
                RETURN s
            """, stock_items)
            conn.commit()
            log.info(f"Safety net: ensured {len(all_stock_codes)} Stock nodes exist")

        # ── HOLDS 엣지 배치 생성 (UNWIND) ──
        all_holds = []
        for ticker, df in holdings_data.items():
            for idx, row in df.iterrows():
                stock_code = str(idx)
                if not stock_code:
                    continue
                weight = float(row.get('비중', 0))
                shares_val = row.get('계약수', row.get('주수', 0))
                shares = int(shares_val) if shares_val and not pd.isna(shares_val) else 0
                all_holds.append({
                    'etf_code': ticker,
                    'stock_code': stock_code,
                    'date': date_str,
                    'weight': weight,
                    'shares': shares,
                })

        log.info(f"Total HOLDS edges to create: {len(all_holds)}")

        # ETF별로 나누어 배치 커밋 (부분 진행 보존)
        from itertools import groupby
        holds_sorted = sorted(all_holds, key=lambda x: x['etf_code'])
        success_count = 0
        COMMIT_EVERY = 50  # ETF 단위

        etf_groups = []
        for etf_code, group in groupby(holds_sorted, key=lambda x: x['etf_code']):
            etf_groups.append((etf_code, list(group)))

        for i in range(0, len(etf_groups), COMMIT_EVERY):
            batch_groups = etf_groups[i:i + COMMIT_EVERY]
            batch_items = [item for _, items in batch_groups for item in items]
            try:
                # HOLDS MERGE 배치
                execute_cypher_batch(cur, """
                    MATCH (e:ETF {code: item.etf_code})
                    MATCH (s:Stock {code: item.stock_code})
                    MERGE (e)-[h:HOLDS {date: item.date}]->(s)
                    RETURN h
                """, batch_items)

                # HOLDS SET 배치 (AGE 버그 우회로 MERGE + SET 분리)
                execute_cypher_batch(cur, """
                    MATCH (e:ETF {code: item.etf_code})-[h:HOLDS {date: item.date}]->(s:Stock {code: item.stock_code})
                    SET h.weight = item.weight, h.shares = item.shares
                    RETURN h
                """, batch_items)

                conn.commit()
                success_count += len(batch_items)
                log.info(f"HOLDS batch committed: {min(i + COMMIT_EVERY, len(etf_groups))}/{len(etf_groups)} ETFs")
            except Exception as e:
                log.warning(f"Failed HOLDS batch at ETF group {i}: {e}")
                conn.rollback()
                cur = init_age(conn)

        log.info(f"Holdings collection complete: {success_count}/{len(all_holds)} HOLDS edges")

    finally:
        cur.close()
        conn.close()


def collect_prices(**context):
    """ETF 가격 데이터를 AGE Price 노드로 배치 저장 (UNWIND)

    각 krx_data item의 date 필드를 그대로 사용하여 멀티 날짜 지원.
    (ETF)-[:HAS_PRICE]->(Price {date, open, high, low, close, volume, nav, market_cap, net_assets, trade_value})
    """
    ti = context['ti']
    krx_data_dicts = ti.xcom_pull(task_ids='fetch_krx_data')
    tickers = ti.xcom_pull(task_ids='filter_etf_list')

    if not krx_data_dicts:
        log.warning("No KRX data available")
        return

    # 유니버스 티커로 필터링
    universe_codes = set(tickers) if tickers else set()
    if not universe_codes:
        log.warning("No universe tickers, skipping price collection")
        return

    # date 변환 포함 items 준비 (유니버스만)
    items = []
    for krx_item in krx_data_dicts:
        if krx_item['code'] not in universe_codes:
            continue
        item_date = krx_item['date']
        date_str = f"{item_date[:4]}-{item_date[4:6]}-{item_date[6:8]}"
        items.append({
            'code': krx_item['code'],
            'date': date_str,
            'open': krx_item['open_price'],
            'high': krx_item['high_price'],
            'low': krx_item['low_price'],
            'close': krx_item['close_price'],
            'volume': krx_item['volume'],
            'nav': krx_item['nav'],
            'market_cap': krx_item['market_cap'],
            'net_assets': krx_item['net_assets'],
            'trade_value': krx_item['trade_value'],
        })

    if not items:
        log.warning("No price data for universe ETFs")
        return

    log.info(f"Collecting prices for {len(set(i['code'] for i in items))} universe ETFs "
             f"(filtered from {len(krx_data_dicts)} KRX records)")

    conn = get_db_connection()
    cur = init_age(conn)

    try:

        # 날짜별로 나누어 배치 커밋 (부분 진행 보존)
        from itertools import groupby
        items_sorted = sorted(items, key=lambda x: x['date'])
        success_count = 0

        for date_key, group in groupby(items_sorted, key=lambda x: x['date']):
            date_items = list(group)
            try:
                # 2) HAS_PRICE→Price MERGE 배치
                execute_cypher_batch(cur, """
                    MATCH (e:ETF {code: item.code})
                    MERGE (e)-[:HAS_PRICE]->(p:Price {date: item.date})
                    RETURN p
                """, date_items)

                # 3) Price SET 배치
                execute_cypher_batch(cur, """
                    MATCH (e:ETF {code: item.code})-[:HAS_PRICE]->(p:Price {date: item.date})
                    SET p.open = item.open, p.high = item.high, p.low = item.low,
                        p.close = item.close, p.volume = item.volume, p.nav = item.nav,
                        p.market_cap = item.market_cap, p.net_assets = item.net_assets,
                        p.trade_value = item.trade_value
                    RETURN p
                """, date_items)

                # 4) ETF 노드에 net_assets 프로퍼티 업데이트 (검색 시가총액순 정렬용, 0 제외)
                valid_na_items = [it for it in date_items if it.get('net_assets') and it['net_assets'] > 0]
                if valid_na_items:
                    execute_cypher_batch(cur, """
                        MATCH (e:ETF {code: item.code})
                        SET e.net_assets = item.net_assets
                        RETURN e
                    """, valid_na_items)

                conn.commit()
                success_count += len(date_items)
                log.info(f"Price batch {date_key}: {len(date_items)} records committed")
            except Exception as e:
                log.warning(f"Failed price batch for {date_key}: {e}")
                conn.rollback()
                cur = init_age(conn)

        log.info(f"Price collection complete: {success_count}/{len(items)} records")

    finally:
        cur.close()
        conn.close()


def collect_stock_prices(**context):
    """Stock 가격 데이터를 AGE Price 노드로 배치 저장 (UNWIND)

    XCom의 trading_dates 리스트를 사용하여 멀티 날짜 수집 지원.
    (Stock)-[:HAS_PRICE]->(Price {date, open, high, low, close, volume, change_rate})
    """
    from pykrx import stock
    import json

    ti = context['ti']
    trading_dates = ti.xcom_pull(task_ids='fetch_krx_data', key='trading_dates')
    if not trading_dates:
        trading_date = ti.xcom_pull(task_ids='fetch_krx_data', key='trading_date')
        trading_dates = [trading_date] if trading_date else [context['ds_nodash']]

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # 1. is_etf=false인 Stock 코드 목록 조회
        results = execute_cypher(cur, """
            MATCH (s:Stock)
            WHERE s.is_etf = false
            RETURN s.code
        """, {})
        stock_codes = set()
        for row in results:
            if row[0]:
                data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
                if data:
                    stock_codes.add(str(data).strip('"'))

        if not stock_codes:
            log.warning("No stocks to collect prices for")
            return

        log.info(f"Collecting prices for {len(stock_codes)} stocks "
                 f"across {len(trading_dates)} dates")

        # 2. 각 날짜별로 pykrx OHLCV 조회 → 배치 저장
        total_success = 0

        for td in trading_dates:
            try:
                date_str = f"{td[:4]}-{td[4:6]}-{td[6:8]}"
                df = stock.get_market_ohlcv_by_ticker(td)

                if df is None or df.empty:
                    log.warning(f"No market OHLCV data for {td}")
                    continue

                # 배치 아이템 구성
                items = []
                for code in stock_codes:
                    if code in df.index:
                        row = df.loc[code]
                        items.append({
                            'code': code,
                            'date': date_str,
                            'open': float(row.get('시가', 0)),
                            'high': float(row.get('고가', 0)),
                            'low': float(row.get('저가', 0)),
                            'close': float(row.get('종가', 0)),
                            'volume': int(row.get('거래량', 0)),
                            'change_rate': float(row.get('등락률', 0)),
                        })

                if not items:
                    log.warning(f"No matching stock data for {td}")
                    continue

                # MERGE 배치
                execute_cypher_batch(cur, """
                    MATCH (s:Stock {code: item.code})
                    MERGE (s)-[:HAS_PRICE]->(p:Price {date: item.date})
                    RETURN p
                """, items)

                # SET 배치
                execute_cypher_batch(cur, """
                    MATCH (s:Stock {code: item.code})-[:HAS_PRICE]->(p:Price {date: item.date})
                    SET p.open = item.open, p.high = item.high, p.low = item.low,
                        p.close = item.close, p.volume = item.volume,
                        p.change_rate = item.change_rate
                    RETURN p
                """, items)

                conn.commit()
                total_success += len(items)
                log.info(f"Stock prices for {td}: {len(items)} saved")

            except Exception as e:
                log.warning(f"Failed to collect stock prices for date {td}: {e}")
                continue

        log.info(f"Stock price collection complete. Total: {total_success}")

    finally:
        cur.close()
        conn.close()


def detect_portfolio_changes(**context):
    """포트폴리오 변화 감지 및 AGE에 저장"""

    ti = context['ti']
    tickers = ti.xcom_pull(task_ids='filter_etf_list')
    trading_date = ti.xcom_pull(task_ids='fetch_krx_data', key='trading_date')
    today = (f"{trading_date[:4]}-{trading_date[4:6]}-{trading_date[6:8]}"
             if trading_date else context['ds'])
    yesterday = (datetime.strptime(today, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')

    if not tickers:
        log.warning("No tickers to process")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    changes_count = 0

    try:
        for ticker in tickers:
            try:
                # Get today's holdings from AGE
                today_results = execute_cypher(cur, """
                    MATCH (e:ETF {code: $etf_code})-[h:HOLDS {date: $date}]->(s:Stock)
                    RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight}
                """, {'etf_code': ticker, 'date': today})

                today_holdings = {}
                for row in today_results:
                    if row[0]:
                        import json
                        import re
                        raw = str(row[0])
                        raw = re.sub(r'::(?:numeric|integer|float|vertex|edge|path)\b', '', raw)
                        data = json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(data, dict):
                            code = data.get('stock_code', '')
                            if code:
                                today_holdings[code] = {
                                    'name': data.get('stock_name', ''),
                                    'weight': float(data.get('weight', 0))
                                }

                # Get yesterday's holdings from AGE
                yesterday_results = execute_cypher(cur, """
                    MATCH (e:ETF {code: $etf_code})-[h:HOLDS {date: $date}]->(s:Stock)
                    RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight}
                """, {'etf_code': ticker, 'date': yesterday})

                yesterday_holdings = {}
                for row in yesterday_results:
                    if row[0]:
                        import json
                        import re
                        raw = str(row[0])
                        raw = re.sub(r'::(?:numeric|integer|float|vertex|edge|path)\b', '', raw)
                        data = json.loads(raw) if isinstance(raw, str) else raw
                        if isinstance(data, dict):
                            code = data.get('stock_code', '')
                            if code:
                                yesterday_holdings[code] = {
                                    'name': data.get('stock_name', ''),
                                    'weight': float(data.get('weight', 0))
                                }

                if not today_holdings or not yesterday_holdings:
                    continue

                changes = _detect_changes(ticker, today_holdings, yesterday_holdings)

                for change in changes:
                    import uuid
                    change_id = str(uuid.uuid4())

                    execute_cypher(cur, """
                        MATCH (e:ETF {code: $etf_code})
                        CREATE (c:Change {
                            id: $change_id,
                            stock_code: $stock_code,
                            stock_name: $stock_name,
                            change_type: $change_type,
                            before_weight: $before_weight,
                            after_weight: $after_weight,
                            weight_change: $weight_change,
                            detected_at: $detected_at
                        })
                        CREATE (e)-[:HAS_CHANGE]->(c)
                        RETURN c
                    """, {
                        'etf_code': ticker,
                        'change_id': change_id,
                        'stock_code': change['stock_code'],
                        'stock_name': change['stock_name'],
                        'change_type': change['type'],
                        'before_weight': change['before_weight'] if change['before_weight'] else 0,
                        'after_weight': change['after_weight'] if change['after_weight'] else 0,
                        'weight_change': change.get('weight_change', 0),
                        'detected_at': today
                    })
                    changes_count += 1

                conn.commit()

            except Exception as e:
                log.warning(f"Failed to detect changes for {ticker}: {e}")
                conn.rollback()
                cur = init_age(conn)
                continue

        log.info(f"Detected {changes_count} portfolio changes")

    finally:
        cur.close()
        conn.close()


def _detect_changes(etf_code: str, today_holdings: dict,
                    yesterday_holdings: dict) -> list:
    """두 스냅샷 비교하여 변화 감지"""
    changes = []

    # 신규 편입
    for code, data in today_holdings.items():
        if code not in yesterday_holdings:
            changes.append({
                'type': 'added',
                'stock_code': code,
                'stock_name': data['name'],
                'before_weight': None,
                'after_weight': data['weight'],
                'weight_change': data['weight']
            })

    # 완전 제외
    for code, data in yesterday_holdings.items():
        if code not in today_holdings:
            changes.append({
                'type': 'removed',
                'stock_code': code,
                'stock_name': data['name'],
                'before_weight': data['weight'],
                'after_weight': None,
                'weight_change': -data['weight']
            })

    # 비중 5%p 이상 변화
    for code, today_data in today_holdings.items():
        if code in yesterday_holdings:
            yesterday_data = yesterday_holdings[code]
            diff = today_data['weight'] - yesterday_data['weight']
            if abs(diff) >= 5.0:
                changes.append({
                    'type': 'increased' if diff > 0 else 'decreased',
                    'stock_code': code,
                    'stock_name': today_data['name'],
                    'before_weight': yesterday_data['weight'],
                    'after_weight': today_data['weight'],
                    'weight_change': diff
                })

    return changes


def update_etf_returns(**context):
    """ETF 노드에 1D/1W/1M 수익률 계산·저장

    collect_prices 이후 실행. AGE Price 노드에서 최신 종가와 N일 전 종가를 비교하여
    return_1d, return_1w, return_1m 을 ETF 노드 프로퍼티로 SET.
    1W = 7일 전, 1M = 30일 전 기준 (해당 날짜 이하에서 가장 가까운 거래일 종가 사용).
    """
    import json
    import re as re_mod
    from datetime import datetime, timedelta

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # 1. 전체 ETF 코드 목록
        results = execute_cypher(cur, """
            MATCH (e:ETF)
            RETURN e.code
        """)
        etf_codes = []
        for row in results:
            if row[0]:
                raw = str(row[0])
                raw = re_mod.sub(r'::(?:numeric|integer|float|vertex|edge|path)\b', '', raw)
                raw = raw.strip('"')
                if raw:
                    etf_codes.append(raw)

        if not etf_codes:
            log.warning("No ETF codes found")
            return

        log.info(f"Calculating returns for {len(etf_codes)} ETFs")

        # 2. 각 ETF 별 최신 종가 + 날짜 기반 수익률 계산
        update_items = []
        for code in etf_codes:
            try:
                rows = execute_cypher(cur, """
                    MATCH (e:ETF {code: $code})-[:HAS_PRICE]->(p:Price)
                    RETURN {date: p.date, close: p.close, market_cap: p.market_cap}
                    ORDER BY p.date DESC
                    LIMIT 45
                """, {'code': code})

                if not rows:
                    continue

                prices = []
                for r in rows:
                    parsed = json.loads(
                        re_mod.sub(r'::(?:numeric|integer|float|vertex|edge|path)\b', '', str(r[0]))
                    )
                    if parsed.get('close') is not None and parsed.get('date') is not None:
                        prices.append(parsed)

                if not prices:
                    continue

                latest_close = float(prices[0]['close'])
                if latest_close == 0:
                    continue

                latest_date = datetime.strptime(prices[0]['date'], '%Y-%m-%d')
                target_1w = (latest_date - timedelta(days=7)).strftime('%Y-%m-%d')
                target_1m = (latest_date - timedelta(days=30)).strftime('%Y-%m-%d')

                item = {'code': code, 'close_price': latest_close, 'return_1d': None, 'return_1w': None, 'return_1m': None, 'market_cap_change_1w': None}

                # 1D: index 1 (전거래일)
                if len(prices) > 1:
                    prev = float(prices[1]['close'])
                    if prev > 0:
                        item['return_1d'] = round((latest_close - prev) / prev * 100, 2)

                # 1W: 7일 전 이하에서 가장 가까운 거래일
                for p in prices[1:]:
                    if p['date'] <= target_1w:
                        prev = float(p['close'])
                        if prev > 0:
                            item['return_1w'] = round((latest_close - prev) / prev * 100, 2)
                        # 시가총액 변화율
                        latest_mc = prices[0].get('market_cap')
                        prev_mc = p.get('market_cap')
                        if latest_mc and prev_mc:
                            item['market_cap_change_1w'] = round((float(latest_mc) - float(prev_mc)) / float(prev_mc) * 100, 2)
                        break

                # 1M: 30일 전 이하에서 가장 가까운 거래일
                for p in prices[1:]:
                    if p['date'] <= target_1m:
                        prev = float(p['close'])
                        if prev > 0:
                            item['return_1m'] = round((latest_close - prev) / prev * 100, 2)
                        break

                update_items.append(item)

            except Exception as e:
                log.warning(f"Failed to calc returns for {code}: {e}")
                continue

        # 3. 배치 SET
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


def tag_new_etfs(**context):
    """신규 ETF에 룰 기반 태그 부여 (코스피200/코스닥150)"""
    import re

    from age_utils import INDEX_TAG_PATTERNS, RULE_ONLY_TAGS

    ti = context['ti']
    new_etfs = ti.xcom_pull(task_ids='filter_etf_list', key='new_etfs')

    if not new_etfs:
        log.info("No new ETFs to tag")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # Tag 노드 보장 (MERGE)
        tag_items = [{'name': t} for t in RULE_ONLY_TAGS]
        execute_cypher_batch(cur, """
            MERGE (t:Tag {name: item.name})
            RETURN t
        """, tag_items)

        # 룰 기반 매칭
        tagged_pairs = []
        for etf in new_etfs:
            for pattern, tag_name in INDEX_TAG_PATTERNS:
                if re.search(pattern, etf['name']):
                    tagged_pairs.append({'code': etf['code'], 'tag_name': tag_name})
                    break

        if tagged_pairs:
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                MATCH (t:Tag {name: item.tag_name})
                MERGE (e)-[:TAGGED]->(t)
                RETURN 1
            """, tagged_pairs)

        conn.commit()
        log.info(f"Tagged {len(tagged_pairs)}/{len(new_etfs)} new ETFs (rule-based)")

    finally:
        cur.close()
        conn.close()


# ──────────────────────────────────────────────
# DAG 태스크 정의
# ──────────────────────────────────────────────

start = EmptyOperator(task_id='start', dag=dag)
end = EmptyOperator(task_id='end', dag=dag)

task_fetch_krx_data = PythonOperator(
    task_id='fetch_krx_data',
    python_callable=fetch_krx_data,
    dag=dag,
)

task_filter_etf_list = PythonOperator(
    task_id='filter_etf_list',
    python_callable=filter_etf_list,
    dag=dag,
)

task_collect_holdings = PythonOperator(
    task_id='collect_holdings',
    python_callable=collect_holdings,
    dag=dag,
)

task_collect_prices = PythonOperator(
    task_id='collect_prices',
    python_callable=collect_prices,
    dag=dag,
)

task_detect_changes = PythonOperator(
    task_id='detect_portfolio_changes',
    python_callable=detect_portfolio_changes,
    dag=dag,
)

task_collect_stock_prices = PythonOperator(
    task_id='collect_stock_prices',
    python_callable=collect_stock_prices,
    dag=dag,
)

task_tag_new_etfs = PythonOperator(
    task_id='tag_new_etfs',
    python_callable=tag_new_etfs,
    dag=dag,
)

task_update_returns = PythonOperator(
    task_id='update_etf_returns',
    python_callable=update_etf_returns,
    dag=dag,
)

# 의존 관계:
# start → fetch_krx_data → filter_etf_list
#   → collect_holdings (HOLDS 엣지만, 배치)
#   |   → collect_stock_prices (배치)
#   |   → detect_portfolio_changes
#   → collect_prices (유니버스만, 배치)
#   |   → update_etf_returns (1D/1W/1M 수익률 계산)
#   → tag_new_etfs (신규 ETF 룰 기반 태깅)
# → end
start >> task_fetch_krx_data >> task_filter_etf_list
task_filter_etf_list >> [task_collect_holdings, task_collect_prices, task_tag_new_etfs]
task_collect_holdings >> [task_collect_stock_prices, task_detect_changes]
task_collect_prices >> task_update_returns
[task_collect_stock_prices, task_detect_changes, task_update_returns, task_tag_new_etfs] >> end
