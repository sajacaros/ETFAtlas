"""
ETF Graph Structure Rebuild DAG (Apache AGE)
- 주간 그래프 구조 재구축: ETF 메타데이터 + Stock/Market/Sector 구조 + LLM 태깅
- 스케줄: 매주 일요일 02:00 KST + 수동 트리거 가능

일일 sync_universe_age DAG에서 분리된 구조 재구축 전용 DAG.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
import logging

from age_utils import (
    get_db_connection, init_age, execute_cypher, execute_cypher_batch,
    get_company_from_etf_name,
    check_new_universe_candidates, get_krx_daily_data,
    get_valid_ticker_set,
    INDEX_TAG_PATTERNS, RULE_ONLY_TAGS,
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
    'rebuild_graph_age',
    default_args=default_args,
    description='ETF 그래프 구조 주간 재구축 (Apache AGE)',
    schedule_interval='0 2 * * 0',  # 일요일 02:00 KST
    catchup=False,
    tags=['etf', 'weekly', 'age', 'rebuild'],
)


# ──────────────────────────────────────────────
# Task 함수
# ──────────────────────────────────────────────

def fetch_krx_data(**context):
    """KRX API에서 최신 거래일 데이터 조회"""
    date = context['ds_nodash']
    ti = context['ti']

    krx_data, actual_date = get_krx_daily_data(date)
    ti.xcom_push(key='trading_date', value=actual_date)

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
        for item in krx_data
    ]


def filter_etf_list(**context):
    """AGE 기반 ETF 유니버스 필터링"""
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

                set_items = [{'code': c['code'], 'name': c['name']} for c in new_candidates]
                execute_cypher_batch(cur, """
                    MATCH (e:ETF {code: item.code})
                    SET e.name = item.name
                    RETURN e
                """, set_items)

                conn.commit()
                for c in new_candidates:
                    existing_codes.add(c['code'])
                log.info(f"Added {len(new_candidates)} new ETFs to universe (AGE)")

        universe_tickers = list(existing_codes)
        log.info(f"Total universe: {len(universe_tickers)} ETFs")
        return universe_tickers

    finally:
        cur.close()
        conn.close()


def collect_etf_metadata(**context):
    """ETF 메타데이터 배치 수집 및 AGE 저장 (KRX name 사용, pykrx 개별 조회 제거)"""
    from pykrx.website.krx.etx.core import ETF_전종목기본종목
    from math import ceil

    ti = context['ti']
    tickers = ti.xcom_pull(task_ids='filter_etf_list')
    krx_data_dicts = ti.xcom_pull(task_ids='fetch_krx_data')

    if not tickers:
        log.warning("No tickers to process")
        return

    # KRX 데이터에서 이름 맵 구성 (pykrx 개별 조회 제거)
    name_map = {}
    if krx_data_dicts:
        for item in krx_data_dicts:
            name_map[item['code']] = item['name']

    # ETF 전종목 기본정보 일괄 조회 (보수율 포함)
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

    try:
        now_iso = datetime.now().isoformat()

        # 1) ETF MERGE 배치
        etf_items = [{'code': t} for t in tickers]
        execute_cypher_batch(cur, """
            MERGE (e:ETF {code: item.code})
            RETURN e
        """, etf_items)

        # 2) ETF SET 배치 (name + updated_at + expense_ratio)
        set_items = []
        for ticker in tickers:
            name = name_map.get(ticker, ticker)
            expense_ratio = fee_map.get(ticker)
            set_items.append({
                'code': ticker,
                'name': name,
                'updated_at': now_iso,
                'expense_ratio': expense_ratio if expense_ratio is not None else -1,
                'has_fee': expense_ratio is not None,
            })

        # expense_ratio가 있는 것과 없는 것을 분리하여 배치
        items_with_fee = [i for i in set_items if i['has_fee']]
        items_no_fee = [i for i in set_items if not i['has_fee']]

        if items_with_fee:
            # has_fee 필드 제거 후 배치
            batch = [{'code': i['code'], 'name': i['name'],
                       'updated_at': i['updated_at'],
                       'expense_ratio': i['expense_ratio']} for i in items_with_fee]
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                SET e.name = item.name, e.updated_at = item.updated_at,
                    e.expense_ratio = item.expense_ratio
                RETURN e
            """, batch)

        if items_no_fee:
            batch = [{'code': i['code'], 'name': i['name'],
                       'updated_at': i['updated_at']} for i in items_no_fee]
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                SET e.name = item.name, e.updated_at = item.updated_at
                RETURN e
            """, batch)

        # 3) Company MERGE 배치
        company_items = []
        etf_company_pairs = []
        seen_companies = set()
        for ticker in tickers:
            name = name_map.get(ticker, ticker)
            company = get_company_from_etf_name(name)
            if company not in seen_companies:
                company_items.append({'name': company})
                seen_companies.add(company)
            etf_company_pairs.append({'code': ticker, 'company': company})

        execute_cypher_batch(cur, """
            MERGE (c:Company {name: item.name})
            RETURN c
        """, company_items)

        # 4) MANAGED_BY 관계 배치
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})
            MATCH (c:Company {name: item.company})
            MERGE (e)-[:MANAGED_BY]->(c)
            RETURN 1
        """, etf_company_pairs)

        conn.commit()
        fee_count = len(items_with_fee)
        log.info(f"Saved metadata for {len(tickers)} ETFs (expense_ratio: {fee_count})")

    finally:
        cur.close()
        conn.close()


