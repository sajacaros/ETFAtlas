-- =============================================================================
-- 03_seed_code_examples.sql
-- 생성 파일 — docker/db/seed/code_examples.py 를 고친 뒤 다시 생성할 것.
-- 시드 예시(사용자/챗 로그 출처가 아닌 행)를 지우고 다시 넣는다. 임베딩은 embed_code_examples DAG가 채운다.
-- =============================================================================

DELETE FROM code_examples WHERE source_chat_log_id IS NULL AND created_by IS NULL;

-- Example 1: 반도체 ETF 3개의 가격 추이를 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$반도체 ETF 3개의 가격 추이를 비교해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY e.net_assets DESC LIMIT 3")
# 결과 ETF마다
get_etf_prices(etf_code="<ETF의 code>", period="1m")$c$,
  $d$태그 → 순자산 상위 N개 → ETF별 가격 조회$d$,
  'active');

-- Example 2: AI이면서 반도체인 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$AI이면서 반도체인 ETF를 알려줘$q$,
  $c$graph_query(cypher="MATCH (t1:Tag {name: 'AI'})<-[:TAGGED]-(e:ETF)-[:TAGGED]->(t2:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, net_assets: e.net_assets} ORDER BY e.net_assets DESC")$c$,
  $d$두 태그를 모두 가진 ETF (태그 교집합)$d$,
  'active');

-- Example 3: 2차전지 ETF 중 보수율 낮은 3개와 높은 3개를 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$2차전지 ETF 중 보수율 낮은 3개와 높은 3개를 비교해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '2차전지'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 3")
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '2차전지'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio DESC LIMIT 3")$c$,
  $d$태그 ETF를 보수율 오름차순/내림차순으로 각각 조회$d$,
  'active');

-- Example 4: 배당 ETF와 반도체 ETF를 하나씩 추천하고 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$배당 ETF와 반도체 ETF를 하나씩 추천하고 비교해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag) WHERE t.name IN ['고배당', '반도체'] WITH t, e ORDER BY e.net_assets DESC WITH t, head(collect(e)) AS top RETURN {tag: t.name, code: top.code, name: top.name}")
compare_etfs(etf_codes="<고배당 ETF의 code>,<반도체 ETF의 code>")$c$,
  $d$태그별 대표 ETF 1개씩 → compare_etfs$d$,
  'active');

-- Example 5: 바이오 ETF 중 수익률 1등과 금융 ETF 중 수익률 1등을 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$바이오 ETF 중 수익률 1등과 금융 ETF 중 수익률 1등을 비교해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag) WHERE t.name IN ['바이오', '금융'] AND e.return_1m IS NOT NULL WITH t, e ORDER BY e.return_1m DESC WITH t, head(collect(e)) AS top RETURN {tag: t.name, code: top.code, name: top.name, return_1m: top.return_1m}")
compare_etfs(etf_codes="<바이오 ETF의 code>,<금융 ETF의 code>")$c$,
  $d$태그별 1개월 수익률 1위 → compare_etfs$d$,
  'active');

-- Example 6: 방산 ETF 전체의 상세 정보와 가격을 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$방산 ETF 전체의 상세 정보와 가격을 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '방산'}) RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC")
# 결과 ETF마다
get_etf_info(etf_code="<ETF의 code>")
get_etf_prices(etf_code="<ETF의 code>", period="1m")$c$,
  $d$태그 ETF 전체 → ETF별 상세 + 가격$d$,
  'active');

-- Example 7: AI 관련 ETF들의 보유종목 변동을 한번에 확인해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$AI 관련 ETF들의 보유종목 변동을 한번에 확인해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: 'AI'}) RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC")
# 결과 ETF마다
get_holdings_changes(etf_code="<ETF의 code>", period="1w")$c$,
  $d$태그 ETF → ETF별 보유종목 변동$d$,
  'active');

-- Example 8: 반도체 ETF들의 보수율 통계와 추천 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$반도체 ETF들의 보수율 통계와 추천 ETF를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '반도체'}) RETURN {count: count(e), min_fee: min(e.expense_ratio), max_fee: max(e.expense_ratio), avg_fee: avg(e.expense_ratio)}")
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, net_assets: e.net_assets} ORDER BY e.expense_ratio ASC LIMIT 5")$c$,
  $d$태그 ETF 보수율 집계(min/max/avg) + 보수율 낮은 순$d$,
  'active');

