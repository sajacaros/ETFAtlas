-- =============================================================================
-- 05_seed_code_examples.sql
-- Seed code_examples table with predefined examples from code_examples.json
-- This script deletes any previously JSON-seeded rows (where source_chat_log_id
-- and created_by are both NULL) and re-inserts all 36 examples.
-- =============================================================================

-- Remove previously seeded examples (not user-created, not from chat logs)
DELETE FROM code_examples WHERE source_chat_log_id IS NULL AND created_by IS NULL;

-- Insert all 36 code examples
-- Example 1: 반도체 ETF 3개의 가격 추이를 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$반도체 ETF 3개의 가격 추이를 비교해줘$q$, $c$# 1. 반도체 태그 ETF 목록 조회
results = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.net_assets DESC LIMIT 3")
etfs = json.loads(results)

# 2. 각 ETF의 가격 추이 조회
price_data = []
for etf in etfs:
    prices = get_etf_prices(etf_code=etf['code'], period='1m')
    price_info = json.loads(prices)
    price_data.append({'name': etf['name'], 'code': etf['code'], 'summary': price_info['summary']})

# 3. 표로 정리
lines = ['| ETF | 코드 | 시작가 | 최종가 | 등락률 |', '|---|---|---|---|---|']
for p in price_data:
    s = p['summary']
    lines.append(f"| {p['name']} | {p['code']} | {s['start_close']} | {s['end_close']} | {s['change_rate']}% |")
final_answer('\n'.join(lines))$c$, $d$태그 검색 → 상위 N개 ETF 추출 → for 루프로 가격 조회 → 표 정리$d$, 'active', NULL, NULL, NULL);

-- Example 2: 삼성전자를 보유한 ETF 중 보수율이 낮은 3개의 상세 정보를 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$삼성전자를 보유한 ETF 중 보수율이 낮은 3개의 상세 정보를 알려줘$q$, $c$# 1. 삼성전자 종목코드 확인
search = stock_search(query='삼성전자')
stocks = json.loads(search)
stock_code = stocks[0]['code']

# 2. 삼성전자를 보유한 ETF를 보수율순으로 조회
results = graph_query(cypher=f"MATCH (e:ETF)-[h:HOLDS]->(s:Stock {{code: '{stock_code}'}}) WITH e, h ORDER BY h.date DESC WITH e, head(collect(h)) as latest RETURN {{code: e.code, name: e.name, weight: latest.weight, expense_ratio: e.expense_ratio}} ORDER BY e.expense_ratio ASC LIMIT 3")
etfs = json.loads(results)

# 3. 각 ETF의 상세 정보 조회
details = []
for etf in etfs:
    info = get_etf_info(etf_code=etf['code'])
    details.append(json.loads(info))

# 4. 표로 정리
lines = ['| ETF | 코드 | 보수율 | 보유비중 | 태그 |', '|---|---|---|---|---|']
for d, e in zip(details, etfs):
    tags = ', '.join(d.get('tags', []))
    lines.append(f"| {d['name']} | {d['code']} | {d.get('expense_ratio', 'N/A')} | {e['weight']}% | {tags} |")
final_answer('\n'.join(lines))$c$, $d$종목 검색 → graph_query로 보유 ETF 필터 → for 루프 상세 조회 → 표 정리$d$, 'active', NULL, NULL, NULL);

-- Example 3: AI 관련 ETF들의 보유종목 변동을 한번에 확인해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$AI 관련 ETF들의 보유종목 변동을 한번에 확인해줘$q$, $c$# 1. AI 태그 ETF 목록 조회
results = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: 'AI'}) RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC LIMIT 5")
etfs = json.loads(results)

# 2. 각 ETF의 보유종목 변동 조회
all_changes = []
for etf in etfs:
    changes = get_holdings_changes(etf_code=etf['code'], period='1w')
    if changes != '변동 없음':
        all_changes.append({'name': etf['name'], 'code': etf['code'], 'changes': json.loads(changes)})

# 3. 결과 정리
if not all_changes:
    final_answer('최근 1주간 AI ETF들의 보유종목 변동이 없습니다.')
else:
    lines = ['| ETF | 종목 | 변동유형 | 이전비중 | 현재비중 |', '|---|---|---|---|---|']
    for etf_change in all_changes:
        for c in etf_change['changes'][:5]:
            lines.append(f"| {etf_change['name']} | {c.get('stock_name', '')} | {c['change_type']} | {c.get('before_weight', '-')} | {c.get('after_weight', '-')} |")
    final_answer('\n'.join(lines))$c$, $d$태그 ETF 조회 → for 루프 보유종목 변동 조회 → 빈 결과 분기 처리$d$, 'active', NULL, NULL, NULL);

-- Example 4: KODEX 200과 유사한 ETF 5개의 상세 정보를 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$KODEX 200과 유사한 ETF 5개의 상세 정보를 비교해줘$q$, $c$# 1. KODEX 200 코드 확인
search = etf_search(query='KODEX 200')
result = json.loads(search)
etf_code = result[0]['code']

# 2. 유사 ETF 조회
similar = find_similar_etfs(etf_code=etf_code)
similar_etfs = json.loads(similar)

# 3. 상위 5개 유사 ETF 상세 조회
details = []
for etf in similar_etfs[:5]:
    info = get_etf_info(etf_code=etf['etf_code'])
    detail = json.loads(info)
    detail['similarity'] = etf.get('similarity', '')
    details.append(detail)

# 4. 표로 정리
lines = ['| ETF | 코드 | 보수율 | 유사도 | 태그 |', '|---|---|---|---|---|']
for d in details:
    tags = ', '.join(d.get('tags', []))
    lines.append(f"| {d['name']} | {d['code']} | {d.get('expense_ratio', 'N/A')} | {d.get('similarity', '')} | {tags} |")
final_answer('\n'.join(lines))$c$, $d$ETF 검색 → 유사 ETF 조회 → for 루프 상세 조회 → 표 정리$d$, 'active', NULL, NULL, NULL);

-- Example 5: 2차전지 ETF 중 보수율 낮은 3개와 높은 3개를 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$2차전지 ETF 중 보수율 낮은 3개와 높은 3개를 비교해줘$q$, $c$# 1. 2차전지 태그 ETF를 보수율순으로 조회
results = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '2차전지'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC")
etfs = json.loads(results)

# 2. 보수율 낮은 3개 + 높은 3개 추출
low3 = etfs[:3]
high3 = etfs[-3:] if len(etfs) >= 6 else etfs[3:]

# 3. 각 ETF 상세 정보 조회
all_details = []
for etf in low3 + high3:
    info = get_etf_info(etf_code=etf['code'])
    detail = json.loads(info)
    detail['group'] = '저보수' if etf in low3 else '고보수'
    all_details.append(detail)

