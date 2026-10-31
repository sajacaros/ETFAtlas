# ETF Atlas 챗봇 도구(Tool) 정리

## 개요

> 범위: 답변 화면의 `agent` 스킬 안에서 도는 tool-calling 에이전트(`ChatService`)와 그 도구.
> 챗봇 전체 흐름은 웹 화면의 Architecture 페이지(`frontend/public/architecture.html`), 레이아웃·스킬 구현은 [answer-skills.md](answer-skills.md)를 본다.

`ChatService`는 **pydantic-ai** tool-calling 에이전트이며, **6개의 커스텀 도구**와 **답변 화면의 데이터 스킬 중 `tool = True`인 13개**(아래 '스킬 도구')를 가진다.
레이아웃 설계가 스킬로 표현할 수 없는 질문(태그·운용사별 목록, 유사 ETF, 비중 변화, 복잡한 그래프 조건 등)이나 설계에 실패한 질문을 `agent` 슬롯으로 넘기면 이 에이전트가 마크다운으로 답한다.
커스텀 도구는 `backend/app/services/chat_service.py`에, 스킬 도구는 `backend/app/services/answer/tools.py`가 만든다.
ETF 정보·가격 추이·비교처럼 스킬이 있는 일은 스킬 도구가 맡는다 — 예전의 `get_etf_info`·`get_etf_prices`·`get_stock_prices`·`compare_etfs`는 없앴다 (아래 '없앤 도구').

---

## 도구 목록

### 1. etf_search - ETF 검색

| 항목 | 내용 |
|------|------|
| **클래스** | `ETFSearchTool` |
| **용도** | ETF를 이름이나 코드로 검색 (KODEX, TIGER, ARIRANG 등) |
| **데이터 소스** | Apache AGE 그래프 DB (Cypher 쿼리) |

**입력**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `query` | string | O | 검색 키워드 (ETF 이름 또는 코드) |

**출력**: 최대 10건의 ETF 목록 (JSON). 숫자 열은 아래 '도구 결과의 서식'대로 바뀐다
```json
[{"code": "069500", "name": "KODEX 200", "expense_ratio": "0.15%"}]
```

**Cypher 패턴**
```cypher
MATCH (e:ETF)
WHERE toLower(e.name) CONTAINS toLower($query) OR e.code CONTAINS $query
RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio}
ORDER BY e.name LIMIT 10
```

---

### 2. stock_search - 주식 종목 검색

| 항목 | 내용 |
|------|------|
| **클래스** | `StockSearchTool` |
| **용도** | 개별 주식 종목(삼성전자, SK하이닉스 등)을 이름이나 코드로 검색 |
| **데이터 소스** | Apache AGE 그래프 DB (Cypher 쿼리) |

**입력**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `query` | string | O | 검색 키워드 (종목 이름 또는 코드) |

**출력**: 최대 10건의 종목 목록 (JSON)
```json
[{"code": "005930", "name": "삼성전자"}]
```

---

### 3. list_tags - 태그/테마 목록 조회

| 항목 | 내용 |
|------|------|
| **클래스** | `ListTagsTool` |
| **용도** | 그래프 DB에 등록된 모든 태그(테마)와 각 태그별 ETF 수 조회 |
| **데이터 소스** | `GraphService.get_all_tags()` |

**입력**: 없음 (파라미터 없는 도구)

**출력**: 태그 목록과 ETF 수 (JSON)
```json
[{"name": "반도체", "count": 15}, {"name": "배당", "count": 12}]
```

---

### 4. find_similar_etfs - 유사 ETF 조회

| 항목 | 내용 |
|------|------|
| **클래스** | `FindSimilarETFsTool` |
| **용도** | 특정 ETF와 보유종목 비중이 유사한 ETF 검색 |
| **데이터 소스** | `GraphService.find_similar_etfs()` |

**입력**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `etf_code` | string | O | ETF 종목코드 (예: '069500') |

**출력**: 유사 ETF 목록 (JSON)
```json
[
  {"etf_code": "102110", "name": "TIGER 200", "overlap": 180, "similarity": "92.50%"}
]
```

