"""
etf_tagging — ETF 테마 태그: 지수 규칙 → 이름 키워드 → LLM 순으로 분류하고 대상 ETF의 TAGGED를 교체한다
"""

import json
import logging
from enum import Enum

from pydantic import BaseModel

from age_db import age_cursor, execute_cypher, execute_cypher_batch, fetch_values, parse_age_value
from ai_config import load_ai_config
from market_calendar import now_kst
from rdb import get_db_connection
from universe import RULE_ONLY_TAGS, index_tag

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

LLM_BATCH_SIZE = 5  # LLM 한 번에 분류할 ETF 수
LLM_HOLDINGS = 10  # LLM에 넘기는 ETF별 비중 상위 구성종목 수
LLM_MAX_TOKENS = 8192  # 추론 모델: reasoning 토큰 포함

TAG_SYSTEM_PROMPT = f"""한국 주식시장 ETF 분류 전문가입니다.
ETF 이름과 주요 보유종목을 보고, 아래 고정 태그 목록에서 적절한 태그를 1~3개 선택하세요.

허용 태그 (이 목록에서만 선택):
{", ".join(ALLOWED_TAGS)}

규칙:
- 반드시 위 목록에 있는 태그만 사용 (새로운 태그 생성 금지)
- 0~3개 태그를 선택
- 가장 핵심적인 테마/산업 태그를 우선 선택
- 시장 전체를 담는 ETF(대형주, 우량주, ESG 등)처럼 맞는 태그가 없으면 빈 목록을 반환"""

TAG_FEW_SHOT_INPUT = """- [091160] KODEX 반도체: 삼성전자, SK하이닉스, 한미반도체, 리노공업, ISC
- [364690] TIGER 2차전지테마: LG에너지솔루션, 삼성SDI, 에코프로비엠, 포스코퓨처엠
- [091170] KODEX 은행: KB금융, 신한지주, 하나금융지주, 우리금융지주, 기업은행
- [102780] KODEX 삼성그룹: 삼성전자, 삼성바이오로직스, 삼성물산, 삼성생명, 삼성SDI"""

TAG_FEW_SHOT_OUTPUT = json.dumps({"results": [
    {"code": "091160", "tags": ["반도체"]},
    {"code": "364690", "tags": ["2차전지", "소부장"]},
    {"code": "091170", "tags": ["금융"]},
    {"code": "102780", "tags": ["그룹주"]},
]}, ensure_ascii=False)

TagEnum = Enum('TagEnum', {t: t for t in ALLOWED_TAGS})


class ETFTagResult(BaseModel):
    code: str
    tags: list[TagEnum]


class ETFTagBatchResult(BaseModel):
    results: list[ETFTagResult]


def split_targets(etf_rows, full_rebuild: bool) -> tuple[dict[str, str], dict[str, list], int]:
    """ETF 노드(agtype vertex 문자열) → (태깅 대상 code→name, 관리자 지정 code→태그, 이미 태깅돼 건너뛴 수).

    관리자가 지정한 ETF(manual_tags)는 지정한 태그를 그대로 쓰고, 나머지는 신규(tagged_at 없음)만 — 전체 재태깅이면 전부.
    """
    targets, manual, skipped = {}, {}, 0
    for raw in etf_rows:
        if not raw:
            continue
        try:
            data = json.loads(parse_age_value(raw))
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        props = data.get('properties', data)
        code = props.get('code', '')
        if not code:
            continue
        if props.get('manual_tags') is not None:
            manual[code] = props['manual_tags']
        elif full_rebuild or not props.get('tagged_at'):
            targets[code] = props.get('name', '')
        else:
            skipped += 1
    return targets, manual, skipped


def keyword_tags(name: str) -> list[str]:
    """이름에 든 키워드로 정한 태그들 (대소문자 무시)."""
    name_upper = name.upper()
    return [tag for keywords, tag in KEYWORD_TAG_RULES if any(kw.upper() in name_upper for kw in keywords)]