# 4. 표로 정리
lines = ['| 구분 | ETF | 보수율 | 1개월 수익률 | 태그 |', '|---|---|---|---|---|']
for d in all_details:
    returns = d.get('returns', {})
    ret_1m = f"{returns.get('1m', 'N/A')}%" if '1m' in returns else 'N/A'
    lines.append(f"| {d['group']} | {d['name']} | {d.get('expense_ratio', 'N/A')} | {ret_1m} | {', '.join(d.get('tags', []))} |")
final_answer('\n'.join(lines))$c$, $d$태그 ETF 전체 조회 → 정렬로 상/하위 추출 → for 루프 상세 조회$d$, 'active', NULL, NULL, NULL);

-- Example 6: SK하이닉스를 보유한 ETF 중 수익률이 좋은 3개의 가격 추이를 보여줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$SK하이닉스를 보유한 ETF 중 수익률이 좋은 3개의 가격 추이를 보여줘$q$, $c$# 1. SK하이닉스 종목코드 확인
search = stock_search(query='SK하이닉스')
stocks = json.loads(search)
stock_code = stocks[0]['code']

# 2. SK하이닉스를 보유한 ETF를 수익률순으로 조회
results = graph_query(cypher=f"MATCH (e:ETF)-[h:HOLDS]->(s:Stock {{code: '{stock_code}'}}) WITH e, h ORDER BY h.date DESC WITH e, head(collect(h)) as latest RETURN {{code: e.code, name: e.name, weight: latest.weight, return_1m: e.return_1m}} ORDER BY e.return_1m DESC LIMIT 3")
etfs = json.loads(results)

# 3. 각 ETF 가격 추이 조회
price_data = []
for etf in etfs:
    prices = get_etf_prices(etf_code=etf['code'], period='1m')
    price_info = json.loads(prices)
    price_data.append({'name': etf['name'], 'code': etf['code'], 'summary': price_info['summary']})

# 4. 표로 정리
lines = ['| ETF | 코드 | 시작가 | 최종가 | 등락률 | 평균거래량 |', '|---|---|---|---|---|---|']
for p in price_data:
    s = p['summary']
    lines.append(f"| {p['name']} | {p['code']} | {s['start_close']} | {s['end_close']} | {s['change_rate']}% | {s.get('avg_volume', 'N/A')} |")
final_answer('\n'.join(lines))$c$, $d$종목 검색 → graph_query 수익률순 필터 → for 루프 가격 조회$d$, 'active', NULL, NULL, NULL);

-- Example 7: 배당 ETF와 반도체 ETF를 하나씩 추천하고 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$배당 ETF와 반도체 ETF를 하나씩 추천하고 비교해줘$q$, $c$# 1. 배당 태그 ETF 중 순자산 최대
result1 = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '배당'}) RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC LIMIT 1")
div_etf = json.loads(result1)[0]

# 2. 반도체 태그 ETF 중 순자산 최대
result2 = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC LIMIT 1")
chip_etf = json.loads(result2)[0]

# 3. 두 ETF 비교
comparison = compare_etfs(etf_codes=f"{div_etf['code']},{chip_etf['code']}")
comp_data = json.loads(comparison)

# 4. 표로 정리
lines = ['| 항목 | ' + comp_data[0]['name'] + ' | ' + comp_data[1]['name'] + ' |', '|---|---|---|']
for key in ['code', 'expense_ratio', 'return_1m', 'latest_net_assets']:
    label = {'code': '코드', 'expense_ratio': '보수율', 'return_1m': '1개월 수익률', 'latest_net_assets': '순자산'}[key]
    lines.append(f"| {label} | {comp_data[0].get(key, 'N/A')} | {comp_data[1].get(key, 'N/A')} |")
final_answer('\n'.join(lines))$c$, $d$두 태그에서 대표 ETF 추출 → compare_etfs로 비교$d$, 'active', NULL, NULL, NULL);

-- Example 8: 삼성자산운용의 ETF 중 수익률 상위 5개의 보유종목을 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$삼성자산운용의 ETF 중 수익률 상위 5개의 보유종목을 알려줘$q$, $c$# 1. 삼성자산운용 ETF를 수익률순으로 조회
results = graph_query(cypher="MATCH (e:ETF)-[:MANAGED_BY]->(c:Company {name: '삼성자산운용'}) RETURN {code: e.code, name: e.name, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 5")
etfs = json.loads(results)

# 2. 각 ETF의 상세 정보 조회 (보유종목 포함)
all_info = []
for etf in etfs:
    info = get_etf_info(etf_code=etf['code'])
    all_info.append(json.loads(info))

# 3. 각 ETF별 상위 보유종목 표 생성
lines = []
for info in all_info:
    lines.append(f"\n### {info['name']} ({info['code']})")
    lines.append('| 종목 | 비중(%) |')
    lines.append('|---|---|')
    for h in info.get('top_holdings', [])[:5]:
        lines.append(f"| {h['stock_name']} | {h['weight']} |")
final_answer('\n'.join(lines))$c$, $d$운용사별 ETF 조회 → for 루프 상세 조회 → 섹션별 표 생성$d$, 'active', NULL, NULL, NULL);

-- Example 9: TIGER ETF 중에서 보수율이 0.1% 이하인 ETF의 가격 추이를 보여줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$TIGER ETF 중에서 보수율이 0.1% 이하인 ETF의 가격 추이를 보여줘$q$, $c$# 1. TIGER ETF 검색
search = etf_search(query='TIGER', limit=50)
etfs = json.loads(search)

# 2. 보수율 0.1% 이하 필터링 (expense_ratio가 '0.10%' 형식 문자열)
low_fee = [e for e in etfs if e.get('expense_ratio') and float(e['expense_ratio'].replace('%', '')) <= 0.1]

if not low_fee:
    final_answer('보수율 0.1% 이하인 TIGER ETF가 없습니다.')
else:
    # 3. 각 ETF 가격 조회 (최대 5개)
    lines = ['| ETF | 코드 | 보수율 | 시작가 | 최종가 | 등락률 |', '|---|---|---|---|---|---|']
    for etf in low_fee[:5]:
        prices = get_etf_prices(etf_code=etf['code'], period='1m')
        price_info = json.loads(prices)
        s = price_info['summary']
        lines.append(f"| {etf['name']} | {etf['code']} | {etf['expense_ratio']} | {s['start_close']} | {s['end_close']} | {s['change_rate']}% |")
    final_answer('\n'.join(lines))$c$, $d$ETF 검색 → 리스트 필터링 → for 루프 가격 조회 → 빈 결과 분기$d$, 'active', NULL, NULL, NULL);

-- Example 10: 코스피 200 추종 ETF들의 보수율과 수익률을 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$코스피 200 추종 ETF들의 보수율과 수익률을 비교해줘$q$, $c$# 1. 코스피 태그 ETF 조회
results = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '코스피'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.net_assets DESC LIMIT 10")
etfs = json.loads(results)