**유사도 계산**: 각 ETF의 현재 보유종목(`CURRENT_HOLDS`) 비중(weight) 겹침 기반 overlap 방식

---

### 5. get_holdings_changes - 보유종목 변화 조회

| 항목 | 내용 |
|------|------|
| **클래스** | `GetHoldingsChangesTool` |
| **용도** | ETF의 보유종목 비중 변화 추적 (신규편입/제외/비중증감) |
| **데이터 소스** | `GraphService.get_etf_holdings_changes()` |

**입력**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `etf_code` | string | O | ETF 종목코드 (예: '069500') |
| `period` | string | - | 비교 기간: `'1d'`(전거래일, 기본값), `'1w'`(1주), `'1m'`(1개월) |

**출력**: 변동 내역 목록 (JSON, `unchanged`는 필터링됨)
```json
[
  {"stock_code": "005930", "stock_name": "삼성전자", "change_type": "increased", "old_weight": 14.5, "new_weight": 15.5},
  {"stock_code": "000660", "stock_name": "SK하이닉스", "change_type": "added", "old_weight": null, "new_weight": 3.2}
]
```

**변화 유형**: `added`(신규편입), `removed`(제외), `increased`(비중증가), `decreased`(비중감소)

---

### 6. graph_query - 그래프 DB 직접 쿼리

| 항목 | 내용 |
|------|------|
| **클래스** | `GraphQueryTool` |
| **용도** | Apache AGE에 Cypher 쿼리 직접 실행 (다른 도구로 해결 안 되는 복잡한 관계 질문용) |
| **데이터 소스** | Apache AGE (Cypher 직접 실행) |
| **보안** | 별도 연결의 읽기 전용 트랜잭션(`SET TRANSACTION READ ONLY`) + `statement_timeout` 10초로 실행. 쓰기는 DB가 거부한다. 쿼리가 SQL의 `$$` 안에 들어가므로 `$$`·`;`가 있으면 실행 전에 거부(모든 `execute_cypher` 호출도 `$$`를 거부). 문법 오류는 오류 메시지를 LLM에 돌려준다 |

**입력**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `cypher` | string | O | Cypher 쿼리 (MATCH로 시작, RETURN은 단일 맵으로 감싸기) |

**출력**: 쿼리 결과 (JSON)

**그래프 스키마**
```
노드:
  - ETF(code, name, expense_ratio, base_index, listed_date, description, dividend_cycle, dividend_yield, dividend_per_share, net_assets, close_price, return_1d, return_1w, return_1m, market_cap_change_1w, updated_at)
  - Stock(code, name, is_etf)
  - Company(name)
  - Tag(name)
  - Price(date, open, high, low, close, volume, nav, market_cap, net_assets, trade_value, change_rate)
  - User(user_id)

관계:
  - (ETF)-[:CURRENT_HOLDS {date, weight, shares}]->(Stock)  = 현재 구성종목 (ETF당 비중 상위 30개)
  - (ETF)-[:HOLDS {date, weight, shares}]->(Stock)          = 날짜별 구성종목 이력 (비중 변화 비교에만 사용)
  - (ETF)-[:MANAGED_BY]->(Company)
  - (ETF)-[:TAGGED]->(Tag)
  - (ETF)-[:HAS_PRICE]->(Price), (Stock)-[:HAS_PRICE]->(Price)
  - (User)-[:WATCHES {added_at}]->(ETF)
```

**Cypher 작성 규칙**
1. MATCH로 시작하는 읽기 전용 쿼리만 가능
2. RETURN은 반드시 단일 맵: `RETURN {key1: val1, key2: val2}`
3. 문자열 값은 작은따옴표: `{code: '005930'}`
4. 집계 함수 + ORDER BY는 WITH 절로 분리
5. weight, expense_ratio, dividend_yield, return_*, net_assets는 숫자로 저장된다(비중·보수율·수익률은 % 단위, 순자산은 원). 결과에 붙는 `%`·`억원`은 표시용 서식이므로 조건은 숫자로 쓴다 (예: `h.weight >= 10`, `e.expense_ratio <= 0.1`)
6. `CURRENT_HOLDS`는 ETF당 비중 상위 30개뿐이라 엣지가 없으면 미보유이거나 30위 밖(사실상 0)이다. 특정 종목 비중이 낮은 ETF는 후보 ETF(태그 등)에서 MATCH로 출발하고 종목은 `OPTIONAL MATCH` + `coalesce(sum(h.weight), 0)`로 붙인다. `MATCH`로 붙이면 미보유 ETF가 결과에서 빠진다

