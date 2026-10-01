"""챗봇 few-shot 예시 원본 (질문 유형 → 도구 호출 순서).

`code`는 도구 호출을 한 줄에 하나씩 적은 것이다. 챗봇 로그 승인 시 저장되는 형식과 같다.
고유명사는 <종목명>, <ETF명>, <운용사> 같은 자리표시자로 두고, 앞 호출 결과를 쓰는 자리는
<…의 code>처럼 적는다. 태그 이름은 고정 목록이라 그대로 쓴다.

`python docker/db/seed/code_examples.py > docker/db/init/03_seed_code_examples.sql`로 SQL을 만든다.
"""

EXAMPLES = [
    # ── 태그 ──
    {
        "question": "반도체 ETF 3개의 가격 추이를 비교해줘",
        "description": "태그 → 순자산 상위 N개 → ETF별 가격 조회",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY e.net_assets DESC LIMIT 3")
# 결과 ETF마다
get_etf_prices(etf_code="<ETF의 code>", period="1m")""",
    },
    {
        "question": "AI이면서 반도체인 ETF를 알려줘",
        "description": "두 태그를 모두 가진 ETF (태그 교집합)",
        "code": """\
graph_query(cypher="MATCH (t1:Tag {name: 'AI'})<-[:TAGGED]-(e:ETF)-[:TAGGED]->(t2:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, net_assets: e.net_assets} ORDER BY e.net_assets DESC")""",
    },
    {
        "question": "2차전지 ETF 중 보수율 낮은 3개와 높은 3개를 비교해줘",
        "description": "태그 ETF를 보수율 오름차순/내림차순으로 각각 조회",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '2차전지'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 3")
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '2차전지'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio DESC LIMIT 3")""",
    },
    {
        "question": "배당 ETF와 반도체 ETF를 하나씩 추천하고 비교해줘",
        "description": "태그별 대표 ETF 1개씩 → compare_etfs",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag) WHERE t.name IN ['고배당', '반도체'] WITH t, e ORDER BY e.net_assets DESC WITH t, head(collect(e)) AS top RETURN {tag: t.name, code: top.code, name: top.name}")
compare_etfs(etf_codes="<고배당 ETF의 code>,<반도체 ETF의 code>")""",
    },
    {
        "question": "바이오 ETF 중 수익률 1등과 금융 ETF 중 수익률 1등을 비교해줘",
        "description": "태그별 1개월 수익률 1위 → compare_etfs",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag) WHERE t.name IN ['바이오', '금융'] AND e.return_1m IS NOT NULL WITH t, e ORDER BY e.return_1m DESC WITH t, head(collect(e)) AS top RETURN {tag: t.name, code: top.code, name: top.name, return_1m: top.return_1m}")
compare_etfs(etf_codes="<바이오 ETF의 code>,<금융 ETF의 code>")""",
    },
    {
        "question": "방산 ETF 전체의 상세 정보와 가격을 알려줘",
        "description": "태그 ETF 전체 → ETF별 상세 + 가격",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '방산'}) RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC")