def classify_by_rules(etfs: dict[str, str]) -> tuple[dict[str, str], dict[str, list[str]], dict[str, str]]:
    """code→name을 (지수 태그 code→태그, 키워드 태그 code→태그들, LLM에 맡길 code→name)으로 나눈다."""
    index_etfs, keyword_etfs, llm_etfs = {}, {}, {}
    for code, name in etfs.items():
        if tag := index_tag(name):
            index_etfs[code] = tag
        elif tags := keyword_tags(name):
            keyword_etfs[code] = tags
        else:
            llm_etfs[code] = name
    return index_etfs, keyword_etfs, llm_etfs


def llm_batch_text(batch: list[tuple[str, str]], holdings: dict[str, list[str]]) -> str:
    """[(code, name)] → LLM에 넘길 "- [코드] 이름: 구성종목, ..." 줄들."""
    lines = []
    for code, name in batch:
        names = holdings.get(code, [])
        lines.append(f"- [{code}] {name}: " + (", ".join(names[:LLM_HOLDINGS]) if names else "보유종목 정보 없음"))
    return "\n".join(lines)


def accepted_tags(result: ETFTagBatchResult, batch_codes: set[str]) -> dict[str, list[str]]:
    """LLM 결과에서 이번 묶음의 코드·허용 태그만. 태그가 하나도 없는 ETF는 빠진다."""
    allowed = set(ALLOWED_TAGS)
    out = {}
    for etf_tag in result.results:
        if etf_tag.code not in batch_codes:  # LLM이 지어낸 코드
            continue
        tags = [t.value for t in etf_tag.tags if t.value in allowed]
        if tags:
            out[etf_tag.code] = tags
    return out


def classify_with_llm(client, model: str, etf_list: str, thinking: bool = True) -> ETFTagBatchResult:
    completion = client.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": TAG_SYSTEM_PROMPT},
            {"role": "user", "content": "다음 ETF들을 분류해주세요:\n\n" + TAG_FEW_SHOT_INPUT},
            {"role": "assistant", "content": TAG_FEW_SHOT_OUTPUT},
            {"role": "user", "content": "다음 ETF들을 분류해주세요:\n\n" + etf_list},
        ],
        response_format=ETFTagBatchResult,
        temperature=0,
        max_tokens=LLM_MAX_TOKENS,
        extra_body=None if thinking else {
            'chat_template_kwargs': {'enable_thinking': False}},
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("LLM returned no parsable result")
    return parsed