**쿼리 예시**
```cypher
-- ETF의 현재 보유종목 (현재 구성종목은 항상 CURRENT_HOLDS)
MATCH (e:ETF {code: '069500'})-[h:CURRENT_HOLDS]->(s:Stock)
RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight}
ORDER BY h.weight DESC LIMIT 10

-- 특정 종목을 보유한 ETF (비중 내림차순)
MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {name: '삼성전자'})
RETURN {etf_code: e.code, etf_name: e.name, weight: h.weight}
ORDER BY h.weight DESC

-- 특정 종목의 ETF 내 비중 이력 (HOLDS는 이력 비교에만)
MATCH (e:ETF {code: '069500'})-[h:HOLDS]->(s:Stock {name: '삼성전자'})
RETURN {date: h.date, weight: h.weight} ORDER BY h.date

-- 태그별 ETF 조회
MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '반도체'})
RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio}

-- 운용사별 ETF
MATCH (e:ETF)-[:MANAGED_BY]->(c:Company)
WHERE c.name CONTAINS '삼성'
RETURN {code: e.code, name: e.name, company: c.name}

-- 두 종목을 동시에 보유한 ETF
MATCH (e:ETF)-[h1:CURRENT_HOLDS]->(s1:Stock {code: '005930'})
MATCH (e)-[h2:CURRENT_HOLDS]->(s2:Stock {code: '095610'})
WITH e, h1, h2, h1.weight + h2.weight AS total_weight
ORDER BY total_weight DESC
LIMIT 5
RETURN {etf_code: e.code, etf_name: e.name, weight_samsung: h1.weight, weight_tes: h2.weight, total_weight: total_weight}
```

### 도구 결과의 서식

커스텀 도구는 결과의 숫자 열을 답변 화면 요약과 같은 서식(`app/domain/format.py`의 `format_value`)으로 바꿔 넘긴다 (`chat_service.format_fields`). LLM이 단위를 헷갈리지 않게 하려는 것이다.

| 열 | 서식 | 예 |
|---|---|---|
| `expense_ratio`, `weight`, `similarity`, `return_*`, `change_rate`, `market_cap_change_1w`, 비중 변화 열 | `percent` | `0.15%` |
| `net_assets`, `market_cap`, `trade_value` 등 금액 | `krw` (1억원 미만은 원 단위) | `12조 3,456억원`, `5,000,000원` |

예전에는 금액을 도구마다 `12,345억원`처럼 억 단위로만 적어 스킬 요약(`1조 2,345억원`)과 달랐다.

---

## 스킬 도구 (`answer/tools.py`)

답변 화면의 데이터 스킬 중 `tool = True`인 것은 agent도 같은 인자 스키마(스킬의 `Args`)로 부른다. 스킬을 하나 만들고 `tool`을 켜면 플래너와 agent 양쪽에서 쓰인다 — 같은 기능을 도구로 따로 만들지 않는다.

| 도구(스킬) | 하는 일 |
|---|---|
| `company_financials` | DART 분기·연간 실적, 영업이익률, 부채비율 |
| `company_valuation` | 시가총액, PER(최근 4분기·직전 연도), PBR, ROE, FCF·FCF 수익률·역산 DCF 성장률, 대조용 KIS PER·PBR |
| `company_type` | 유형 판정(지속 성장주·턴어라운드주·경기민감·성숙기·신흥·초기 단계)의 숫자 기준과 연도별 영업현금흐름·FCF |
| `company_disclosures` | 최근 DART 공시 목록 |
| `stock_technical` | 차트 분석: 이동평균·볼린저·MACD·RSI·스토캐스틱과 대가들의 규칙으로 본 신호 |
| `period_returns` | ETF 기간별 수익률 (1일~1년) |
| `rank` | ETF·종목 후보를 수익률·순자산·총보수·분배율로 정렬·필터 |
| `overlap` | 두 ETF의 공통 종목과 겹치는 비중 |
| `portfolio_lookthrough` | ETF·종목 포트폴리오의 종목별 합산 비중 |
| `etf_compare` | ETF 기본 정보(운용사·기초지수·총보수·순자산·1일·1주 수익률·분배·상장일). 도구로는 ETF 하나도 받는다(`tool_args`) |
| `holdings` | ETF 하나의 구성종목과 비중 (상위 최대 30개) |
| `price_trend` | ETF 가격 추이 (기간 시작·끝 종가, 등락률, 최고·최저) |
| `stock_trend` | 종목 가격 추이 |