# 2. 상위 3개 ETF 비교
codes = ','.join([e['code'] for e in etfs[:3]])
comparison = compare_etfs(etf_codes=codes)
comp_data = json.loads(comparison)

# 3. 표로 정리
lines = ['| ETF | 코드 | 보수율 | 1개월 수익률 | 순자산 |', '|---|---|---|---|---|']
for c in comp_data:
    lines.append(f"| {c['name']} | {c['code']} | {c.get('expense_ratio', 'N/A')} | {c.get('return_1m', 'N/A')}% | {c.get('latest_net_assets', 'N/A')} |")
final_answer('\n'.join(lines))$c$, $d$태그 ETF 조회 → 상위 N개 코드 추출 → compare_etfs 비교$d$, 'active', NULL, NULL, NULL);

-- Example 11: 삼성전자와 SK하이닉스를 동시에 보유한 ETF 중 보수율이 가장 낮은 3개 상세 정보
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$삼성전자와 SK하이닉스를 동시에 보유한 ETF 중 보수율이 가장 낮은 3개 상세 정보$q$, $c$# 1. 종목코드 확인
search1 = stock_search(query='삼성전자')
code1 = json.loads(search1)[0]['code']
search2 = stock_search(query='SK하이닉스')
code2 = json.loads(search2)[0]['code']

# 2. 두 종목을 동시에 보유한 ETF 조회
results = graph_query(cypher=f"MATCH (e:ETF)-[h1:HOLDS]->(s1:Stock {{code: '{code1}'}}) WITH e, h1 ORDER BY h1.date DESC WITH e, head(collect(h1)) as lh1 MATCH (e)-[h2:HOLDS]->(s2:Stock {{code: '{code2}'}}) WITH e, lh1, h2 ORDER BY h2.date DESC WITH e, lh1, head(collect(h2)) as lh2 RETURN {{code: e.code, name: e.name, weight1: lh1.weight, weight2: lh2.weight, expense_ratio: e.expense_ratio}} ORDER BY e.expense_ratio ASC LIMIT 3")
etfs = json.loads(results)

# 3. 상세 정보 조회
details = []
for etf in etfs:
    info = get_etf_info(etf_code=etf['code'])
    detail = json.loads(info)
    detail['weight_samsung'] = etf['weight1']
    detail['weight_hynix'] = etf['weight2']
    details.append(detail)

# 4. 표로 정리
lines = ['| ETF | 보수율 | 삼성전자 비중 | SK하이닉스 비중 | 태그 |', '|---|---|---|---|---|']
for d in details:
    tags = ', '.join(d.get('tags', []))
    lines.append(f"| {d['name']} | {d.get('expense_ratio', 'N/A')} | {d['weight_samsung']}% | {d['weight_hynix']}% | {tags} |")
final_answer('\n'.join(lines))$c$, $d$복수 종목 검색 → 동시 보유 ETF Cypher → for 루프 상세 조회$d$, 'active', NULL, NULL, NULL);

-- Example 12: 바이오 ETF와 헬스케어 ETF 중 각각 수익률 1등을 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$바이오 ETF와 헬스케어 ETF 중 각각 수익률 1등을 비교해줘$q$, $c$# 1. 바이오 태그 수익률 1등
result1 = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '바이오'}) RETURN {code: e.code, name: e.name, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 1")
bio = json.loads(result1)

# 2. 헬스케어 태그 수익률 1등
result2 = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '헬스케어'}) RETURN {code: e.code, name: e.name, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 1")
hc = json.loads(result2)

if not bio or not hc:
    final_answer('바이오 또는 헬스케어 태그의 ETF를 찾을 수 없습니다.')
else:
    # 3. 두 ETF 비교
    codes = f"{bio[0]['code']},{hc[0]['code']}"
    comparison = compare_etfs(etf_codes=codes)
    comp_data = json.loads(comparison)

    lines = ['| 항목 | ' + comp_data[0]['name'] + ' | ' + comp_data[1]['name'] + ' |', '|---|---|---|']
    for key in ['code', 'expense_ratio', 'return_1m', 'latest_net_assets']:
        label = {'code': '코드', 'expense_ratio': '보수율', 'return_1m': '1개월 수익률', 'latest_net_assets': '순자산'}[key]
        lines.append(f"| {label} | {comp_data[0].get(key, 'N/A')} | {comp_data[1].get(key, 'N/A')} |")
    final_answer('\n'.join(lines))$c$, $d$두 태그 각각 수익률 1등 추출 → compare_etfs 비교 → 빈 결과 분기$d$, 'active', NULL, NULL, NULL);

-- Example 13: 순자산 상위 5개 ETF의 최근 1주 가격과 보유종목 변동을 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$순자산 상위 5개 ETF의 최근 1주 가격과 보유종목 변동을 알려줘$q$, $c$# 1. 순자산 상위 5개 ETF
results = graph_query(cypher="MATCH (e:ETF) RETURN {code: e.code, name: e.name, net_assets: e.net_assets} ORDER BY e.net_assets DESC LIMIT 5")
etfs = json.loads(results)

# 2. 각 ETF의 가격과 보유종목 변동 조회
lines = []
for etf in etfs:
    # 가격 조회
    prices = get_etf_prices(etf_code=etf['code'], period='1w')
    price_info = json.loads(prices)
    s = price_info['summary']

    # 보유종목 변동 조회
    changes = get_holdings_changes(etf_code=etf['code'], period='1w')
    change_count = 0 if changes == '변동 없음' else len(json.loads(changes))

    lines.append(f"| {etf['name']} | {etf['code']} | {s['start_close']} | {s['end_close']} | {s['change_rate']}% | {change_count}건 |")

header = '| ETF | 코드 | 주초가 | 주말가 | 등락률 | 보유종목변동 |\n|---|---|---|---|---|---|\n'
final_answer(header + '\n'.join(lines))$c$, $d$순자산 상위 ETF 조회 → for 루프 가격+변동 병렬 조회$d$, 'active', NULL, NULL, NULL);

-- Example 14: 방산 ETF 전체의 상세 정보와 가격을 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$방산 ETF 전체의 상세 정보와 가격을 알려줘$q$, $c$# 1. 방산 태그 ETF 조회
results = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '방산'}) RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC")
etfs = json.loads(results)

if not etfs:
    final_answer('방산 태그의 ETF가 없습니다.')
else:
    # 2. 각 ETF 상세+가격 조회
    lines = []
    for etf in etfs:
        info = json.loads(get_etf_info(etf_code=etf['code']))
        prices = json.loads(get_etf_prices(etf_code=etf['code'], period='1m'))
        s = prices['summary']
        returns = info.get('returns', {})
        lines.append(f"| {info['name']} | {info['code']} | {info.get('expense_ratio', 'N/A')} | {returns.get('1m', 'N/A')}% | {s['change_rate']}% | {s.get('avg_volume', 'N/A')} |")

    header = '| ETF | 코드 | 보수율 | 1개월수익률 | 가격등락률 | 평균거래량 |\n|---|---|---|---|---|---|\n'
    final_answer(header + '\n'.join(lines))$c$, $d$태그 ETF 전체 조회 → for 루프 상세+가격 조회 → 빈 결과 분기$d$, 'active', NULL, NULL, NULL);