def build_stock_structure(**context):
    """Stock/Market/Sector 노드 + 관계 배치 생성

    기존 collect_holdings의 구조 생성 부분을 분리하여 주간 실행.
    pykrx 업종 인덱스 API (~80 호출)로 섹터 맵 구축 후 배치 MERGE.
    """
    from pykrx import stock

    ti = context['ti']
    tickers = ti.xcom_pull(task_ids='filter_etf_list')
    trading_date = ti.xcom_pull(task_ids='fetch_krx_data', key='trading_date')

    if not tickers:
        log.warning("No tickers to process")
        return

    query_date = trading_date if trading_date else context['ds_nodash']

    # ETF 티커 목록 (보유종목이 ETF인지 확인용)
    etf_tickers = set(stock.get_etf_ticker_list(query_date))

    # 유효 종목코드 집합 (채권/파생/현금 제외)
    valid_tickers = get_valid_ticker_set(query_date)

    # ── 모든 ETF의 보유종목 코드 수집 (상장종목만, 최대 30개) ──
    import time
    all_stock_codes = set()
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
                all_stock_codes.update(str(c) for c in df.index)
            time.sleep(0.1)
        except Exception as e:
            log.warning(f"Failed to fetch holdings for {ticker}: {e}")

    log.info(f"Unique stock codes across all ETFs: {len(all_stock_codes)}")

    # ── 종목 이름 맵 구성 ──
    import pandas as pd
    name_map = {}
    for code in all_stock_codes:
        try:
            if code in etf_tickers:
                result = stock.get_etf_ticker_name(code)
            else:
                result = stock.get_market_ticker_name(code)
            if result and not isinstance(result, pd.DataFrame) and len(str(result)) > 0:
                name_map[code] = str(result)
            else:
                name_map[code] = code
        except Exception:
            name_map[code] = code

    # ── AGE 배치 생성 ──
    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # 1) Stock 노드 배치 MERGE + SET
        stock_items = [{'code': c} for c in all_stock_codes]
        execute_cypher_batch(cur, """
            MERGE (s:Stock {code: item.code})
            RETURN s
        """, stock_items)

        set_items = []
        for code in all_stock_codes:
            name = name_map.get(code, code)
            is_etf = code in etf_tickers
            set_items.append({'code': code, 'name': name, 'is_etf': is_etf})

        execute_cypher_batch(cur, """
            MATCH (s:Stock {code: item.code})
            SET s.name = item.name, s.is_etf = item.is_etf
            RETURN s
        """, set_items)

        conn.commit()
        log.info(f"Built stock structure: {len(all_stock_codes)} stocks")

    finally:
        cur.close()
        conn.close()


ALLOWED_TAGS = [
    '반도체', 'AI',
    '2차전지', '자동차', '로봇', '방산', '우주항공',
    '조선', '전력', '에너지', '산업재', '소재',
    '금융', '헬스케어', '바이오',
    '필수소비재', '경기소비재', '커뮤니케이션', '게임', '엔터', '뷰티', '럭셔리',
    '성장주', '가치주', '고배당',
]



