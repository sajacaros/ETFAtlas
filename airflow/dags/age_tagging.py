"""
ETF 태그 전체 재구축 DAG (Apache AGE)

기존 TAGGED 관계 삭제 후, 룰 기반 + 키워드 + LLM 태깅으로 전체 재구축.
관리자가 수동 지정한 ETF(ETF.manual_tags)는 규칙/LLM을 건너뛰고 지정한 태그를 그대로 쓴다.
LLM_API_KEY 필요 (LiteLLM 프록시). 수동 트리거 또는 주간 스케줄.
"""

from datetime import datetime, timedelta
from airflow.sdk import DAG
from airflow.providers.standard.operators.python import PythonOperator
import logging

from age_utils import (
    get_db_connection, init_age, execute_cypher, execute_cypher_batch,
    _parse_age_value, INDEX_TAG_PATTERNS, RULE_ONLY_TAGS,
)

log = logging.getLogger(__name__)

ALLOWED_TAGS = [
    '반도체', 'AI', 'IT',
    '2차전지', '자동차', '로봇', '방산', '우주항공',
    '조선', '전력', '재생에너지', '원전', '소부장',
    '금융', '바이오',
    '커뮤니케이션', '게임', '엔터', '뷰티', '여행레저',
    '건설',
    '고배당', '주주환원', '그룹주',
]

# LLM/키워드 규칙에는 쓰지 않고 관리자 수동 지정(manual_tags)으로만 붙이는 태그.
# 우량주: 특정 테마 없이 대형 우량주를 소수만 골라 집중하는 ETF (지수를 폭넓게 따라가는 ETF는 코스피)
MANUAL_ONLY_TAGS = ['우량주']

default_args = {
    'owner': 'etf-atlas',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
    'email_on_failure': False,
}

dag = DAG(
    'age_tagging',
    default_args=default_args,
    description='ETF 태그 전체 재구축 (룰 + LLM)',
    schedule='0 3 * * 6',  # 토요일 03:00 KST
    catchup=False,
    tags=['etf', 'weekly', 'age', 'tagging'],
)