-- Example 15: KODEX ETF 중 가장 인기 있는 5개와 가장 인기 없는 5개를 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$KODEX ETF 중 가장 인기 있는 5개와 가장 인기 없는 5개를 비교해줘$q$, $c$# 1. KODEX ETF 전체 조회 (순자산순)
search = etf_search(query='KODEX', limit=50)
etfs = json.loads(search)

# 2. 각 ETF의 상세 조회 (순자산 확인)
detailed = []
for etf in etfs:
    info = json.loads(get_etf_info(etf_code=etf['code']))
    detailed.append(info)

# 3. 순자산 기준 정렬
# 순자산이 없는 경우 제외
with_assets = [d for d in detailed if d.get('returns')]
top5 = detailed[:5]
bottom5 = detailed[-5:] if len(detailed) >= 10 else detailed[5:]

# 4. 표로 정리
lines = ['## 순자산 상위 5개', '| ETF | 보수율 | 태그 |', '|---|---|---|']
for d in top5:
    lines.append(f"| {d['name']} | {d.get('expense_ratio', 'N/A')} | {', '.join(d.get('tags', []))} |")
lines.extend(['', '## 순자산 하위 5개', '| ETF | 보수율 | 태그 |', '|---|---|---|'])
for d in bottom5:
    lines.append(f"| {d['name']} | {d.get('expense_ratio', 'N/A')} | {', '.join(d.get('tags', []))} |")
final_answer('\n'.join(lines))$c$, $d$ETF 검색 → for 루프 상세 조회 → 상/하위 분리 → 섹션별 표$d$, 'active', NULL, NULL, NULL);

-- Example 16: 금융 ETF 3개의 보유종목 상위 5개를 한눈에 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$금융 ETF 3개의 보유종목 상위 5개를 한눈에 비교해줘$q$, $c$# 1. 금융 태그 ETF 상위 3개 조회
results = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '금융'}) RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC LIMIT 3")
etfs = json.loads(results)

# 2. 각 ETF의 상세 정보 조회
lines = []
for etf in etfs:
    info = json.loads(get_etf_info(etf_code=etf['code']))
    lines.append(f"\n### {info['name']} (보수율: {info.get('expense_ratio', 'N/A')})")
    lines.append('| 순위 | 종목 | 비중(%) |')
    lines.append('|---|---|---|')
    for i, h in enumerate(info.get('top_holdings', [])[:5], 1):
        lines.append(f"| {i} | {h['stock_name']} | {h['weight']} |")

final_answer('\n'.join(lines))$c$, $d$태그 ETF 조회 → for 루프 상세 조회 → 각 ETF별 보유종목 표$d$, 'active', NULL, NULL, NULL);

-- Example 17: 삼성전자를 10% 이상 보유한 ETF들의 최근 수익률을 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$삼성전자를 10% 이상 보유한 ETF들의 최근 수익률을 비교해줘$q$, $c$# 1. 삼성전자 코드 확인
search = stock_search(query='삼성전자')
stock_code = json.loads(search)[0]['code']

# 2. 삼성전자를 10% 이상 보유한 ETF 조회
results = graph_query(cypher=f"MATCH (e:ETF)-[h:HOLDS]->(s:Stock {{code: '{stock_code}'}}) WITH e, h ORDER BY h.date DESC WITH e, head(collect(h)) as latest WHERE latest.weight >= 10.0 RETURN {{code: e.code, name: e.name, weight: latest.weight, expense_ratio: e.expense_ratio}} ORDER BY latest.weight DESC")
etfs = json.loads(results)

# 3. 각 ETF 가격 조회
lines = ['| ETF | 보유비중 | 보수율 | 1개월 등락률 |', '|---|---|---|---|']
for etf in etfs:
    prices = json.loads(get_etf_prices(etf_code=etf['code'], period='1m'))
    s = prices['summary']
    lines.append(f"| {etf['name']} | {etf['weight']}% | {etf.get('expense_ratio', 'N/A')} | {s['change_rate']}% |")

final_answer('\n'.join(lines))$c$, $d$종목 검색 → 비중 조건 Cypher → for 루프 가격 조회$d$, 'active', NULL, NULL, NULL);

-- Example 18: 미래에셋자산운용과 삼성자산운용의 반도체 ETF를 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$미래에셋자산운용과 삼성자산운용의 반도체 ETF를 비교해줘$q$, $c$# 1. 미래에셋 반도체 ETF
result1 = graph_query(cypher="MATCH (e:ETF)-[:MANAGED_BY]->(c:Company {name: '미래에셋자산운용'}) MATCH (e)-[:TAGGED]->(t:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.net_assets DESC")
mirae = json.loads(result1)

# 2. 삼성 반도체 ETF
result2 = graph_query(cypher="MATCH (e:ETF)-[:MANAGED_BY]->(c:Company {name: '삼성자산운용'}) MATCH (e)-[:TAGGED]->(t:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.net_assets DESC")
samsung = json.loads(result2)

# 3. 각각 상위 2개씩 상세 조회
lines = ['## 미래에셋 반도체 ETF', '| ETF | 보수율 | 1개월수익률 |', '|---|---|---|']
for etf in mirae[:2]:
    info = json.loads(get_etf_info(etf_code=etf['code']))
    ret = info.get('returns', {}).get('1m', 'N/A')
    lines.append(f"| {info['name']} | {info.get('expense_ratio', 'N/A')} | {ret}% |")

lines.extend(['', '## 삼성 반도체 ETF', '| ETF | 보수율 | 1개월수익률 |', '|---|---|---|'])
for etf in samsung[:2]:
    info = json.loads(get_etf_info(etf_code=etf['code']))
    ret = info.get('returns', {}).get('1m', 'N/A')
    lines.append(f"| {info['name']} | {info.get('expense_ratio', 'N/A')} | {ret}% |")

final_answer('\n'.join(lines))$c$, $d$두 운용사×태그 교차 조회 → 각각 상세 조회 → 섹션별 비교$d$, 'active', NULL, NULL, NULL);

-- Example 19: 최근 1주 수익률 상위 3개 ETF의 보유종목과 유사 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$최근 1주 수익률 상위 3개 ETF의 보유종목과 유사 ETF를 알려줘$q$, $c$# 1. 1주 수익률 상위 3개 ETF
results = graph_query(cypher="MATCH (e:ETF) RETURN {code: e.code, name: e.name, return_1w: e.return_1w} ORDER BY e.return_1w DESC LIMIT 3")
top_etfs = json.loads(results)