# 결과 ETF마다
get_etf_info(etf_code="<ETF의 code>")
get_etf_prices(etf_code="<ETF의 code>", period="1m")""",
    },
    {
        "question": "AI 관련 ETF들의 보유종목 변동을 한번에 확인해줘",
        "description": "태그 ETF → ETF별 보유종목 변동",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: 'AI'}) RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC")
# 결과 ETF마다
get_holdings_changes(etf_code="<ETF의 code>", period="1w")""",
    },
    {
        "question": "반도체 ETF들의 보수율 통계와 추천 ETF를 알려줘",
        "description": "태그 ETF 보수율 집계(min/max/avg) + 보수율 낮은 순",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '반도체'}) RETURN {count: count(e), min_fee: min(e.expense_ratio), max_fee: max(e.expense_ratio), avg_fee: avg(e.expense_ratio)}")
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, net_assets: e.net_assets} ORDER BY e.expense_ratio ASC LIMIT 5")""",
    },
    {
        "question": "금융 ETF 3개의 보유종목 상위 5개를 한눈에 비교해줘",
        "description": "태그 상위 N개 ETF의 최신 보유종목 상위 M개 (ETF별 collect)",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '금융'}) WITH e ORDER BY e.net_assets DESC LIMIT 3 MATCH (e)-[h:HOLDS]->(s:Stock) WITH e, s, h ORDER BY h.date DESC WITH e, s, head(collect(h)) AS latest WITH e, s, latest ORDER BY latest.weight DESC WITH e, collect({stock: s.name, weight: latest.weight}) AS holdings RETURN {code: e.code, name: e.name, top5: holdings[0..5]}")""",
    },
    # ── 종목 → ETF (HOLDS) ──
    {
        "question": "삼성전자를 보유한 ETF 중 보수율이 낮은 3개의 상세 정보를 알려줘",
        "description": "종목 이름으로 보유 ETF(최신 HOLDS) → 보수율순 → 상세",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[h:HOLDS]->(s:Stock {name: '<종목명>'}) WITH e, h ORDER BY h.date DESC WITH e, head(collect(h)) AS latest RETURN {code: e.code, name: e.name, weight: latest.weight, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 3")
# 결과 ETF마다
get_etf_info(etf_code="<ETF의 code>")""",
    },
    {
        "question": "삼성전자를 가장 많이 담은 ETF를 알려줘",
        "description": "종목 이름으로 보유 ETF(최신 HOLDS) → 비중순",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[h:HOLDS]->(s:Stock {name: '<종목명>'}) WITH e, h ORDER BY h.date DESC WITH e, head(collect(h)) AS latest RETURN {code: e.code, name: e.name, weight: latest.weight, expense_ratio: e.expense_ratio} ORDER BY latest.weight DESC LIMIT 10")""",
    },
    {
        "question": "삼성전자와 SK하이닉스가 많이 들어있는 ETF를 수수료순으로 정렬해줘",
        "description": "여러 종목을 모두 보유한 ETF → 합산 비중 → 보수율순",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[h:HOLDS]->(s:Stock) WHERE s.name IN ['<종목명1>', '<종목명2>'] WITH e, s, h ORDER BY h.date DESC WITH e, s, head(collect(h)) AS latest WITH e, count(s) AS matched, sum(latest.weight) AS weight_sum WHERE matched = 2 RETURN {code: e.code, name: e.name, weight_sum: weight_sum, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC, weight_sum DESC LIMIT 10")""",
    },
    {
        "question": "삼성전자와 SK하이닉스를 동시에 보유한 ETF 중 보수율이 가장 낮은 3개 상세 정보",
        "description": "여러 종목 동시 보유(matched = 종목 수) → 보수율순 → 상세",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[h:HOLDS]->(s:Stock) WHERE s.name IN ['<종목명1>', '<종목명2>'] WITH e, s, h ORDER BY h.date DESC WITH e, s, head(collect(h)) AS latest WITH e, count(s) AS matched, sum(latest.weight) AS weight_sum WHERE matched = 2 RETURN {code: e.code, name: e.name, weight_sum: weight_sum, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 3")
# 결과 ETF마다
get_etf_info(etf_code="<ETF의 code>")""",
    },
    {
        "question": "반도체 3대장 합산 비중이 높은 ETF를 알려줘",
        "description": "여러 종목 합산 비중순 (일부만 보유해도 포함)",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[h:HOLDS]->(s:Stock) WHERE s.name IN ['<종목명1>', '<종목명2>', '<종목명3>'] WITH e, s, h ORDER BY h.date DESC WITH e, s, head(collect(h)) AS latest WITH e, sum(latest.weight) AS weight_sum, collect(s.name) AS stocks RETURN {code: e.code, name: e.name, weight_sum: weight_sum, stocks: stocks} ORDER BY weight_sum DESC LIMIT 10")""",
    },
    {
        "question": "삼성전자를 10% 이상 보유한 ETF들의 최근 수익률을 비교해줘",
        "description": "종목 비중 조건(WHERE latest.weight >= N) → 수익률",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[h:HOLDS]->(s:Stock {name: '<종목명>'}) WITH e, h ORDER BY h.date DESC WITH e, head(collect(h)) AS latest WHERE latest.weight >= 10 RETURN {code: e.code, name: e.name, weight: latest.weight, return_1w: e.return_1w, return_1m: e.return_1m} ORDER BY e.return_1m DESC")""",
    },
    {
        "question": "SK하이닉스를 보유한 ETF 중 수익률이 좋은 3개의 가격 추이를 보여줘",
        "description": "종목 보유 ETF → 수익률순 → ETF별 가격",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[h:HOLDS]->(s:Stock {name: '<종목명>'}) WHERE e.return_1m IS NOT NULL WITH e, h ORDER BY h.date DESC WITH e, head(collect(h)) AS latest RETURN {code: e.code, name: e.name, weight: latest.weight, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 3")
# 결과 ETF마다
get_etf_prices(etf_code="<ETF의 code>", period="1m")""",
    },
    {
        "question": "삼성전자 주가와 삼성전자를 가장 많이 보유한 ETF 3개의 가격을 비교해줘",
        "description": "종목 코드 확인 → 종목 가격 + 보유 비중 상위 ETF 가격",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[h:HOLDS]->(s:Stock {name: '<종목명>'}) WITH e, s, h ORDER BY h.date DESC WITH e, s, head(collect(h)) AS latest RETURN {stock_code: s.code, code: e.code, name: e.name, weight: latest.weight} ORDER BY latest.weight DESC LIMIT 3")
get_stock_prices(stock_code="<결과의 stock_code>", period="1m")
# 결과 ETF마다
get_etf_prices(etf_code="<ETF의 code>", period="1m")""",
    },
    {
        "question": "삼성전자 주가와 반도체 ETF 수익률을 비교해줘",
        "description": "종목 가격 + 태그 ETF 수익률",
        "code": """\
stock_search(query="<종목명>")
get_stock_prices(stock_code="<종목의 code>", period="1m")
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, return_1w: e.return_1w, return_1m: e.return_1m} ORDER BY e.net_assets DESC LIMIT 5")""",
    },
    {
        "question": "삼성전자가 많이 포함된 테마(태그)는 뭐야? 각 태그별 대표 ETF도 알려줘",
        "description": "종목 보유 ETF의 태그 분포(태그별 ETF 수, 평균 비중) + 태그별 비중 1위 ETF",
        "code": """\
graph_query(cypher="MATCH (t:Tag)<-[:TAGGED]-(e:ETF)-[h:HOLDS]->(s:Stock {name: '<종목명>'}) WITH t, e, h ORDER BY h.date DESC WITH t, e, head(collect(h)) AS latest WITH t, e, latest ORDER BY latest.weight DESC WITH t, count(e) AS etf_count, avg(latest.weight) AS avg_weight, head(collect(e.name)) AS top_etf RETURN {tag: t.name, etf_count: etf_count, avg_weight: avg_weight, top_etf: top_etf} ORDER BY etf_count DESC")""",
    },
    # ── ETF → 보유종목 / 유사 ETF ──
    {
        "question": "KODEX 200의 보유종목 상위 10개를 알려줘",
        "description": "ETF 이름으로 최신 보유종목 비중순",
        "code": """\
graph_query(cypher="MATCH (e:ETF {name: '<ETF명>'})-[h:HOLDS]->(s:Stock) WITH s, h ORDER BY h.date DESC WITH s, head(collect(h)) AS latest RETURN {stock_code: s.code, stock_name: s.name, weight: latest.weight} ORDER BY latest.weight DESC LIMIT 10")""",
    },
    {
        "question": "KODEX 200과 TIGER 200의 공통 보유종목 비중을 비교해줘",
        "description": "두 ETF가 함께 보유한 종목과 각각의 비중",
        "code": """\
graph_query(cypher="MATCH (a:ETF {name: '<ETF명1>'})-[ha:HOLDS]->(s:Stock)<-[hb:HOLDS]-(b:ETF {name: '<ETF명2>'}) WITH s, ha, hb ORDER BY ha.date DESC, hb.date DESC WITH s, head(collect(ha)) AS la, head(collect(hb)) AS lb RETURN {stock: s.name, weight_a: la.weight, weight_b: lb.weight} ORDER BY la.weight DESC")""",
    },
    {
        "question": "KODEX 200과 유사한 ETF 5개의 상세 정보를 비교해줘",
        "description": "ETF 코드 확인 → 유사 ETF → compare_etfs",
        "code": """\
etf_search(query="<ETF명>")
find_similar_etfs(etf_code="<ETF의 code>")
compare_etfs(etf_codes="<유사 ETF 5개의 code, 쉼표 구분>")""",
    },
    {
        "question": "최근 1주 수익률 상위 3개 ETF의 보유종목과 유사 ETF를 알려줘",
        "description": "수익률 상위 ETF → ETF별 상세(보유종목) + 유사 ETF",
        "code": """\
graph_query(cypher="MATCH (e:ETF) WHERE e.return_1w IS NOT NULL RETURN {code: e.code, name: e.name, return_1w: e.return_1w} ORDER BY e.return_1w DESC LIMIT 3")
# 결과 ETF마다
get_etf_info(etf_code="<ETF의 code>")
find_similar_etfs(etf_code="<ETF의 code>")""",
    },
    # ── 보유종목 변동 (HOLDS 날짜 비교) ──
    {
        "question": "최근 신규 편입된 종목이 있는 ETF를 알려줘",
        "description": "기준 ETF(069500)로 최근 두 수집일 확인 → 최신 날짜에만 있는 보유 관계",
        "code": """\
graph_query(cypher="MATCH (e:ETF {code: '069500'})-[h:HOLDS]->() WITH DISTINCT h.date AS d ORDER BY d DESC LIMIT 2 WITH collect(d) AS ds WHERE size(ds) = 2 MATCH (e:ETF)-[h:HOLDS]->(s:Stock) WHERE h.date = ds[0] AND NOT EXISTS((e)-[:HOLDS {date: ds[1]}]->(s)) RETURN {code: e.code, name: e.name, stock: s.name, weight: h.weight} ORDER BY h.weight DESC LIMIT 20")""",
    },
    {
        "question": "삼성전자 비중이 늘어난 ETF를 알려줘",
        "description": "종목의 ETF별 HOLDS 이력 → 최신 vs 직전 비중 비교",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[h:HOLDS]->(s:Stock {name: '<종목명>'}) WITH e, h ORDER BY h.date DESC WITH e, collect(h) AS hs WHERE size(hs) >= 2 WITH e, hs[0] AS cur, hs[1] AS prev WHERE cur.weight > prev.weight RETURN {code: e.code, name: e.name, prev_date: prev.date, prev_weight: prev.weight, date: cur.date, weight: cur.weight, change: cur.weight - prev.weight} ORDER BY cur.weight - prev.weight DESC")""",
    },
    {
        "question": "KoAct 바이오헬스케어에서 알테오젠 비중이 급변한 시점을 분석해줘",
        "description": "ETF-종목 HOLDS 날짜별 이력 (변화량 계산은 응답에서)",
        "code": """\
graph_query(cypher="MATCH (e:ETF {name: '<ETF명>'})-[h:HOLDS]->(s:Stock {name: '<종목명>'}) RETURN {date: h.date, weight: h.weight, shares: h.shares} ORDER BY h.date")""",
    },
    # ── ETF 속성 정렬 / 필터 / 집계 ──
    {
        "question": "순자산 100억 이상 ETF 중 보수율이 낮은 ETF를 알려줘",
        "description": "ETF 속성 조건(순자산은 원 단위) → 보수율순",
        "code": """\
graph_query(cypher="MATCH (e:ETF) WHERE e.net_assets >= 10000000000 RETURN {code: e.code, name: e.name, net_assets: e.net_assets, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 10")""",
    },
    {
        "question": "보수율 낮으면서 수익률 좋은 ETF를 추천해줘",
        "description": "보수율 상한 조건 + 수익률순",
        "code": """\
graph_query(cypher="MATCH (e:ETF) WHERE e.expense_ratio <= 0.1 AND e.return_1m IS NOT NULL RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 10")""",
    },
    {
        "question": "1주 수익률과 1개월 수익률 차이가 큰 ETF를 알려줘",
        "description": "두 속성의 차이를 Cypher에서 계산해 정렬",
        "code": """\
graph_query(cypher="MATCH (e:ETF) WHERE e.return_1w IS NOT NULL AND e.return_1m IS NOT NULL WITH e, abs(e.return_1w - e.return_1m) AS gap RETURN {code: e.code, name: e.name, return_1w: e.return_1w, return_1m: e.return_1m, gap: gap} ORDER BY gap DESC LIMIT 10")""",
    },
    {
        "question": "최근 시가총액이 가장 많이 늘어난 ETF 5개를 알려줘",
        "description": "ETF 속성(market_cap_change_1w) 정렬",
        "code": """\
graph_query(cypher="MATCH (e:ETF) WHERE e.market_cap_change_1w IS NOT NULL RETURN {code: e.code, name: e.name, market_cap_change_1w: e.market_cap_change_1w} ORDER BY e.market_cap_change_1w DESC LIMIT 5")""",
    },
    {
        "question": "순자산 상위 5개 ETF의 최근 1주 가격과 보유종목 변동을 알려줘",
        "description": "순자산순 → ETF별 가격 + 보유종목 변동",
        "code": """\
graph_query(cypher="MATCH (e:ETF) RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY e.net_assets DESC LIMIT 5")
# 결과 ETF마다
get_etf_prices(etf_code="<ETF의 code>", period="1w")
get_holdings_changes(etf_code="<ETF의 code>", period="1w")""",
    },
    {
        "question": "거래량이 가장 많은 ETF 5개를 알려줘",
        "description": "ETF별 최신 Price 노드 → 거래량순",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:HAS_PRICE]->(p:Price) WITH e, p ORDER BY p.date DESC WITH e, head(collect(p)) AS latest RETURN {code: e.code, name: e.name, date: latest.date, volume: latest.volume, trade_value: latest.trade_value} ORDER BY latest.volume DESC LIMIT 5")""",
    },
    {
        "question": "KODEX ETF 중 순자산이 가장 큰 5개와 가장 작은 5개를 비교해줘",
        "description": "이름 접두어(브랜드) 필터 → 순자산 상/하위",
        "code": """\
graph_query(cypher="MATCH (e:ETF) WHERE e.name STARTS WITH 'KODEX' RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY e.net_assets DESC LIMIT 5")
graph_query(cypher="MATCH (e:ETF) WHERE e.name STARTS WITH 'KODEX' RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY e.net_assets ASC LIMIT 5")""",
    },
    {
        "question": "TIGER ETF 중에서 보수율이 0.1% 이하인 ETF의 가격 추이를 보여줘",
        "description": "브랜드 + 보수율 조건 → ETF별 가격",
        "code": """\
graph_query(cypher="MATCH (e:ETF) WHERE e.name STARTS WITH 'TIGER' AND e.expense_ratio <= 0.1 RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC")
# 결과 ETF마다
get_etf_prices(etf_code="<ETF의 code>", period="1m")""",
    },
    {
        "question": "코스피 200 추종 ETF들의 보수율과 수익률을 비교해줘",
        "description": "지수 태그(코스피) → 보수율·수익률",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '코스피'}) WHERE e.name CONTAINS '200' RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, return_1m: e.return_1m} ORDER BY e.expense_ratio ASC")""",
    },
    # ── 운용사 ──
    {
        "question": "삼성자산운용의 ETF 중 수익률 상위 5개의 보유종목을 알려줘",
        "description": "운용사 → 수익률순 → ETF별 상세(보유종목)",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:MANAGED_BY]->(c:Company {name: '<운용사>'}) WHERE e.return_1m IS NOT NULL RETURN {code: e.code, name: e.name, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 5")
# 결과 ETF마다
get_etf_info(etf_code="<ETF의 code>")""",
    },
    {
        "question": "미래에셋자산운용과 삼성자산운용의 반도체 ETF를 비교해줘",
        "description": "운용사 × 태그 교차 조건",
        "code": """\
graph_query(cypher="MATCH (c:Company)<-[:MANAGED_BY]-(e:ETF)-[:TAGGED]->(:Tag {name: '반도체'}) WHERE c.name IN ['<운용사1>', '<운용사2>'] RETURN {company: c.name, code: e.code, name: e.name, expense_ratio: e.expense_ratio, net_assets: e.net_assets} ORDER BY c.name, e.net_assets DESC")""",
    },
    {
        "question": "운용사별 ETF 개수와 평균 보수율을 비교해줘",
        "description": "운용사 그룹 집계(count, avg)",
        "code": """\
graph_query(cypher="MATCH (e:ETF)-[:MANAGED_BY]->(c:Company) WITH c, count(e) AS etf_count, avg(e.expense_ratio) AS avg_fee RETURN {company: c.name, etf_count: etf_count, avg_fee: avg_fee} ORDER BY etf_count DESC")""",
    },
]


def _dollar(tag: str, text: str) -> str:
    assert f"${tag}$" not in text
    return f"${tag}${text}${tag}$"


def to_sql() -> str:
    lines = [
        "-- =============================================================================",
        "-- 03_seed_code_examples.sql",
        "-- 생성 파일 — docker/db/seed/code_examples.py 를 고친 뒤 다시 생성할 것.",
        "-- 시드 예시(사용자/챗 로그 출처가 아닌 행)를 지우고 다시 넣는다. 임베딩은 embed_code_examples DAG가 채운다.",
        "-- =============================================================================",
        "",
        "DELETE FROM code_examples WHERE source_chat_log_id IS NULL AND created_by IS NULL;",
        "",
    ]
    for i, ex in enumerate(EXAMPLES, 1):
        lines.append(f"-- Example {i}: {ex['question']}")
        lines.append("INSERT INTO code_examples (question, code, description, status) VALUES (")
        lines.append(f"  {_dollar('q', ex['question'])},")
        lines.append(f"  {_dollar('c', ex['code'])},")
        lines.append(f"  {_dollar('d', ex['description'])},")
        lines.append("  'active');")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(to_sql())