def tag_all_etfs(**context):
    """전체 ETF 태그 재구축: 룰 기반 + 키워드 + LLM

    안전한 교체 방식: 새 태그를 먼저 구축한 뒤 기존 TAGGED 관계를 삭제하고 교체.
    LLM 실패 시에도 기존 태그가 보존됨.
    """
    import os
    import json
    import re

    allowed_set = set(ALLOWED_TAGS)

    api_key = os.environ.get('LLM_API_KEY', '')
    if not api_key:
        log.warning("LLM_API_KEY not set, skipping ETF tagging")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # 1. 전체 ETF 목록
        all_etfs_result = execute_cypher(cur, "MATCH (e:ETF) RETURN e")
        all_etfs = {}
        manual_etfs = {}  # code → 관리자 지정 태그 (빈 리스트면 태그 없음)
        for row in all_etfs_result:
            if row[0]:
                raw = _parse_age_value(row[0])
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(data, dict):
                    props = data.get('properties', data)
                    code = props.get('code', '')
                    name = props.get('name', '')
                    if not code:
                        continue
                    if props.get('manual_tags') is not None:
                        manual_etfs[code] = props['manual_tags']
                    else:
                        all_etfs[code] = name

        if not all_etfs and not manual_etfs:
            log.info("No ETFs found")
            return

        log.info(f"Re-tagging {len(all_etfs)} ETFs (manual: {len(manual_etfs)} kept)")

        # 2. 인덱스 / 키워드 / LLM 분류
        KEYWORD_TAG_RULES = [
            (['반도체'], '반도체'),
            (['AI', '인공지능'], 'AI'),
            (['IT', '소프트웨어', '인터넷', '플랫폼', '메타버스'], 'IT'),
            (['2차전지', '배터리'], '2차전지'),
            (['자동차', '모빌리티'], '자동차'),
            (['로봇'], '로봇'),
            (['방산'], '방산'),
            (['우주', '항공'], '우주항공'),
            (['조선'], '조선'),
            (['전력'], '전력'),
            (['재생에너지', '신재생', '태양광', '풍력'], '재생에너지'),
            (['원전', '원자력'], '원전'),
            (['소부장', '소재', '부품', '장비'], '소부장'),
            (['금융', '은행', '보험', '증권'], '금융'),
            (['바이오', '헬스케어', '의료', '제약'], '바이오'),
            (['통신', '커뮤니케이션'], '커뮤니케이션'),
            (['게임'], '게임'),
            (['엔터', 'KPOP', 'K-POP', '미디어'], '엔터'),
            (['뷰티', '화장품'], '뷰티'),
            (['여행', '레저', '관광'], '여행레저'),
            (['건설'], '건설'),
            (['배당'], '고배당'),
            (['주주환원', '자사주', '밸류업'], '주주환원'),
            (['그룹', '지주'], '그룹주'),
        ]

        index_etfs = {}
        keyword_etfs = {}
        llm_etfs = {}

        for code, name in all_etfs.items():
            matched_tag = None
            for pattern, tag_name in INDEX_TAG_PATTERNS:
                if re.search(pattern, name):
                    matched_tag = tag_name
                    break
            if matched_tag:
                index_etfs[code] = matched_tag
                continue
            name_upper = name.upper()
            matched_tags = []
            for keywords, tag_name in KEYWORD_TAG_RULES:
                if any(kw.upper() in name_upper for kw in keywords):
                    matched_tags.append(tag_name)
            if matched_tags:
                keyword_etfs[code] = matched_tags
            else:
                llm_etfs[code] = name

        # ── 2-1. 수동 + 인덱스 + 키워드 태그 쌍 수집 (메모리) ──
        all_tag_pairs = [
            {'code': c, 'tag_name': t}
            for c, tags in manual_etfs.items() for t in tags
        ]

        if index_etfs:
            all_tag_pairs.extend(
                {'code': c, 'tag_name': t} for c, t in index_etfs.items()
            )
            log.info(f"Index ETFs matched: {len(index_etfs)}")

        if keyword_etfs:
            all_tag_pairs.extend(
                {'code': c, 'tag_name': t}
                for c, tags in keyword_etfs.items() for t in tags
            )
            log.info(f"Keyword ETFs matched: {len(keyword_etfs)}")

        # ── 2-2. LLM 태깅용 보유종목 조회 (최신 날짜만) ──
        # 최신 HOLDS 날짜 조회
        latest_holds_result = execute_cypher(cur, """
            MATCH ()-[h:HOLDS]->()
            WITH DISTINCT h.date AS d
            RETURN d ORDER BY d DESC LIMIT 1
        """)
        latest_holds_date = None
        if latest_holds_result and latest_holds_result[0][0]:
            latest_holds_date = _parse_age_value(latest_holds_result[0][0])

        etf_holdings = {}
        for code in llm_etfs:
            if latest_holds_date:
                holdings_result = execute_cypher(cur, """
                    MATCH (e:ETF {code: $code})-[h:HOLDS {date: $date}]->(s:Stock)
                    RETURN s.name
                    ORDER BY h.weight DESC
                    LIMIT 10
                """, {'code': code, 'date': latest_holds_date})
            else:
                holdings_result = []
            holdings = []
            for row in holdings_result:
                if row[0]:
                    stock_name = _parse_age_value(row[0])
                    if stock_name:
                        holdings.append(stock_name)
            etf_holdings[code] = holdings

        # ── 2-3. LLM 태깅 ──
        from openai import OpenAI
        from pydantic import BaseModel
        from enum import Enum

        TagEnum = Enum('TagEnum', {t: t for t in ALLOWED_TAGS})

        class ETFTagResult(BaseModel):
            code: str
            tags: list[TagEnum]

        class ETFTagBatchResult(BaseModel):
            results: list[ETFTagResult]

        client = OpenAI(
            base_url=os.environ.get('LLM_API_BASE', 'http://localhost:4000'),
            api_key=api_key,
        )
        llm_model = os.environ.get('LLM_MODEL', 'qwen38-27b')

        tags_str = ", ".join(ALLOWED_TAGS)
        system_prompt = f"""한국 주식시장 ETF 분류 전문가입니다.
ETF 이름과 주요 보유종목을 보고, 아래 고정 태그 목록에서 적절한 태그를 1~3개 선택하세요.

허용 태그 (이 목록에서만 선택):
{tags_str}

규칙:
- 반드시 위 목록에 있는 태그만 사용 (새로운 태그 생성 금지)
- 0~3개 태그를 선택
- 가장 핵심적인 테마/산업 태그를 우선 선택
- 시장 전체를 담는 ETF(대형주, 우량주, ESG 등)처럼 맞는 태그가 없으면 빈 목록을 반환"""

        few_shot_input = """- [091160] KODEX 반도체: 삼성전자, SK하이닉스, 한미반도체, 리노공업, ISC
- [364690] TIGER 2차전지테마: LG에너지솔루션, 삼성SDI, 에코프로비엠, 포스코퓨처엠
- [091170] KODEX 은행: KB금융, 신한지주, 하나금융지주, 우리금융지주, 기업은행
- [102780] KODEX 삼성그룹: 삼성전자, 삼성바이오로직스, 삼성물산, 삼성생명, 삼성SDI"""

        few_shot_output = json.dumps({"results": [
            {"code": "091160", "tags": ["반도체"]},
            {"code": "364690", "tags": ["2차전지", "소부장"]},
            {"code": "091170", "tags": ["금융"]},
            {"code": "102780", "tags": ["그룹주"]},
        ]}, ensure_ascii=False)

        def classify(etf_list: str, thinking: bool = True) -> ETFTagBatchResult:
            completion = client.chat.completions.parse(
                model=llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "다음 ETF들을 분류해주세요:\n\n" + few_shot_input},
                    {"role": "assistant", "content": few_shot_output},
                    {"role": "user", "content": "다음 ETF들을 분류해주세요:\n\n" + etf_list},
                ],
                response_format=ETFTagBatchResult,
                temperature=0,
                max_tokens=8192,  # 추론 모델: reasoning 토큰 포함
                extra_body=None if thinking else {
                    'chat_template_kwargs': {'enable_thinking': False}},
            )
            parsed = completion.choices[0].message.parsed
            if parsed is None:
                raise ValueError("LLM returned no parsable result")
            return parsed
        untagged_list = list(llm_etfs.items())
        batch_size = 5
        llm_tagged = 0

        for i in range(0, len(untagged_list), batch_size):
            batch = untagged_list[i:i + batch_size]
            etf_texts = []
            for code, name in batch:
                holdings = etf_holdings.get(code, [])
                holdings_str = (", ".join(holdings[:10])
                                if holdings else "보유종목 정보 없음")
                etf_texts.append(f"- [{code}] {name}: {holdings_str}")

            try:
                try:
                    result = classify("\n".join(etf_texts))
                except Exception as e:
                    # 추론이 토큰 한도를 다 쓰는 경우가 있어 추론 없이 한 번 더
                    log.warning(f"LLM batch {i // batch_size + 1} failed ({e}); retrying without thinking")
                    result = classify("\n".join(etf_texts), thinking=False)
                for etf_tag in result.results:
                    tag_values = [t.value for t in etf_tag.tags
                                  if t.value in allowed_set]
                    if not tag_values:
                        continue
                    for tag_name in tag_values:
                        all_tag_pairs.append({'code': etf_tag.code,
                                              'tag_name': tag_name})
                    llm_tagged += 1

                log.info(f"LLM batch {i // batch_size + 1}: {len(batch)} ETFs")
            except Exception as e:
                log.warning(f"Failed LLM batch {i // batch_size + 1}: {e}")

        # ── 3. 기존 태그 삭제 → 새 태그 일괄 적용 (단일 트랜잭션) ──
        execute_cypher(cur, """
            MATCH (e:ETF)-[r:TAGGED]->(t:Tag)
            DELETE r RETURN r
        """)
        execute_cypher(cur, """
            MATCH (t:Tag) DETACH DELETE t RETURN t
        """)

        all_tags = ALLOWED_TAGS + RULE_ONLY_TAGS + MANUAL_ONLY_TAGS
        tag_init_items = [{'name': t} for t in all_tags]
        execute_cypher_batch(cur, """
            MERGE (t:Tag {name: item.name}) RETURN t
        """, tag_init_items)

        if all_tag_pairs:
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                MATCH (t:Tag {name: item.tag_name})
                MERGE (e)-[:TAGGED]->(t) RETURN 1
            """, all_tag_pairs)

        conn.commit()
        total_tagged = len(index_etfs) + len(keyword_etfs) + llm_tagged
        log.info(f"Tagging complete: {total_tagged}/{len(all_etfs)} "
                 f"+ manual {len(manual_etfs)} "
                 f"(index: {len(index_etfs)}, keyword: {len(keyword_etfs)}, "
                 f"llm: {llm_tagged})")

    finally:
        cur.close()
        conn.close()


# ── DAG 태스크 정의 ──

PythonOperator(
    task_id='tag_all_etfs',
    python_callable=tag_all_etfs,
    execution_timeout=timedelta(minutes=30),
    dag=dag,
)