def tag_new_etfs(**context):
    """Tag 미분류 ETF에 LLM 기반 태그 자동 부여 (고정 태그 리스트)"""
    import os
    import json as json_module
    import re

    def parse_agtype(value):
        """AGE agtype 값에서 타입 접미사 제거 후 JSON 파싱"""
        if not value:
            return None
        s = str(value)
        s = re.sub(r'::(?:vertex|edge|path|text|integer|float|boolean)\s*$', '', s)
        try:
            return json_module.loads(s)
        except (json_module.JSONDecodeError, ValueError):
            return s.strip('"')

    allowed_set = set(ALLOWED_TAGS)

    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        log.warning("OPENAI_API_KEY not set, skipping ETF tagging")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # 0. 기존 TAGGED 관계 전체 삭제 + Tag 노드 정리
        execute_cypher(cur, """
            MATCH (e:ETF)-[r:TAGGED]->(t:Tag)
            DELETE r
            RETURN r
        """)
        conn.commit()
        log.info("Deleted all existing TAGGED relationships")

        # 기존 Tag 노드 전체 삭제 (TAGGED 관계 삭제 후이므로 모두 고아)
        execute_cypher(cur, """
            MATCH (t:Tag)
            DETACH DELETE t
            RETURN t
        """)
        conn.commit()
        log.info("Deleted all old Tag nodes")

        # 고정 태그 노드 사전 생성 (MERGE) — 룰 기반 태그 포함
        all_tags = ALLOWED_TAGS + RULE_ONLY_TAGS
        tag_init_items = [{'name': t} for t in all_tags]
        execute_cypher_batch(cur, """
            MERGE (t:Tag {name: item.name})
            RETURN t
        """, tag_init_items)
        conn.commit()
        log.info(f"Ensured {len(all_tags)} fixed Tag nodes exist")

        # 1. 전체 ETF 목록 조회
        all_etfs_result = execute_cypher(cur, """
            MATCH (e:ETF)
            RETURN e
        """)
        all_etfs = {}
        for row in all_etfs_result:
            if row[0]:
                data = parse_agtype(row[0])
                if isinstance(data, dict):
                    props = data.get('properties', data)
                    code = props.get('code', '')
                    name = props.get('name', '')
                    if code:
                        all_etfs[code] = name

        if not all_etfs:
            log.info("No ETFs found in graph")
            return

        log.info(f"Re-tagging all {len(all_etfs)} ETFs with fixed tags")

        # 1-1. 인덱스 ETF 분리 (코스피200, 코스닥150)
        index_etfs = {}   # code -> tag_name
        llm_etfs = {}     # code -> name (LLM 태깅 대상)
        for code, name in all_etfs.items():
            matched_tag = None
            for pattern, tag_name in INDEX_TAG_PATTERNS:
                if re.search(pattern, name):
                    matched_tag = tag_name
                    break
            if matched_tag:
                index_etfs[code] = matched_tag
            else:
                llm_etfs[code] = name

        # 인덱스 ETF 직접 태깅 (LLM 호출 없이)
        if index_etfs:
            index_pairs = [{'code': c, 'tag_name': t}
                           for c, t in index_etfs.items()]
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                MATCH (t:Tag {name: item.tag_name})
                MERGE (e)-[:TAGGED]->(t)
                RETURN 1
            """, index_pairs)
            conn.commit()
            log.info(f"Index ETFs tagged directly: {len(index_etfs)} "
                     f"(코스피200: {sum(1 for t in index_etfs.values() if t == '코스피200')}, "
                     f"코스닥150: {sum(1 for t in index_etfs.values() if t == '코스닥150')})")

        # 2. LLM 태깅 대상 ETF의 보유종목 TOP 10 조회
        etf_holdings = {}
        for code in llm_etfs:
            holdings_result = execute_cypher(cur, """
                MATCH (e:ETF {code: $code})-[h:HOLDS]->(s:Stock)
                RETURN s.name
                ORDER BY h.weight DESC
                LIMIT 10
            """, {'code': code})

            holdings = []
            for row in holdings_result:
                if row[0]:
                    stock_name = parse_agtype(row[0])
                    if stock_name and isinstance(stock_name, str):
                        holdings.append(stock_name)
            etf_holdings[code] = holdings

        # 3. LLM 배치 호출
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate
        from pydantic import BaseModel, field_validator
        from enum import Enum

        TagEnum = Enum('TagEnum', {t: t for t in ALLOWED_TAGS})

        class ETFTagResult(BaseModel):
            code: str
            tags: list[TagEnum]

        class ETFTagBatchResult(BaseModel):
            results: list[ETFTagResult]

        llm = ChatOpenAI(
            model="gpt-4.1-mini",
            temperature=0,
            api_key=api_key,
        )
        structured_llm = llm.with_structured_output(ETFTagBatchResult)

        tags_str = ", ".join(ALLOWED_TAGS)
        system_prompt = f"""한국 주식시장 ETF 분류 전문가입니다.