- 결과는 슬롯과 같은 요약(`summary`)과 주석이다. 화면 슬롯과 agent 답이 같은 숫자를 읽는다.
- 인자가 스키마에 맞지 않으면 오류를 모델에게 돌려줘 다시 부르게 한다(`ModelRetry`). 슬롯의 `'@이름.순위'` 참조는 도구에서 쓸 수 없다 — 이름이나 코드를 적는다.
- 부를 때마다 DB 세션을 따로 열어 스킬 도구끼리는 병렬로 돈다. 공유 세션을 쓰는 커스텀 도구 6개는 `sequential=True`라 순차로 돈다(pydantic-ai에서 장벽).
- 도구로 부를 때 인자 모델을 바꿔야 하는 스킬은 `tool_args`를 둔다 (`etf_compare`: 화면 슬롯은 ETF 2~5개, 도구는 1~5개).
- 스킬 도구 목록은 `agent` 스킬이 그 답변의 레지스트리(`SkillContext.registry`)에서 만들어 `ChatService`에 넣는다. `chat_service`는 `answer/`를 가져오지 않는다.

### 없앤 도구

스킬과 하는 일이 겹쳐 없앴다. 같은 질문은 스킬 도구가 답한다.

| 없앤 도구 | 대신 | 달라진 점 |
|---|---|---|
| `get_etf_info` | `etf_compare`(기본 정보) + `holdings`(구성종목) + `period_returns`(기간 수익률) | 수익률을 달력일로 직접 세지 않고 화면과 같은 기준(기간 전 마지막 거래일)으로 계산한다. 태그·운용사 설명(`description`)은 `graph_query`로 |
| `get_etf_prices` | `price_trend` | 일별 원시 데이터 대신 기간 요약(시작·끝 종가, 등락률, 최고·최저)을 돌려준다 |
| `get_stock_prices` | `stock_trend` (보조지표는 `stock_technical`) | 위와 같다 |
| `compare_etfs` | `etf_compare` (+ `holdings`·`period_returns`) | 태그·상위 보유종목은 비교표에 없다 |

- 해결 절차 예시(`code_examples`)와 승인된 로그의 `generated_code`에는 없앤 도구를 부르는 예시가 남아 있다. 에이전트가 없는 도구를 부르지 않도록 그런 예시는 프롬프트에 넣지 않는다 (`chat_service.usable_examples`, 뺀 예시 id는 로그에 남는다). 시드(`docker/db/seed/code_examples.py`)와 DB의 예시를 새 도구 이름으로 옮기면 다시 쓰인다.

---

## 도구 요약표

| # | 도구명 | 용도 | 입력 | 데이터 소스 |
|---|--------|------|------|-------------|
| 1 | `etf_search` | ETF 검색 | query, limit? | AGE |
| 2 | `stock_search` | 주식 종목 검색 | query, limit? | AGE |
| 3 | `list_tags` | 태그/테마 목록 | (없음) | AGE |
| 4 | `find_similar_etfs` | 유사 ETF 조회 | etf_code | AGE |
| 5 | `get_holdings_changes` | 보유종목 변화 | etf_code, period? | AGE |
| 6 | `graph_query` | Cypher 직접 실행 | cypher | AGE |
| - | 스킬 도구 13개 | 위 '스킬 도구' 표 | 스킬의 `Args` (이름·코드를 그대로) | AGE + PG |

> **AGE** = Apache AGE 그래프 DB, **PG** = PostgreSQL

---

## 에이전트의 도구 활용 방식

### 실행 흐름

