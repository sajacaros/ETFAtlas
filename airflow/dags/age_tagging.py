"""
ETF 태깅 DAG (Apache AGE)

아직 자동 태깅되지 않은 ETF(ETF.tagged_at 없음, 즉 신규 편입)만 룰 기반 + 키워드 + LLM으로 태깅한다.
이미 태깅된 ETF는 매주 다시 LLM에 돌리지 않는다 — LLM 결과가 실행마다 달라 태그가 흔들리기 때문.
규칙이나 태그 목록을 바꿨으면 params.full_rebuild=true로 수동 실행해 전체를 다시 태깅한다.
관리자가 수동 지정한 ETF(ETF.manual_tags)는 규칙/LLM을 건너뛰고 지정한 태그를 그대로 쓴다.
LLM_API_KEY 필요 (LiteLLM 프록시). 수동 트리거 또는 주간 스케줄.
"""

from datetime import datetime, timedelta
from airflow.sdk import DAG, Param
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
# 우량주: 산업 테마 없이 선별 기준(시가총액 상위, 성장성, ESG 등)으로 대형주를 골라 담는 ETF (지수를 폭넓게 따라가는 ETF는 코스피)
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
    description='신규 ETF 태깅 (룰 + LLM), full_rebuild로 전체 재태깅',
    schedule='0 3 * * 6',  # 토요일 03:00 KST
    catchup=False,
    params={'full_rebuild': Param(False, type='boolean',
                                  description='이미 태깅된 ETF까지 전체 다시 태깅')},
    tags=['etf', 'weekly', 'age', 'tagging'],
)


def tag_all_etfs(**context):
    """대상 ETF 태깅: 룰 기반 + 키워드 + LLM. 대상은 신규 ETF(전체 재태깅이면 수동 지정 외 전부).

    새 태그를 메모리에 모두 구한 뒤 대상 ETF의 TAGGED만 교체한다.
    LLM이 실패한 ETF는 기존 태그를 그대로 두고 tagged_at도 남기지 않아 다음 실행에서 다시 시도한다.
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
        full_rebuild = bool(context['params'].get('full_rebuild'))
        all_etfs = {}  # 태깅 대상: code → name
        manual_etfs = {}  # code → 관리자 지정 태그 (빈 리스트면 태그 없음)
        skipped = 0
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
                    elif full_rebuild or not props.get('tagged_at'):
                        all_etfs[code] = name
                    else:
                        skipped += 1

        if not all_etfs and not manual_etfs:
            log.info("No ETFs found")
            return

        log.info(f"Tagging {len(all_etfs)} ETFs (full_rebuild={full_rebuild}, "
                 f"already tagged: {skipped}, manual: {len(manual_etfs)})")

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

        # ── 2-2. LLM 태깅용 현재 보유종목 조회 ──
        etf_holdings = {}
        for code in llm_etfs:
            holdings_result = execute_cypher(cur, """
                MATCH (e:ETF {code: $code})-[h:CURRENT_HOLDS]->(s:Stock)
                RETURN s.name
                ORDER BY h.weight DESC
                LIMIT 10
            """, {'code': code})
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
        llm_failed = set()  # 이번에 태깅하지 못한 ETF — 기존 태그 유지, 다음 실행에서 재시도

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
                batch_codes = {code for code, _ in batch}
                for etf_tag in result.results:
                    if etf_tag.code not in batch_codes:  # LLM이 지어낸 코드
                        continue
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
                llm_failed.update(code for code, _ in batch)

        # ── 3. 대상 ETF의 TAGGED만 교체 (단일 트랜잭션) ──
        all_tags = ALLOWED_TAGS + RULE_ONLY_TAGS + MANUAL_ONLY_TAGS
        execute_cypher_batch(cur, """
            MERGE (t:Tag {name: item.name}) RETURN t
        """, [{'name': t} for t in all_tags])
        # 목록에서 빠진 태그 정리
        execute_cypher(cur, f"""
            MATCH (t:Tag) WHERE NOT t.name IN {json.dumps(all_tags, ensure_ascii=False)}
            DETACH DELETE t RETURN 1
        """)

        tagged_codes = [c for c in all_etfs if c not in llm_failed]
        replace_items = [{'code': c} for c in tagged_codes + list(manual_etfs)]
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})-[r:TAGGED]->(:Tag)
            DELETE r RETURN 1
        """, replace_items)
        all_tag_pairs = [p for p in all_tag_pairs if p['code'] not in llm_failed]
        if all_tag_pairs:
            execute_cypher_batch(cur, """
                MATCH (e:ETF {code: item.code})
                MATCH (t:Tag {name: item.tag_name})
                MERGE (e)-[:TAGGED]->(t) RETURN 1
            """, all_tag_pairs)

        today = datetime.now().strftime('%Y-%m-%d')
        execute_cypher_batch(cur, f"""
            MATCH (e:ETF {{code: item.code}})
            SET e.tagged_at = '{today}' RETURN 1
        """, [{'code': c} for c in tagged_codes])

        conn.commit()
        total_tagged = len(index_etfs) + len(keyword_etfs) + llm_tagged
        log.info(f"Tagging complete: {total_tagged}/{len(all_etfs)} "
                 f"+ manual {len(manual_etfs)} "
                 f"(index: {len(index_etfs)}, keyword: {len(keyword_etfs)}, "
                 f"llm: {llm_tagged}, llm failed: {len(llm_failed)})")

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