lines = []
for etf in top_etfs:
    # 2. 상세 정보 (보유종목)
    info = json.loads(get_etf_info(etf_code=etf['code']))
    lines.append(f"\n### {info['name']} (1주 수익률: {etf.get('return_1w', 'N/A')}%)")
    lines.append('\n**상위 보유종목:**')
    lines.append('| 종목 | 비중 |')
    lines.append('|---|---|')
    for h in info.get('top_holdings', [])[:5]:
        lines.append(f"| {h['stock_name']} | {h['weight']}% |")

    # 3. 유사 ETF
    similar = json.loads(find_similar_etfs(etf_code=etf['code']))
    lines.append('\n**유사 ETF:**')
    lines.append('| ETF | 유사도 |')
    lines.append('|---|---|')
    for s in similar[:3]:
        lines.append(f"| {s['name']} | {s.get('similarity', '')} |")

final_answer('\n'.join(lines))$c$, $d$수익률 상위 ETF 조회 → for 루프 (상세 + 유사 ETF) → 섹션별 표$d$, 'active', NULL, NULL, NULL);

-- Example 20: 삼성전자 주가와 삼성전자를 가장 많이 보유한 ETF 3개의 가격을 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$삼성전자 주가와 삼성전자를 가장 많이 보유한 ETF 3개의 가격을 비교해줘$q$, $c$# 1. 삼성전자 코드 확인
search = stock_search(query='삼성전자')
stock_code = json.loads(search)[0]['code']

# 2. 삼성전자 주가 조회
stock_prices = json.loads(get_stock_prices(stock_code=stock_code, period='1m'))

# 3. 삼성전자를 가장 많이 보유한 ETF 3개
results = graph_query(cypher=f"MATCH (e:ETF)-[h:HOLDS]->(s:Stock {{code: '{stock_code}'}}) WITH e, h ORDER BY h.date DESC WITH e, head(collect(h)) as latest RETURN {{code: e.code, name: e.name, weight: latest.weight}} ORDER BY latest.weight DESC LIMIT 3")
etfs = json.loads(results)

# 4. 각 ETF 가격 조회
lines = ['| 종목/ETF | 시작가 | 최종가 | 등락률 |', '|---|---|---|---|']
ss = stock_prices['summary']
lines.append(f"| 삼성전자 | {ss['start_close']} | {ss['end_close']} | {ss['change_rate']}% |")

for etf in etfs:
    ep = json.loads(get_etf_prices(etf_code=etf['code'], period='1m'))
    es = ep['summary']
    lines.append(f"| {etf['name']} ({etf['weight']}%) | {es['start_close']} | {es['end_close']} | {es['change_rate']}% |")

final_answer('\n'.join(lines))$c$, $d$종목 검색 → 주가 조회 + 보유 ETF 조회 → for 루프 ETF 가격 → 통합 비교표$d$, 'active', NULL, NULL, NULL);

-- Example 21: 내 즐겨찾기 ETF의 수익률과 가격 추이를 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$내 즐겨찾기 ETF의 수익률과 가격 추이를 알려줘$q$, $c$# 1. 즐겨찾기 ETF 목록 조회 ($user_id는 시스템이 자동 주입)
results = graph_query(cypher="MATCH (u:User {user_id: $user_id})-[w:WATCHES]->(e:ETF) RETURN {code: e.code, name: e.name, return_1d: e.return_1d, return_1w: e.return_1w, return_1m: e.return_1m} ORDER BY w.added_at DESC")
if results == '조회 결과 없음':
    final_answer('즐겨찾기한 ETF가 없습니다.')
else:
    etfs = json.loads(results)

    # 2. 각 ETF 가격 추이 조회
    lines = ['| ETF | 코드 | 일간 | 주간 | 월간 | 최근종가 | 등락률 |', '|---|---|---|---|---|---|---|']
    for etf in etfs:
        prices = json.loads(get_etf_prices(etf_code=etf['code'], period='1m'))
        s = prices['summary']
        lines.append(f"| {etf['name']} | {etf['code']} | {etf.get('return_1d', 'N/A')}% | {etf.get('return_1w', 'N/A')}% | {etf.get('return_1m', 'N/A')}% | {s['end_close']} | {s['change_rate']}% |")
    final_answer('\n'.join(lines))$c$, $d$즐겨찾기 ETF graph_query ($user_id 패턴) → for 루프 가격 조회$d$, 'active', NULL, NULL, NULL);

-- Example 22: KODEX 200과 TIGER 200의 공통 보유종목 비중을 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$KODEX 200과 TIGER 200의 공통 보유종목 비중을 비교해줘$q$, $c$# 1. 두 ETF 코드 확인
search1 = etf_search(query='KODEX 200')
code1 = json.loads(search1)[0]['code']
search2 = etf_search(query='TIGER 200')
code2 = json.loads(search2)[0]['code']

# 2. 공통 보유종목과 각 비중 조회 (Cypher로 JOIN)
results = graph_query(cypher=f"MATCH (e1:ETF {{code: '{code1}'}})-[h1:HOLDS]->(s:Stock) WITH s, h1 ORDER BY h1.date DESC WITH s, head(collect(h1)) as lh1 MATCH (s)<-[h2:HOLDS]-(e2:ETF {{code: '{code2}'}}) WITH s, lh1, h2 ORDER BY h2.date DESC WITH s, lh1, head(collect(h2)) as lh2 RETURN {{stock_name: s.name, weight_etf1: lh1.weight, weight_etf2: lh2.weight}} ORDER BY lh1.weight DESC")
common = json.loads(results)

# 3. 표로 정리
lines = ['| 종목 | KODEX 200 비중 | TIGER 200 비중 | 차이 |', '|---|---|---|---|']
for c in common[:15]:
    diff = round(c['weight_etf1'] - c['weight_etf2'], 2)
    lines.append(f"| {c['stock_name']} | {c['weight_etf1']}% | {c['weight_etf2']}% | {diff}%p |")
final_answer('\n'.join(lines))$c$, $d$두 ETF 검색 → Cypher JOIN으로 공통 보유종목 비중 비교$d$, 'active', NULL, NULL, NULL);

-- Example 23: 반도체 ETF들의 보수율 통계와 추천 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$반도체 ETF들의 보수율 통계와 추천 ETF를 알려줘$q$, $c$# 1. 반도체 태그 보수율 통계 (집계 쿼리)
stats = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '반도체'}) WITH min(e.expense_ratio) as min_exp, max(e.expense_ratio) as max_exp, avg(e.expense_ratio) as avg_exp, count(e) as cnt RETURN {min_expense: min_exp, max_expense: max_exp, avg_expense: avg_exp, etf_count: cnt}")
stat = json.loads(stats)[0]

# 2. 보수율 낮은 순 상위 3개 ETF 상세 조회
results = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.expense_ratio ASC LIMIT 3")
top3 = json.loads(results)

details = []
for etf in top3:
    info = json.loads(get_etf_info(etf_code=etf['code']))
    details.append(info)