질문 재작성과 대화 기억은 답변 화면 오케스트레이터(`AnswerService`)가 먼저 처리하고, `agent` 스킬은 재작성된 질문을 넘긴다. `ChatService`에는 재작성 단계가 없다.

```
agent 스킬                  ← 대화 맥락(세션 요약 + 최근 5턴)은 AnswerService가 읽어 SkillContext로 넘긴다
    ↓
ChatService._build_prompt() ← 유사 해결 절차 예시(재작성 질문으로 검색) + 대화 맥락 + 재작성 질문
    ↓
agent.run_stream_events(prompt)  ← instructions = 시스템 프롬프트 + 태그 목록
    ↓
┌─────────────────────────────────────────────────┐
│  tool-calling 루프 (모델 요청 최대 15회)             │
│                                                   │
│  1. LLM이 도구 호출(JSON 인자)을 반환 — 여러 개 병렬 가능 │
│  2. 도구 실행 → 결과를 LLM에 전달                    │
│  3. 반복하다가 도구 호출 없이 텍스트를 반환하면 종료     │
└─────────────────────────────────────────────────┘
    ↓
최종 답변 마크다운 → agent 슬롯 내용 (실행 단계는 step 이벤트로 화면에)
```

### 세션과 대화 기억

대화는 `chat_sessions` 단위로 서버에 저장된다. 첫 질문에서 `session_id` 없이 요청하면 서버가 세션을 만들고(제목 = 첫 질문 앞 50자) SSE `session` 이벤트로 알려 준다.

- **최근 턴**: 세션의 마지막 `CHAT_HISTORY_WINDOW`(기본 5)개 턴은 `chat_logs` 원문 그대로 맥락에 넣는다. 질문은 재작성본이 있으면 그것을, 답변은 앞 1,500자만 쓴다.
- **요약**: window 밖으로 밀려난 턴은 `chat_sessions.summary`에 누적 요약한다. 기존 요약 + 새로 밀려난 턴을 LLM이 다시 요약하고, 반영한 마지막 로그 id를 `summarized_until_log_id`에 기록한다. 답변을 보낸 뒤에 실행하므로 사용자는 기다리지 않는다. 실패하면 다음 질문 시작 때 다시 시도한다.
- **질문 재작성(refine)**: 맥락이 있으면 에이전트 실행 전에 질문을 독립 질문으로 바꾼다 (`chat_memory_prompt.py`). 바뀌면 `chat_logs.refined_question`에 남기고 화면에 "→ 재작성 질문"으로 보여 준다.
  - `그거랑 비슷한 ETF 3개는?` → `KODEX 200(069500)과 비슷한 ETF 3개는?`
  - `두 번째 거 보수율은?` → `ACE 200(105190)의 보수율은?`
  - `SK하이닉스는?` (직전: 삼성전자를 가장 많이 보유한 ETF 3개는?) → `SK하이닉스를 가장 많이 보유한 ETF 3개는?`
  - 새 주제면 그대로 둔다. 빈 응답·여러 줄·지나치게 긴 출력은 버리고 원문을 쓴다.
- 요약·재작성은 일반화와 같이 추론을 끄고 호출한다 (재작성 약 0.5~1초).
- 재작성 질문은 few-shot 예시 검색에도 쓰고, 관리자가 로그를 예시로 임베딩할 때 기본 질문으로 채워진다 (`그거 보수율은?` 같은 원문은 예시로 쓸모가 없다).
- 실행 과정(step 목록, SSE `step` 이벤트와 같은 형식)은 `chat_logs.steps`에 저장해 세션을 다시 열 때도 보여 준다. few-shot용 `generated_code`도 같은 목록에서 만든다.
- 세션을 지워도 `chat_logs`는 관리자 검수용으로 남고 `session_id`만 `NULL`이 된다.

### 도구 실행 방식

- 도구 인자는 JSON 스키마로 검증하고, 잘못된 인자는 재시도 프롬프트(`RetryPromptPart`)로 LLM에 되돌린다 → step의 `error`로 표시
- 독립적인 조회는 한 번의 모델 응답에서 여러 도구를 호출할 수 있다. 다만 도구들이 DB 세션 하나를 공유하므로 `sequential=True`로 등록해 실제 실행은 순차로 한다
- 정렬·필터링은 LLM이 결과를 보고 직접 하거나, 대상이 많으면 `graph_query`의 ORDER BY/LIMIT을 쓰도록 프롬프트로 안내