-- Example 9: 금융 ETF 3개의 보유종목 상위 5개를 한눈에 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$금융 ETF 3개의 보유종목 상위 5개를 한눈에 비교해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '금융'}) WITH e ORDER BY e.net_assets DESC LIMIT 3 MATCH (e)-[h:CURRENT_HOLDS]->(s:Stock) WITH e, s, h ORDER BY h.weight DESC WITH e, collect({stock: s.name, weight: h.weight}) AS holdings RETURN {code: e.code, name: e.name, top5: holdings[0..5]}")$c$,
  $d$태그 상위 N개 ETF의 최신 보유종목 상위 M개 (ETF별 collect)$d$,
  'active');

-- Example 10: 삼성전자를 보유한 ETF 중 보수율이 낮은 3개의 상세 정보를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$삼성전자를 보유한 ETF 중 보수율이 낮은 3개의 상세 정보를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: '<종목명>'}) RETURN {code: e.code, name: e.name, weight: h.weight, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 3")
# 결과 ETF마다
get_etf_info(etf_code="<ETF의 code>")$c$,
  $d$종목 이름으로 보유 ETF(CURRENT_HOLDS) → 보수율순 → 상세$d$,
  'active');

-- Example 11: 삼성전자를 가장 많이 담은 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$삼성전자를 가장 많이 담은 ETF를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: '<종목명>'}) RETURN {code: e.code, name: e.name, weight: h.weight, expense_ratio: e.expense_ratio} ORDER BY h.weight DESC LIMIT 10")$c$,
  $d$종목 이름으로 보유 ETF(CURRENT_HOLDS) → 비중순$d$,
  'active');

-- Example 12: 삼성전자와 SK하이닉스가 많이 들어있는 ETF를 수수료순으로 정렬해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$삼성전자와 SK하이닉스가 많이 들어있는 ETF를 수수료순으로 정렬해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock) WHERE s.name IN ['<종목명1>', '<종목명2>'] WITH e, count(s) AS matched, sum(h.weight) AS weight_sum WHERE matched = 2 RETURN {code: e.code, name: e.name, weight_sum: weight_sum, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC, weight_sum DESC LIMIT 10")$c$,
  $d$여러 종목을 모두 보유한 ETF → 합산 비중 → 보수율순$d$,
  'active');

-- Example 13: 삼성전자와 SK하이닉스를 동시에 보유한 ETF 중 보수율이 가장 낮은 3개 상세 정보
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$삼성전자와 SK하이닉스를 동시에 보유한 ETF 중 보수율이 가장 낮은 3개 상세 정보$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock) WHERE s.name IN ['<종목명1>', '<종목명2>'] WITH e, count(s) AS matched, sum(h.weight) AS weight_sum WHERE matched = 2 RETURN {code: e.code, name: e.name, weight_sum: weight_sum, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 3")
# 결과 ETF마다
get_etf_info(etf_code="<ETF의 code>")$c$,
  $d$여러 종목 동시 보유(matched = 종목 수) → 보수율순 → 상세$d$,
  'active');

-- Example 14: 반도체 3대장 합산 비중이 높은 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$반도체 3대장 합산 비중이 높은 ETF를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock) WHERE s.name IN ['<종목명1>', '<종목명2>', '<종목명3>'] WITH e, sum(h.weight) AS weight_sum, collect(s.name) AS stocks RETURN {code: e.code, name: e.name, weight_sum: weight_sum, stocks: stocks} ORDER BY weight_sum DESC LIMIT 10")$c$,
  $d$여러 종목 합산 비중순 (일부만 보유해도 포함)$d$,
  'active');

-- Example 15: 2차전지 ETF 중 LG에너지솔루션과 삼성SDI 비중이 낮은 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$2차전지 ETF 중 LG에너지솔루션과 삼성SDI 비중이 낮은 ETF를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '2차전지'}) OPTIONAL MATCH (e)-[h:CURRENT_HOLDS]->(s:Stock) WHERE s.name IN ['<종목명1>', '<종목명2>'] WITH e, coalesce(sum(h.weight), 0) AS weight_sum, collect(s.name) AS held RETURN {code: e.code, name: e.name, weight_sum: weight_sum, held: held, expense_ratio: e.expense_ratio} ORDER BY weight_sum ASC LIMIT 10")$c$,
  $d$후보 ETF(태그)에서 출발 → 종목은 OPTIONAL MATCH(미보유·상위 30위 밖 = 0) → 합산 비중 오름차순$d$,
  'active');