# 3. 통계 + 추천 표 정리
lines = [f"반도체 ETF {stat['etf_count']}개 통계: 평균 보수율 {stat['avg_expense']:.2f}%, 최저 {stat['min_expense']:.2f}%, 최고 {stat['max_expense']:.2f}%\n"]
lines.append('### 보수율 낮은 추천 ETF')
lines.append('| ETF | 보수율 | 1개월수익률 | 태그 |')
lines.append('|---|---|---|---|')
for d in details:
    ret = d.get('returns', {}).get('1m', 'N/A')
    lines.append(f"| {d['name']} | {d.get('expense_ratio', 'N/A')} | {ret}% | {', '.join(d.get('tags', []))} |")
final_answer('\n'.join(lines))$c$, $d$Cypher 집계(min/max/avg) → 상위 ETF 상세 조회 → 통계+추천 표$d$, 'active', NULL, NULL, NULL);

-- Example 24: 최근 신규 편입된 종목이 있는 ETF를 알려주고 해당 ETF 상세도 보여줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$최근 신규 편입된 종목이 있는 ETF를 알려주고 해당 ETF 상세도 보여줘$q$, $c$# 1. 신규 편입 변동이 있는 ETF 조회 (HAS_CHANGE 관계)
results = graph_query(cypher="MATCH (e:ETF)-[:HAS_CHANGE]->(c:Change {change_type: 'new'}) RETURN {etf_code: e.code, etf_name: e.name, stock_name: c.stock_name, weight: c.after_weight, detected_at: c.detected_at} ORDER BY c.detected_at DESC LIMIT 10")

if results == '조회 결과 없음':
    final_answer('최근 신규 편입된 종목 변동이 없습니다.')
else:
    changes = json.loads(results)
    # 중복 ETF 제거하여 상위 5개 ETF만
    seen = set()
    unique_etfs = []
    for c in changes:
        if c['etf_code'] not in seen:
            seen.add(c['etf_code'])
            unique_etfs.append(c)
        if len(unique_etfs) >= 5:
            break

    # 2. 각 ETF 상세 정보 조회
    lines = ['| ETF | 신규편입종목 | 편입비중 | 보수율 | 태그 |', '|---|---|---|---|---|']
    for etf in unique_etfs:
        info = json.loads(get_etf_info(etf_code=etf['etf_code']))
        tags = ', '.join(info.get('tags', []))
        lines.append(f"| {etf['etf_name']} | {etf['stock_name']} | {etf.get('weight', 'N/A')}% | {info.get('expense_ratio', 'N/A')} | {tags} |")
    final_answer('\n'.join(lines))$c$, $d$HAS_CHANGE 관계로 변동 조회 → 중복 제거 → for 루프 상세 조회$d$, 'active', NULL, NULL, NULL);

-- Example 25: 삼성전자가 많이 포함된 테마(태그)는 뭐야? 각 태그별 대표 ETF도 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$삼성전자가 많이 포함된 테마(태그)는 뭐야? 각 태그별 대표 ETF도 알려줘$q$, $c$# 1. 삼성전자 코드 확인
search = stock_search(query='삼성전자')
stock_code = json.loads(search)[0]['code']

# 2. 삼성전자를 보유한 ETF들의 태그 분포 조회
results = graph_query(cypher=f"MATCH (e:ETF)-[h:HOLDS]->(s:Stock {{code: '{stock_code}'}}) MATCH (e)-[:TAGGED]->(t:Tag) WITH t.name as tag_name, count(DISTINCT e) as etf_count RETURN {{tag_name: tag_name, etf_count: etf_count}} ORDER BY etf_count DESC")
tag_dist = json.loads(results)

# 3. 각 태그별 대표 ETF (순자산 최대) 조회
lines = ['| 태그 | ETF수 | 대표 ETF | 보수율 |', '|---|---|---|---|']
for tag in tag_dist[:7]:
    rep = graph_query(cypher=f"MATCH (e:ETF)-[:TAGGED]->(t:Tag {{name: '{tag['tag_name']}'}}) RETURN {{code: e.code, name: e.name, expense_ratio: e.expense_ratio}} ORDER BY e.net_assets DESC LIMIT 1")
    rep_etf = json.loads(rep)[0]
    lines.append(f"| {tag['tag_name']} | {tag['etf_count']}개 | {rep_etf['name']} | {rep_etf.get('expense_ratio', 'N/A')} |")
final_answer('\n'.join(lines))$c$, $d$종목 검색 → 태그 분포 집계 Cypher → for 루프 태그별 대표 ETF 조회$d$, 'active', NULL, NULL, NULL);

-- Example 26: AI이면서 반도체인 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$AI이면서 반도체인 ETF를 알려줘$q$, $c$# 1. AI와 반도체 태그를 모두 가진 ETF 조회
results = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t1:Tag {name: 'AI'}) MATCH (e)-[:TAGGED]->(t2:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio} ORDER BY e.net_assets DESC")
etfs = json.loads(results)

if not etfs:
    final_answer('AI와 반도체 태그를 모두 가진 ETF가 없습니다.')
else:
    # 2. 각 ETF 상세 조회
    lines = ['| ETF | 코드 | 보수율 | 1개월수익률 | 태그 |', '|---|---|---|---|---|']
    for etf in etfs:
        info = json.loads(get_etf_info(etf_code=etf['code']))
        ret = info.get('returns', {}).get('1m', 'N/A')
        tags = ', '.join(info.get('tags', []))
        lines.append(f"| {info['name']} | {info['code']} | {info.get('expense_ratio', 'N/A')} | {ret}% | {tags} |")
    final_answer('\n'.join(lines))$c$, $d$복수 태그 교차 MATCH → 빈 결과 분기 → for 루프 상세 조회$d$, 'active', NULL, NULL, NULL);

-- Example 27: 거래량이 가장 많은 ETF 5개를 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$거래량이 가장 많은 ETF 5개를 알려줘$q$, $c$# 1. 최근 거래량 상위 ETF 조회 (Price 노드에서 최신 거래량)
results = graph_query(cypher="MATCH (e:ETF)-[:HAS_PRICE]->(p:Price) WITH e, p ORDER BY p.date DESC WITH e, head(collect(p)) as latest RETURN {code: e.code, name: e.name, volume: latest.volume, trade_value: latest.trade_value, expense_ratio: e.expense_ratio} ORDER BY latest.volume DESC LIMIT 5")
etfs = json.loads(results)

# 2. 각 ETF 상세 조회
lines = ['| ETF | 코드 | 거래량 | 보수율 | 1개월수익률 |', '|---|---|---|---|---|']
for etf in etfs:
    info = json.loads(get_etf_info(etf_code=etf['code']))
    ret = info.get('returns', {}).get('1m', 'N/A')
    lines.append(f"| {info['name']} | {info['code']} | {etf.get('volume', 'N/A'):,} | {info.get('expense_ratio', 'N/A')} | {ret}% |")