### 도구 등록 방식

각 도구는 `ChatTool` 서브클래스로 `name`, `description`, `inputs`(JSON 스키마 properties, `nullable: True`면 선택 인자), `forward()`를 정의한다.
`ChatTool.as_agent_tool()`이 `pydantic_ai.Tool.from_schema(...)`로 변환한다. 선택 인자에 `null`이 오면 `forward()` 기본값을 쓴다.

### 실제 질의 흐름 예시

#### 예시 1: "삼성전자를 가장 많이 보유한 ETF는?"

```
[Step 1] stock_search(query="삼성전자")
         → [{"code": "005930", "name": "삼성전자"}]
[Step 2] graph_query(cypher="MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {code: '005930'}) RETURN {etf_code: e.code, etf_name: e.name, weight: h.weight} ORDER BY h.weight DESC LIMIT 5")
         → [{"etf_code": "069500", "etf_name": "KODEX 200", "weight": "30.50%"}, ...]
[답변]   | ETF | 코드 | 비중 | ... 마크다운 표
```

#### 예시 2: "KODEX 200과 TIGER 200 비교해줘"

```
[Step 1] etf_compare(etfs=["KODEX 200", "TIGER 200"])     ┐ 한 번의 모델 응답에서 병렬 호출
[Step 2] period_returns(etfs=["KODEX 200", "TIGER 200"])  ┘ (스킬 도구는 이름을 그대로 받는다)
[답변]   비교 표
```

### 도구 사용 순서 가이드라인 (시스템 프롬프트)

1. **종목명** 등장 → `stock_search`로 코드 먼저 확인
2. **태그/테마** 등장 → instructions의 태그 목록에서 정확한 태그명 확인
3. **ETF명** 등장 → `etf_search`로 코드 먼저 확인
4. 확인된 코드/태그명으로 → **전용 도구** 실행
5. ETF 기본정보·비교 → `etf_compare`(하나도 됨), 구성종목 → `holdings`, 기간 수익률 → `period_returns`, 가격 추이 → `price_trend`·`stock_trend`
6. 전용 도구로 불가능한 복잡한 관계 → `graph_query`로 Cypher 직접 작성
7. 실적·밸류에이션·공시·차트 분석·순위·겹침·포트폴리오 합산 → 스킬 도구 ('분석 도구'로 instructions에 붙는다)

### 에이전트 설정

```python
# agent 스킬 (answer/skills/agent.py)
service = ChatService(db, ctx.ai_config, skill_tools(ctx.registry, ctx.session_factory))

# ChatService
agent = Agent(build_model(config),      # llm.build_model: 접속 설정별로 캐시, 요청 타임아웃 LLM_TIMEOUT(120초)
              instructions=..., tools=[t.as_agent_tool() for t in tools] + skill_tools)
agent.run_stream_events(prompt, usage_limits=UsageLimits(request_limit=15))
```

| 설정 | 값 | 설명 |
|------|-----|------|
| LLM | `LLM_MODEL` (기본 qwen38-27b) | LiteLLM 프록시(OpenAI 호환), `pydantic-ai-slim[openai]` |
| 최대 모델 요청 | 15 | 무한 루프 방지 (`UsageLimitExceeded`면 실패로 마친다) |
| 요청 타임아웃 | 120초 | `llm.LLM_TIMEOUT`. 흘려받을 때는 조각 사이 간격에 걸린다 |
| 대화 히스토리 | 세션 요약 + 최근 5턴 | `CHAT_HISTORY_WINDOW`. 질문 재작성과 프롬프트 "참고용" 맥락에 사용 |
| 관찰 결과 제한 | 2,000자 | `OBSERVATION_CHARS` — step 이벤트(실행 과정 패널·로그)에만. 모델은 전부 받는다 |
| few-shot 예제 | 유사 해결 절차 최대 3개 | `code_examples` pgvector 검색 (`EMBEDDING_MODEL`, 768차원, `EMBEDDING_API_KEY`) |