ETF 이름과 주요 보유종목을 보고, 아래 고정 태그 목록에서 적절한 태그를 1~3개 선택하세요.

허용 태그 (이 목록에서만 선택):
{tags_str}

규칙:
- 반드시 위 목록에 있는 태그만 사용 (새로운 태그 생성 금지)
- 1~3개 태그를 선택
- 가장 핵심적인 테마/산업 태그를 우선 선택
- 해당되는 태그가 없으면 가장 가까운 태그를 선택"""

        few_shot_input = """- [069500] KODEX 반도체: 삼성전자, SK하이닉스, 한미반도체, 리노공업, ISC
- [364690] TIGER 2차전지테마: LG에너지솔루션, 삼성SDI, 에코프로비엠, 포스코퓨처엠
- [091170] KODEX 은행: KB금융, 신한지주, 하나금융지주, 우리금융지주, 기업은행"""

        few_shot_output = """[069500] → 반도체
[364690] → 2차전지, 소재
[091170] → 금융"""

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "다음 ETF들을 분류해주세요:\n\n" + few_shot_input),
            ("ai", few_shot_output),
            ("human", "다음 ETF들을 분류해주세요:\n\n{etf_list}"),
        ])

        chain = prompt | structured_llm

        # 10개씩 배치 처리
        untagged_list = list(llm_etfs.items())
        batch_size = 10
        total_tagged = 0

        for i in range(0, len(untagged_list), batch_size):
            batch = untagged_list[i:i + batch_size]

            etf_texts = []
            for code, name in batch:
                holdings = etf_holdings.get(code, [])
                holdings_str = (", ".join(holdings[:10])
                                if holdings else "보유종목 정보 없음")
                etf_texts.append(f"- [{code}] {name}: {holdings_str}")

            etf_list_text = "\n".join(etf_texts)

            try:
                result = chain.invoke({"etf_list": etf_list_text})

                # Tag TAGGED 관계 배치 저장
                tagged_pairs = []
                for etf_tag in result.results:
                    tag_values = [t.value for t in etf_tag.tags
                                  if t.value in allowed_set]
                    if not tag_values:
                        log.warning(f"No valid tags for {etf_tag.code}, skipping")
                        continue
                    for tag_name in tag_values:
                        tagged_pairs.append({
                            'code': etf_tag.code,
                            'tag_name': tag_name
                        })
                    total_tagged += 1

                if tagged_pairs:
                    execute_cypher_batch(cur, """
                        MATCH (e:ETF {code: item.code})
                        MATCH (t:Tag {name: item.tag_name})
                        MERGE (e)-[:TAGGED]->(t)
                        RETURN 1
                    """, tagged_pairs)

                conn.commit()
                log.info(f"Tagged batch {i // batch_size + 1}: {len(batch)} ETFs")

            except Exception as e:
                log.warning(f"Failed to tag batch {i // batch_size + 1}: {e}")
                conn.rollback()
                cur = init_age(conn)
                continue

        total_tagged += len(index_etfs)
        log.info(f"ETF tagging complete. Tagged: {total_tagged}/{len(all_etfs)} "
                 f"(index: {len(index_etfs)}, llm: {total_tagged - len(index_etfs)})")

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

task_collect_metadata = PythonOperator(
    task_id='collect_etf_metadata',
    python_callable=collect_etf_metadata,
    dag=dag,
)

task_build_structure = PythonOperator(
    task_id='build_stock_structure',
    python_callable=build_stock_structure,
    dag=dag,
)

task_tag_new_etfs = PythonOperator(
    task_id='tag_new_etfs',
    python_callable=tag_new_etfs,
    dag=dag,
)

# 의존 관계:
# start → fetch_krx_data → filter_etf_list
#   → collect_etf_metadata (배치화)
#   → build_stock_structure (Stock/Market/Sector 배치 생성)
#   → tag_new_etfs (LLM 태깅)
# → end
start >> task_fetch_krx_data >> task_filter_etf_list
task_filter_etf_list >> task_collect_metadata >> task_build_structure >> task_tag_new_etfs >> end