final_answer('\n'.join(lines))$c$, $d$Price 노드 최신 거래량 기준 정렬 → for 루프 상세 조회$d$, 'active', NULL, NULL, NULL);

-- Example 28: 최근 시가총액이 가장 많이 늘어난 ETF 5개를 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$최근 시가총액이 가장 많이 늘어난 ETF 5개를 알려줘$q$, $c$# 1. 시가총액 주간 변화율 상위 ETF
results = graph_query(cypher="MATCH (e:ETF) WHERE e.market_cap_change_1w IS NOT NULL RETURN {code: e.code, name: e.name, market_cap_change_1w: e.market_cap_change_1w, expense_ratio: e.expense_ratio} ORDER BY e.market_cap_change_1w DESC LIMIT 5")
etfs = json.loads(results)

# 2. 각 ETF 상세 조회
lines = ['| ETF | 코드 | 시총변화(1주) | 보수율 | 태그 |', '|---|---|---|---|---|']
for etf in etfs:
    info = json.loads(get_etf_info(etf_code=etf['code']))
    tags = ', '.join(info.get('tags', []))
    lines.append(f"| {info['name']} | {info['code']} | {etf['market_cap_change_1w']}% | {info.get('expense_ratio', 'N/A')} | {tags} |")
final_answer('\n'.join(lines))$c$, $d$ETF 노드 market_cap_change_1w 기준 정렬 → for 루프 상세 조회$d$, 'active', NULL, NULL, NULL);

-- Example 29: 보수율 낮으면서 수익률 좋은 ETF를 추천해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$보수율 낮으면서 수익률 좋은 ETF를 추천해줘$q$, $c$# 1. 보수율 0.3% 이하 + 1개월 수익률 상위 ETF
results = graph_query(cypher="MATCH (e:ETF) WHERE e.expense_ratio <= 0.3 AND e.return_1m IS NOT NULL RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, return_1m: e.return_1m} ORDER BY e.return_1m DESC LIMIT 10")
etfs = json.loads(results)

# 2. 상세 조회
lines = ['| ETF | 보수율 | 1개월수익률 | 태그 |', '|---|---|---|---|']
for etf in etfs:
    info = json.loads(get_etf_info(etf_code=etf['code']))
    tags = ', '.join(info.get('tags', []))
    lines.append(f"| {info['name']} | {etf.get('expense_ratio', 'N/A')} | {etf['return_1m']}% | {tags} |")
final_answer('\n'.join(lines))$c$, $d$보수율 조건 WHERE + 수익률 정렬 → for 루프 상세 조회$d$, 'active', NULL, NULL, NULL);

-- Example 30: 반도체 3대장 합산 비중이 높은 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$반도체 3대장 합산 비중이 높은 ETF를 알려줘$q$, $c$# 1. 종목코드 확인
codes = []
for name in ['삼성전자', 'SK하이닉스', '삼성SDI']:
    search = stock_search(query=name)
    result = json.loads(search)
    if result:
        codes.append({'name': name, 'code': result[0]['code']})

# 2. 3종목을 모두 보유한 ETF에서 합산 비중 계산
code_list = [c['code'] for c in codes]
results = graph_query(cypher=f"MATCH (e:ETF)-[h:HOLDS]->(s:Stock) WHERE s.code IN ['{code_list[0]}', '{code_list[1]}', '{code_list[2]}'] WITH e, s, h ORDER BY h.date DESC WITH e, s, head(collect(h)) as latest WITH e, sum(latest.weight) as total_weight, count(s) as stock_count WHERE stock_count = 3 RETURN {{code: e.code, name: e.name, total_weight: total_weight, expense_ratio: e.expense_ratio}} ORDER BY total_weight DESC LIMIT 5")
etfs = json.loads(results)

# 3. 표 정리
lines = ['| ETF | 코드 | 합산비중 | 보수율 |', '|---|---|---|---|']
for etf in etfs:
    lines.append(f"| {etf['name']} | {etf['code']} | {round(etf['total_weight'], 2)}% | {etf.get('expense_ratio', 'N/A')} |")
final_answer('\n'.join(lines))$c$, $d$복수 종목 검색 → IN + 합산 비중 집계 Cypher → 정렬$d$, 'active', NULL, NULL, NULL);

-- Example 31: 1주 수익률과 1개월 수익률 차이가 큰 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$1주 수익률과 1개월 수익률 차이가 큰 ETF를 알려줘$q$, $c$# 1. 1주/1개월 수익률이 모두 있는 ETF 조회
results = graph_query(cypher="MATCH (e:ETF) WHERE e.return_1w IS NOT NULL AND e.return_1m IS NOT NULL RETURN {code: e.code, name: e.name, return_1w: e.return_1w, return_1m: e.return_1m, expense_ratio: e.expense_ratio}")
etfs = json.loads(results)

# 2. 수익률 차이 계산 후 절대값 기준 정렬
for etf in etfs:
    etf['diff'] = round(etf['return_1w'] - etf['return_1m'], 2)
sorted_etfs = sorted(etfs, key=lambda x: abs(x['diff']), reverse=True)[:10]

# 3. 표 정리
lines = ['| ETF | 1주수익률 | 1개월수익률 | 차이 | 보수율 |', '|---|---|---|---|---|']
for etf in sorted_etfs:
    lines.append(f"| {etf['name']} | {etf['return_1w']}% | {etf['return_1m']}% | {etf['diff']}%p | {etf.get('expense_ratio', 'N/A')} |")
final_answer('\n'.join(lines))$c$, $d$전체 ETF 조회 → Python에서 차이 계산 + abs 정렬 → 상위 추출$d$, 'active', NULL, NULL, NULL);

-- Example 32: 운용사별 ETF 개수와 평균 보수율을 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$운용사별 ETF 개수와 평균 보수율을 비교해줘$q$, $c$# 1. 운용사별 ETF 수, 평균 보수율 집계
results = graph_query(cypher="MATCH (e:ETF)-[:MANAGED_BY]->(c:Company) WITH c.name as company, count(e) as etf_count, avg(e.expense_ratio) as avg_expense RETURN {company: company, etf_count: etf_count, avg_expense: avg_expense} ORDER BY etf_count DESC")
companies = json.loads(results)

# 2. 표 정리
lines = ['| 운용사 | ETF 수 | 평균 보수율 |', '|---|---|---|']
for c in companies:
    lines.append(f"| {c['company']} | {c['etf_count']}개 | {c['avg_expense']:.2f}% |")
final_answer('\n'.join(lines))$c$, $d$Cypher 집계(count, avg) + GROUP BY 운용사 → 정렬$d$, 'active', NULL, NULL, NULL);

-- Example 33: 순자산 100억 이상 ETF 중 보수율이 낮은 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$순자산 100억 이상 ETF 중 보수율이 낮은 ETF를 알려줘$q$, $c$# 1. 순자산 100억(10,000,000,000원) 이상 + 보수율 오름차순
results = graph_query(cypher="MATCH (e:ETF) WHERE e.net_assets >= 10000000000 RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio, net_assets: e.net_assets} ORDER BY e.expense_ratio ASC LIMIT 10")
etfs = json.loads(results)