### 해결 절차 예시(few-shot)와 피드백 루프

- `code_examples.code`에는 도구 호출을 `name(key="value")` 형태로 한 줄에 하나씩 저장한다. 목적은 질문 유형별로 맞는 **Cypher 패턴**을 보여 주는 것이다.
- 시드 예시 39개의 원본은 `docker/db/seed/code_examples.py`다. 고유명사는 `<종목명>`, `<ETF명>`, `<운용사>` 자리표시자로 두고, 종목·ETF·운용사는 Cypher에서 이름으로 바로 매칭한다(`stock_search` 호출 불필요). 고친 뒤 `python docker/db/seed/code_examples.py > docker/db/init/03_seed_code_examples.sql`로 SQL을 다시 만든다.
- 프롬프트에는 일반화된 질문(`question_generalized`)과 함께 들어가고, LLM은 자리표시자를 현재 질문의 값으로 바꿔 쓴다.
- 검색할 때도 사용자 질문을 같은 프롬프트로 일반화한 뒤 임베딩한다(`현대차와 기아…` → `특정 종목 2개…`). 일반화는 추론을 끄고 호출해 0.2~0.4초 걸린다.
- 채팅 로그의 `generated_code`는 성공한 도구 호출을 `name(key="value")` 한 줄씩 이어 붙인 것 → 관리자가 승인해 임베딩하면 새 예시가 된다

### 에러 처리

1. 정상 종료 → 최종 텍스트, `result=completed`
2. 중지 → 그때까지의 답(없으면 중지 안내 문구), `result=cancelled`
3. 요청 한도 초과·예외로 답을 쓰지 못함 → `result=failed`, 답은 `"죄송합니다. 답변 생성에 실패했습니다. 다시 질문해 주세요."`. 예전처럼 마지막 도구 결과(원시 JSON)를 답으로 내지 않는다
4. `agent` 스킬은 `result`로 실패를 판정해 슬롯을 `failed`("답변을 만들지 못했습니다")로 마감한다

### 스트리밍 동작

`POST /api/chat/message/stream` 엔드포인트는 SSE(Server-Sent Events)로 실시간 전달:

```json
// 맨 처음: 이 대화의 세션 (새로 만들었으면 새 id)
{"type": "session", "data": {"session_id": 12, "title": "KODEX 200 정보 알려줘"}}

// 질문을 맥락으로 재작성했으면
{"type": "refined_question", "data": {"question": "KODEX 200(069500)의 보수율은?"}}

// 유사 예시가 있으면
{"type": "matched_examples", "data": {"examples": [...]}}

// 도구 호출 1건마다 (code = 도구 호출 표기)
{"type": "step", "data": {"step_number": 1, "code": "etf_search(query=\"KODEX\")", "observations": "...", "tool_calls": [...], "error": null}}

// 최종 답변 (result: completed | cancelled | failed | clarifying)
{"type": "answer", "data": {"answer": "최종 답변 텍스트", "result": "completed"}}

// 스트림 도중 예상하지 못한 오류 (내부 오류 문구는 로그에만, 화면에는 고정 문구)
{"type": "error", "data": {"message": "답변 중 오류가 발생했습니다. 잠시 뒤 다시 질문해 주세요."}}

// 로그 저장 후
{"type": "chat_log_id", "data": {"chat_log_id": 345}}
```

세션 API: `GET /api/chat/sessions`(최근 활동 순, 커서 페이징 — `limit` 기본 30, 응답 `{items, next_cursor}`의 `next_cursor`를 다음 요청의 `cursor`로. 커서는 마지막 항목의 `(updated_at, id)`이고 `null`이면 마지막 페이지. 대화 목록은 끝까지 스크롤하면 다음 페이지를 불러온다), `GET /api/chat/sessions/{id}`(전체 대화·실행 과정 + 요약), `PATCH /api/chat/sessions/{id}`(`{title}`), `DELETE /api/chat/sessions/{id}`. 다른 사용자의 세션은 `404`.

프론트엔드에서 각 스텝을 접이식 UI로 표시하여 에이전트의 도구 호출 과정을 실시간으로 확인 가능합니다.