def tag_all_etfs(full_rebuild: bool = False):
    """대상 ETF 태깅: 룰 기반 + 키워드 + LLM. 대상은 신규 ETF(전체 재태깅이면 수동 지정 외 전부).

    새 태그를 메모리에 모두 구한 뒤 대상 ETF의 TAGGED만 교체한다.
    LLM이 실패한 ETF는 기존 태그를 그대로 두고 tagged_at도 남기지 않아 다음 실행에서 다시 시도한다.
    """
    from openai import OpenAI

    conn = get_db_connection()
    try:
        ai = load_ai_config(conn)
    finally:
        conn.close()
    if not ai['llm_api_key']:
        log.warning("LLM API key not set (admin page or LLM_API_KEY), skipping ETF tagging")
        return

    with age_cursor() as (conn, cur):
        # 1. 전체 ETF 목록
        all_etfs, manual_etfs, skipped = split_targets(
            [row[0] for row in execute_cypher(cur, "MATCH (e:ETF) RETURN e")], full_rebuild)
        if not all_etfs and not manual_etfs:
            log.info("No ETFs found")
            return

        log.info(f"Tagging {len(all_etfs)} ETFs (full_rebuild={full_rebuild}, "
                 f"already tagged: {skipped}, manual: {len(manual_etfs)})")

        # 2. 인덱스 / 키워드 / LLM 분류
        index_etfs, keyword_etfs, llm_etfs = classify_by_rules(all_etfs)

        # ── 2-1. 수동 + 인덱스 + 키워드 태그 쌍 수집 (메모리) ──
        all_tag_pairs = [
            {'code': c, 'tag_name': t}
            for c, tags in manual_etfs.items() for t in tags
        ]
        if index_etfs:
            all_tag_pairs.extend({'code': c, 'tag_name': t} for c, t in index_etfs.items())
            log.info(f"Index ETFs matched: {len(index_etfs)}")
        if keyword_etfs:
            all_tag_pairs.extend({'code': c, 'tag_name': t} for c, tags in keyword_etfs.items() for t in tags)
            log.info(f"Keyword ETFs matched: {len(keyword_etfs)}")

        # ── 2-2. LLM 태깅용 현재 보유종목 조회 ──
        etf_holdings = {code: fetch_values(cur, """
            MATCH (e:ETF {code: $code})-[h:CURRENT_HOLDS]->(s:Stock)
            RETURN s.name
            ORDER BY h.weight DESC
            LIMIT $limit
        """, {'code': code, 'limit': LLM_HOLDINGS}) for code in llm_etfs}
        conn.commit()  # LLM을 기다리는 동안 조회 트랜잭션을 열어 두지 않는다

        # ── 2-3. LLM 태깅 ──
        client = OpenAI(base_url=ai['llm_api_base'], api_key=ai['llm_api_key'])
        untagged_list = list(llm_etfs.items())
        llm_tagged = 0
        llm_failed = set()  # 이번에 태깅하지 못한 ETF — 기존 태그 유지, 다음 실행에서 재시도

        for i in range(0, len(untagged_list), LLM_BATCH_SIZE):
            batch = untagged_list[i:i + LLM_BATCH_SIZE]
            batch_no = i // LLM_BATCH_SIZE + 1
            etf_list = llm_batch_text(batch, etf_holdings)
            try:
                try:
                    result = classify_with_llm(client, ai['llm_model'], etf_list)
                except Exception as e:
                    # 추론이 토큰 한도를 다 쓰는 경우가 있어 추론 없이 한 번 더
                    log.warning(f"LLM batch {batch_no} failed ({e}); retrying without thinking")
                    result = classify_with_llm(client, ai['llm_model'], etf_list, thinking=False)
                for code, tags in accepted_tags(result, {code for code, _ in batch}).items():
                    all_tag_pairs.extend({'code': code, 'tag_name': t} for t in tags)
                    llm_tagged += 1
                log.info(f"LLM batch {batch_no}: {len(batch)} ETFs")
            except Exception as e:
                log.warning(f"Failed LLM batch {batch_no}: {e}")
                llm_failed.update(code for code, _ in batch)

        # ── 3. 대상 ETF의 TAGGED만 교체 (단일 트랜잭션) ──
        all_tags = ALLOWED_TAGS + RULE_ONLY_TAGS + MANUAL_ONLY_TAGS
        execute_cypher_batch(cur, """
            MERGE (t:Tag {name: item.name}) RETURN t
        """, [{'name': t} for t in all_tags])
        # 목록에서 빠진 태그 정리
        execute_cypher(cur, """
            MATCH (t:Tag) WHERE NOT t.name IN $names
            DETACH DELETE t RETURN 1
        """, {'names': all_tags})

        tagged_codes = [c for c in all_etfs if c not in llm_failed]
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})-[r:TAGGED]->(:Tag)
            DELETE r RETURN 1
        """, [{'code': c} for c in tagged_codes + list(manual_etfs)])
        all_tag_pairs = [p for p in all_tag_pairs if p['code'] not in llm_failed]
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})
            MATCH (t:Tag {name: item.tag_name})
            MERGE (e)-[:TAGGED]->(t) RETURN 1
        """, all_tag_pairs)
        execute_cypher_batch(cur, """
            MATCH (e:ETF {code: item.code})
            SET e.tagged_at = $today RETURN 1
        """, [{'code': c} for c in tagged_codes], params={'today': now_kst().strftime('%Y-%m-%d')})

        conn.commit()
        total_tagged = len(index_etfs) + len(keyword_etfs) + llm_tagged
        log.info(f"Tagging complete: {total_tagged}/{len(all_etfs)} "
                 f"+ manual {len(manual_etfs)} "
                 f"(index: {len(index_etfs)}, keyword: {len(keyword_etfs)}, "
                 f"llm: {llm_tagged}, llm failed: {len(llm_failed)})")