-- Example 16: 삼성전자를 10% 이상 보유한 ETF들의 최근 수익률을 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$삼성전자를 10% 이상 보유한 ETF들의 최근 수익률을 비교해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: '<종목명>'}) WHERE h.weight >= 10 RETURN {code: e.code, name: e.name, weight: h.weight, return_1w: e.return_1w, return_1m: e.return_1m} ORDER BY e.return_1m DESC")$c$,
  $d$종목 비중 조건(WHERE latest.weight >= N) → 수익률$d$,
  'active');

-- Example 17: SK하이닉스를 보유한 ETF 중 수익률이 좋은 3개의 가격 추이를 보여줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$SK하이닉스를 보유한 ETF 중 수익률이 좋은 3개의 가격 추이를 보여줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: '<종목명>'}) WHERE e.return_1m IS NOT NULL RETURN {code: e.code, name: e.name, weight: h.weight, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 3")
# 결과 ETF마다
get_etf_prices(etf_code="<ETF의 code>", period="1m")$c$,
  $d$종목 보유 ETF → 수익률순 → ETF별 가격$d$,
  'active');

-- Example 18: 삼성전자 주가와 삼성전자를 가장 많이 보유한 ETF 3개의 가격을 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$삼성전자 주가와 삼성전자를 가장 많이 보유한 ETF 3개의 가격을 비교해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: '<종목명>'}) RETURN {stock_code: s.code, code: e.code, name: e.name, weight: h.weight} ORDER BY h.weight DESC LIMIT 3")
get_stock_prices(stock_code="<결과의 stock_code>", period="1m")
# 결과 ETF마다
get_etf_prices(etf_code="<ETF의 code>", period="1m")$c$,
  $d$종목 코드 확인 → 종목 가격 + 보유 비중 상위 ETF 가격$d$,
  'active');

-- Example 19: 삼성전자 주가와 반도체 ETF 수익률을 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$삼성전자 주가와 반도체 ETF 수익률을 비교해줘$q$,
  $c$stock_search(query="<종목명>")
get_stock_prices(stock_code="<종목의 code>", period="1m")
graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, return_1w: e.return_1w, return_1m: e.return_1m} ORDER BY e.net_assets DESC LIMIT 5")$c$,
  $d$종목 가격 + 태그 ETF 수익률$d$,
  'active');

-- Example 20: 삼성전자가 많이 포함된 테마(태그)는 뭐야? 각 태그별 대표 ETF도 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$삼성전자가 많이 포함된 테마(태그)는 뭐야? 각 태그별 대표 ETF도 알려줘$q$,
  $c$graph_query(cypher="MATCH (t:Tag)<-[:TAGGED]-(e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: '<종목명>'}) WITH t, e, h ORDER BY h.weight DESC WITH t, count(e) AS etf_count, avg(h.weight) AS avg_weight, head(collect(e.name)) AS top_etf RETURN {tag: t.name, etf_count: etf_count, avg_weight: avg_weight, top_etf: top_etf} ORDER BY etf_count DESC")$c$,
  $d$종목 보유 ETF의 태그 분포(태그별 ETF 수, 평균 비중) + 태그별 비중 1위 ETF$d$,
  'active');

-- Example 21: KODEX 200의 보유종목 상위 10개를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$KODEX 200의 보유종목 상위 10개를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF {name: '<ETF명>'})-[h:CURRENT_HOLDS]->(s:Stock) RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight} ORDER BY h.weight DESC LIMIT 10")$c$,
  $d$ETF 이름으로 최신 보유종목 비중순$d$,
  'active');

-- Example 22: KODEX 200과 TIGER 200의 공통 보유종목 비중을 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$KODEX 200과 TIGER 200의 공통 보유종목 비중을 비교해줘$q$,
  $c$graph_query(cypher="MATCH (a:ETF {name: '<ETF명1>'})-[ha:CURRENT_HOLDS]->(s:Stock)<-[hb:CURRENT_HOLDS]-(b:ETF {name: '<ETF명2>'}) RETURN {stock: s.name, weight_a: ha.weight, weight_b: hb.weight} ORDER BY ha.weight DESC")$c$,
  $d$두 ETF가 함께 보유한 종목과 각각의 비중$d$,
  'active');

-- Example 23: KODEX 200과 유사한 ETF 5개의 상세 정보를 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$KODEX 200과 유사한 ETF 5개의 상세 정보를 비교해줘$q$,
  $c$etf_search(query="<ETF명>")
find_similar_etfs(etf_code="<ETF의 code>")
compare_etfs(etf_codes="<유사 ETF 5개의 code, 쉼표 구분>")$c$,
  $d$ETF 코드 확인 → 유사 ETF → compare_etfs$d$,
  'active');