# 2. 상세 조회
lines = ['| ETF | 보수율 | 순자산 | 태그 |', '|---|---|---|---|']
for etf in etfs:
    info = json.loads(get_etf_info(etf_code=etf['code']))
    tags = ', '.join(info.get('tags', []))
    lines.append(f"| {info['name']} | {info.get('expense_ratio', 'N/A')} | {etf.get('net_assets', 'N/A')} | {tags} |")
final_answer('\n'.join(lines))$c$, $d$순자산 조건 WHERE + 보수율 정렬 → for 루프 상세 조회$d$, 'active', NULL, NULL, NULL);

-- Example 34: 삼성전자 주가와 반도체 ETF 수익률을 비교해줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$삼성전자 주가와 반도체 ETF 수익률을 비교해줘$q$, $c$# 1. 삼성전자 주가 조회
search = stock_search(query='삼성전자')
stock_code = json.loads(search)[0]['code']
stock_prices = json.loads(get_stock_prices(stock_code=stock_code, period='1m'))

# 2. 반도체 태그 ETF 상위 3개 가격 조회
results = graph_query(cypher="MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '반도체'}) RETURN {code: e.code, name: e.name} ORDER BY e.net_assets DESC LIMIT 3")
etfs = json.loads(results)

# 3. 각 ETF 가격 조회 + 통합 비교표
lines = ['| 종목/ETF | 시작가 | 최종가 | 등락률 |', '|---|---|---|---|']
ss = stock_prices['summary']
lines.append(f"| 삼성전자 | {ss['start_close']} | {ss['end_close']} | {ss['change_rate']}% |")

for etf in etfs:
    ep = json.loads(get_etf_prices(etf_code=etf['code'], period='1m'))
    es = ep['summary']
    lines.append(f"| {etf['name']} | {es['start_close']} | {es['end_close']} | {es['change_rate']}% |")

final_answer('\n'.join(lines))$c$, $d$종목 주가 + 태그 ETF 가격 → 주가 vs ETF 통합 비교표$d$, 'active', NULL, NULL, NULL);

-- Example 35: 삼성전자 비중이 늘어난 ETF를 알려줘
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$삼성전자 비중이 늘어난 ETF를 알려줘$q$, $c$# 1. 삼성전자 코드 확인
search = stock_search(query='삼성전자')
stock_code = json.loads(search)[0]['code']

# 2. 삼성전자를 보유한 ETF 중 비중이 증가한 ETF 조회
results = graph_query(cypher=f"MATCH (e:ETF)-[h:HOLDS]->(s:Stock {{code: '{stock_code}'}}) WITH e, h ORDER BY h.date DESC WITH e, collect(h) as holds WHERE size(holds) >= 2 WITH e, holds[0] as latest, holds[1] as prev WHERE latest.weight > prev.weight RETURN {{code: e.code, name: e.name, prev_weight: prev.weight, latest_weight: latest.weight, change: latest.weight - prev.weight, expense_ratio: e.expense_ratio}} ORDER BY latest.weight - prev.weight DESC LIMIT 10")

if results == '조회 결과 없음':
    final_answer('삼성전자 비중이 늘어난 ETF가 없습니다.')
else:
    etfs = json.loads(results)
    lines = ['| ETF | 이전비중 | 현재비중 | 변화 | 보수율 |', '|---|---|---|---|---|']
    for etf in etfs:
        lines.append(f"| {etf['name']} | {etf['prev_weight']}% | {etf['latest_weight']}% | +{round(etf['change'], 2)}%p | {etf.get('expense_ratio', 'N/A')} |")
    final_answer('\n'.join(lines))$c$, $d$종목 검색 → HOLDS 관계 이력 비교 Cypher(collect + 인덱싱) → 비중 증가 필터$d$, 'active', NULL, NULL, NULL);

-- Example 36: 특정 ETF에서 특정 종목의 비중이 급격히 변한 시점 찾기
INSERT INTO code_examples (question, code, description, status, embedding, created_by, source_chat_log_id)
VALUES ($q$KoAct 바이오헬스케어액티브에서 알테오젠 비중이 급격히 변한 시점을 알려줘$q$, $c$import datetime

# 1. ETF 코드 확인
search = etf_search(query='KoAct 바이오헬스케어')
etf_code = json.loads(search)[0]['code']

# 2. 종목 코드 확인
search = stock_search(query='알테오젠')
stock_code = json.loads(search)[0]['code']

# 3. 해당 ETF에서 해당 종목의 날짜별 비중 이력 조회 (기간 미지정 시 최근 1개월)
since = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
results = graph_query(cypher=f"MATCH (e:ETF {{code: '{etf_code}'}})-[h:HOLDS]->(s:Stock {{code: '{stock_code}'}}) WHERE h.date >= '{since}' RETURN {{date: h.date, weight: h.weight, shares: h.shares}} ORDER BY h.date")
history = json.loads(results)

# 4. 전일 대비 비중 변화량 계산
for i in range(len(history)):
    if i == 0:
        history[i]['change'] = 0.0
    else:
        history[i]['change'] = round(history[i]['weight'] - history[i-1]['weight'], 2)

# 5. 급변 구간 추출: 변화량 큰 상위 5일의 날짜 범위를 날짜순으로 표시
top5 = sorted(history, key=lambda x: abs(x['change']), reverse=True)[:5]
min_date = min(h['date'] for h in top5)
max_date = max(h['date'] for h in top5)
# 급변 구간 전일부터 포함하여 흐름을 보여줌
min_idx = max(0, next(i for i, h in enumerate(history) if h['date'] == min_date) - 1)
max_idx = next(i for i, h in enumerate(history) if h['date'] == max_date)
period = history[min_idx:max_idx + 1]

lines = [f'## 비중 급변 구간 ({period[0]["date"]} ~ {period[-1]["date"]})', '| 날짜 | 비중(%) | 보유수량 | 전일대비(%p) |', '|---|---|---|---|']
for h in period:
    lines.append(f"| {h['date']} | {h['weight']:.2f}% | {h['shares']}주 | {h['change']:+.2f}%p |")
lines.extend(['', '## 전체 비중 이력', '| 날짜 | 비중(%) | 보유수량 | 전일대비(%p) |', '|---|---|---|---|'])
for h in history:
    lines.append(f"| {h['date']} | {h['weight']:.2f}% | {h['shares']}주 | {h['change']:+.2f}%p |")
final_answer('\n'.join(lines))$c$, $d$ETF+종목 검색 → graph_query로 날짜별 HOLDS 이력 전체 조회 → 전일대비 변화량 계산 → 급변 시점 정렬$d$, 'active', NULL, NULL, NULL);