-- Example 24: 최근 1주 수익률 상위 3개 ETF의 보유종목과 유사 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$최근 1주 수익률 상위 3개 ETF의 보유종목과 유사 ETF를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF) WHERE e.return_1w IS NOT NULL RETURN {code: e.code, name: e.name, return_1w: e.return_1w} ORDER BY e.return_1w DESC LIMIT 3")
# 결과 ETF마다
get_etf_info(etf_code="<ETF의 code>")
find_similar_etfs(etf_code="<ETF의 code>")$c$,
  $d$수익률 상위 ETF → ETF별 상세(보유종목) + 유사 ETF$d$,
  'active');

-- Example 25: 최근 신규 편입된 종목이 있는 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$최근 신규 편입된 종목이 있는 ETF를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF {code: '069500'})-[h:HOLDS]->() WITH DISTINCT h.date AS d ORDER BY d DESC LIMIT 2 WITH collect(d) AS ds WHERE size(ds) = 2 MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock) WHERE h.date = ds[0] AND NOT EXISTS((e)-[:HOLDS {date: ds[1]}]->(s)) RETURN {code: e.code, name: e.name, stock: s.name, weight: h.weight} ORDER BY h.weight DESC LIMIT 20")$c$,
  $d$기준 ETF(069500)로 최근 두 수집일 확인 → 현재 구성종목 중 직전 수집일 HOLDS에 없던 종목$d$,
  'active');

-- Example 26: 삼성전자 비중이 늘어난 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$삼성전자 비중이 늘어난 ETF를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[h:HOLDS]->(s:Stock {name: '<종목명>'}) WITH e, h ORDER BY h.date DESC WITH e, collect(h) AS hs WHERE size(hs) >= 2 WITH e, hs[0] AS cur, hs[1] AS prev WHERE cur.weight > prev.weight RETURN {code: e.code, name: e.name, prev_date: prev.date, prev_weight: prev.weight, date: cur.date, weight: cur.weight, change: cur.weight - prev.weight} ORDER BY cur.weight - prev.weight DESC")$c$,
  $d$종목의 ETF별 HOLDS 이력 → 최신 vs 직전 비중 비교$d$,
  'active');

-- Example 27: KoAct 바이오헬스케어에서 알테오젠 비중이 급변한 시점을 분석해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$KoAct 바이오헬스케어에서 알테오젠 비중이 급변한 시점을 분석해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF {name: '<ETF명>'})-[h:HOLDS]->(s:Stock {name: '<종목명>'}) RETURN {date: h.date, weight: h.weight, shares: h.shares} ORDER BY h.date")$c$,
  $d$ETF-종목 HOLDS 날짜별 이력 (변화량 계산은 응답에서)$d$,
  'active');

-- Example 28: 순자산 100억 이상 ETF 중 보수율이 낮은 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$순자산 100억 이상 ETF 중 보수율이 낮은 ETF를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF) WHERE e.net_assets >= 10000000000 RETURN {code: e.code, name: e.name, net_assets: e.net_assets, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 10")$c$,
  $d$ETF 속성 조건(순자산은 원 단위) → 보수율순$d$,
  'active');

-- Example 29: 보수율 낮으면서 수익률 좋은 ETF를 추천해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$보수율 낮으면서 수익률 좋은 ETF를 추천해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF) WHERE e.expense_ratio <= 0.1 AND e.return_1m IS NOT NULL RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 10")$c$,
  $d$보수율 상한 조건 + 수익률순$d$,
  'active');

-- Example 30: 1주 수익률과 1개월 수익률 차이가 큰 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$1주 수익률과 1개월 수익률 차이가 큰 ETF를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF) WHERE e.return_1w IS NOT NULL AND e.return_1m IS NOT NULL WITH e, abs(e.return_1w - e.return_1m) AS gap RETURN {code: e.code, name: e.name, return_1w: e.return_1w, return_1m: e.return_1m, gap: gap} ORDER BY gap DESC LIMIT 10")$c$,
  $d$두 속성의 차이를 Cypher에서 계산해 정렬$d$,
  'active');

-- Example 31: 최근 시가총액이 가장 많이 늘어난 ETF 5개를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$최근 시가총액이 가장 많이 늘어난 ETF 5개를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF) WHERE e.market_cap_change_1w IS NOT NULL RETURN {code: e.code, name: e.name, market_cap_change_1w: e.market_cap_change_1w} ORDER BY e.market_cap_change_1w DESC LIMIT 5")$c$,
  $d$ETF 속성(market_cap_change_1w) 정렬$d$,
  'active');

-- Example 32: 순자산 상위 5개 ETF의 최근 1주 가격과 보유종목 변동을 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$순자산 상위 5개 ETF의 최근 1주 가격과 보유종목 변동을 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF) RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY e.net_assets DESC LIMIT 5")
# 결과 ETF마다
get_etf_prices(etf_code="<ETF의 code>", period="1w")
get_holdings_changes(etf_code="<ETF의 code>", period="1w")$c$,
  $d$순자산순 → ETF별 가격 + 보유종목 변동$d$,
  'active');

-- Example 33: 거래량이 가장 많은 ETF 5개를 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$거래량이 가장 많은 ETF 5개를 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:HAS_PRICE]->(p:Price) WITH e, p ORDER BY p.date DESC WITH e, head(collect(p)) AS latest RETURN {code: e.code, name: e.name, date: latest.date, volume: latest.volume, trade_value: latest.trade_value} ORDER BY latest.volume DESC LIMIT 5")$c$,
  $d$ETF별 최신 Price 노드 → 거래량순$d$,
  'active');

-- Example 34: KODEX ETF 중 순자산이 가장 큰 5개와 가장 작은 5개를 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$KODEX ETF 중 순자산이 가장 큰 5개와 가장 작은 5개를 비교해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF) WHERE e.name STARTS WITH 'KODEX' RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY e.net_assets DESC LIMIT 5")
graph_query(cypher="MATCH (e:ETF) WHERE e.name STARTS WITH 'KODEX' RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY e.net_assets ASC LIMIT 5")$c$,
  $d$이름 접두어(브랜드) 필터 → 순자산 상/하위$d$,
  'active');

-- Example 35: TIGER ETF 중에서 보수율이 0.1% 이하인 ETF의 가격 추이를 보여줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$TIGER ETF 중에서 보수율이 0.1% 이하인 ETF의 가격 추이를 보여줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF) WHERE e.name STARTS WITH 'TIGER' AND e.expense_ratio <= 0.1 RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC")
# 결과 ETF마다
get_etf_prices(etf_code="<ETF의 code>", period="1m")$c$,
  $d$브랜드 + 보수율 조건 → ETF별 가격$d$,
  'active');

-- Example 36: 코스피 200 추종 ETF들의 보수율과 수익률을 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$코스피 200 추종 ETF들의 보수율과 수익률을 비교해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(:Tag {name: '코스피'}) WHERE e.name CONTAINS '200' RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, return_1m: e.return_1m} ORDER BY e.expense_ratio ASC")$c$,
  $d$지수 태그(코스피) → 보수율·수익률$d$,
  'active');

-- Example 37: 삼성자산운용의 ETF 중 수익률 상위 5개의 보유종목을 알려줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$삼성자산운용의 ETF 중 수익률 상위 5개의 보유종목을 알려줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:MANAGED_BY]->(c:Company {name: '<운용사>'}) WHERE e.return_1m IS NOT NULL RETURN {code: e.code, name: e.name, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 5")
# 결과 ETF마다
get_etf_info(etf_code="<ETF의 code>")$c$,
  $d$운용사 → 수익률순 → ETF별 상세(보유종목)$d$,
  'active');

-- Example 38: 미래에셋자산운용과 삼성자산운용의 반도체 ETF를 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$미래에셋자산운용과 삼성자산운용의 반도체 ETF를 비교해줘$q$,
  $c$graph_query(cypher="MATCH (c:Company)<-[:MANAGED_BY]-(e:ETF)-[:TAGGED]->(:Tag {name: '반도체'}) WHERE c.name IN ['<운용사1>', '<운용사2>'] RETURN {company: c.name, code: e.code, name: e.name, expense_ratio: e.expense_ratio, net_assets: e.net_assets} ORDER BY c.name, e.net_assets DESC")$c$,
  $d$운용사 × 태그 교차 조건$d$,
  'active');

-- Example 39: 운용사별 ETF 개수와 평균 보수율을 비교해줘
INSERT INTO code_examples (question, code, description, status) VALUES (
  $q$운용사별 ETF 개수와 평균 보수율을 비교해줘$q$,
  $c$graph_query(cypher="MATCH (e:ETF)-[:MANAGED_BY]->(c:Company) WITH c, count(e) AS etf_count, avg(e.expense_ratio) AS avg_fee RETURN {company: c.name, etf_count: etf_count, avg_fee: avg_fee} ORDER BY etf_count DESC")$c$,
  $d$운용사 그룹 집계(count, avg)$d$,
  'active');

