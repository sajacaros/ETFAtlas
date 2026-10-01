# ETF Atlas 챗봇 도구(Tool) 정리

## 개요

ETF Atlas 챗봇은 **pydantic-ai** tool-calling 에이전트를 사용하며, 총 **10개의 커스텀 도구**를 제공합니다.
모든 도구는 `backend/app/services/chat_service.py`에 정의되어 있습니다.

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

**출력**: 최대 10건의 ETF 목록 (JSON)
```json
[{"code": "069500", "name": "KODEX 200", "expense_ratio": 0.15}]
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

### 4. get_etf_info - ETF 종합 정보 조회

| 항목 | 내용 |
|------|------|
| **클래스** | `GetETFInfoTool` |
| **용도** | ETF의 기본정보, 운용사, 태그, 상위 보유종목 10개, 최근 수익률 종합 조회 |
| **데이터 소스** | Apache AGE (기본정보/태그/보유종목) + PostgreSQL (가격/수익률) |

**입력**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `etf_code` | string | O | ETF 종목코드 (예: '069500') |

**출력**: ETF 종합 정보 (JSON)
```json
{
  "code": "069500",
  "name": "KODEX 200",
  "expense_ratio": 0.15,
  "company": "삼성자산운용",
  "tags": ["대형주", "시장대표"],
  "top_holdings": [
    {"stock_code": "005930", "stock_name": "삼성전자", "weight": 30.5}
  ],
  "returns": {"1w": 1.23, "1m": 3.45, "3m": -2.10}
}
```

**내부 동작**: 4개의 하위 쿼리 실행
1. 기본정보 + 운용사 (Cypher: `ETF → MANAGED_BY → Company`)
2. 태그 (Cypher: `ETF → TAGGED → Tag`)
3. 상위 보유종목 10개 (Cypher: `ETF → HOLDS → Stock`, 최신 날짜 기준)
4. 최근 수익률 1주/1개월/3개월 (`ETFService.get_etf_prices()`)

---

### 5. find_similar_etfs - 유사 ETF 조회

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
  {"etf_code": "102110", "name": "TIGER 200", "overlap": 180, "similarity": 92.5}
]
```

**유사도 계산**: 보유종목 비중(weight) 겹침 기반 overlap 방식

---

### 6. get_holdings_changes - 보유종목 변화 조회

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

### 7. get_etf_prices - ETF 가격 추이 조회

| 항목 | 내용 |
|------|------|
| **클래스** | `GetETFPricesTool` |
| **용도** | ETF의 과거 가격 데이터 (종가, 거래량, 시가총액, 순자산총액) 조회 |
| **데이터 소스** | `ETFService.get_etf_prices()` (PostgreSQL) |

**입력**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `etf_code` | string | O | ETF 종목코드 (예: '069500') |
| `period` | string | - | 조회 기간: `'1w'`, `'1m'`(기본값), `'3m'`, `'6m'`, `'1y'` |

**출력**: 요약 통계 + 일별 데이터 (JSON)
```json
{
  "summary": {
    "etf_code": "069500", "period": "1m", "data_count": 22,
    "start_date": "2026-01-12", "end_date": "2026-02-12",
    "start_close": 35000, "end_close": 36500,
    "high": 37000, "low": 34500, "change_rate": 4.29,
    "avg_volume": 1234567,
    "latest_market_cap": 15000000000,
    "latest_net_assets": 14500000000
  },
  "daily": [
    {"date": "2026-02-12", "close": 36500, "volume": 1200000, "market_cap": 15000000000, "net_assets": 14500000000}
  ]
}
```

---

### 8. get_stock_prices - 주식 종목 가격 추이 조회

| 항목 | 내용 |
|------|------|
| **클래스** | `GetStockPricesTool` |
| **용도** | 개별 주식(ETF가 아닌)의 OHLCV 가격 데이터 조회 |
| **데이터 소스** | `ETFService.get_stock_prices()` (PostgreSQL) |

**입력**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `stock_code` | string | O | 종목코드 (예: '005930') |
| `period` | string | - | 조회 기간: `'1w'`, `'1m'`(기본값), `'3m'`, `'6m'`, `'1y'` |

**출력**: 요약 통계 + 일별 OHLCV (JSON)
```json
{
  "summary": {
    "stock_code": "005930", "period": "1m", "data_count": 22,
    "start_date": "2026-01-12", "end_date": "2026-02-12",
    "start_close": 70000, "end_close": 72000,
    "high": 73000, "low": 69500, "change_rate": 2.86,
    "avg_volume": 987654
  },
  "daily": [
    {"date": "2026-02-12", "open": 71500, "high": 72200, "low": 71300, "close": 72000, "volume": 1000000, "change_rate": 0.7}
  ]
}
```

---

### 9. compare_etfs - ETF 비교

| 항목 | 내용 |
|------|------|
| **클래스** | `CompareETFsTool` |
| **용도** | 2~3개 ETF를 한번에 비교 (보수율, 태그, 수익률, 보유종목) |
| **데이터 소스** | Apache AGE + PostgreSQL |

**입력**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `etf_codes` | string | O | 쉼표 구분 ETF 코드 (예: `'069500,102110,229200'`), 최소 2개, 최대 3개 |

**출력**: ETF별 비교 정보 배열 (JSON)
```json
[
  {
    "code": "069500", "name": "KODEX 200", "expense_ratio": 0.15,
    "company": "삼성자산운용",
    "tags": ["대형주", "시장대표"],
    "top_holdings": [{"stock_code": "005930", "stock_name": "삼성전자", "weight": 30.5}],
    "return_1m": 3.45,
    "latest_net_assets": 15000000000
  }
]
```

**비교 항목**: 기본정보(보수율, 순자산), 운용사, 태그, 상위 보유종목 5개, 최근 1개월 수익률

---

### 10. graph_query - 그래프 DB 직접 쿼리

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
  - ETF(code, name, expense_ratio, net_assets, close_price, return_1d, return_1w, return_1m, market_cap_change_1w, updated_at)
  - Stock(code, name, is_etf)
  - Company(name)
  - Tag(name)
  - Price(date, open, high, low, close, volume, nav, market_cap, net_assets, trade_value, change_rate)
  - User(user_id)

관계:
  - (ETF)-[:HOLDS {date, weight, shares}]->(Stock)
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

**쿼리 예시**
```cypher
-- 특정 종목을 보유한 ETF (비중 내림차순)
MATCH (e:ETF)-[h:HOLDS]->(s:Stock {code: '005930'})
WITH e, h ORDER BY h.date DESC
WITH e, head(collect(h)) as latest
RETURN {etf_code: e.code, etf_name: e.name, weight: latest.weight}
ORDER BY latest.weight DESC

-- 태그별 ETF 조회
MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '반도체'})
RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio}

-- 운용사별 ETF
MATCH (e:ETF)-[:MANAGED_BY]->(c:Company)
WHERE c.name CONTAINS '삼성'
RETURN {code: e.code, name: e.name, company: c.name}

-- 두 종목을 동시에 보유한 ETF
MATCH (e:ETF)-[h1:HOLDS]->(s1:Stock {code: '005930'})
WITH e, h1 ORDER BY h1.date DESC
WITH e, head(collect(h1)) as lh1
MATCH (e)-[h2:HOLDS]->(s2:Stock {code: '095610'})
WITH e, lh1, h2 ORDER BY h2.date DESC
WITH e, lh1, head(collect(h2)) as lh2
WITH e, lh1, lh2, lh1.weight + lh2.weight AS total_weight
ORDER BY total_weight DESC
LIMIT 5
RETURN {etf_code: e.code, etf_name: e.name, weight_samsung: lh1.weight, weight_tes: lh2.weight, total_weight: total_weight}
```

---

## 도구 요약표

| # | 도구명 | 용도 | 입력 | 데이터 소스 |
|---|--------|------|------|-------------|
| 1 | `etf_search` | ETF 검색 | query | AGE |
| 2 | `stock_search` | 주식 종목 검색 | query | AGE |
| 3 | `list_tags` | 태그/테마 목록 | (없음) | AGE |
| 4 | `get_etf_info` | ETF 종합 정보 | etf_code | AGE + PG |
| 5 | `find_similar_etfs` | 유사 ETF 조회 | etf_code | AGE |
| 6 | `get_holdings_changes` | 보유종목 변화 | etf_code, period? | AGE |
| 7 | `get_etf_prices` | ETF 가격 추이 | etf_code, period? | PG |
| 8 | `get_stock_prices` | 주식 가격 추이 | stock_code, period? | PG |
| 9 | `compare_etfs` | ETF 비교 (2~3개) | etf_codes | AGE + PG |
| 10 | `graph_query` | Cypher 직접 실행 | cypher | AGE |

> **AGE** = Apache AGE 그래프 DB, **PG** = PostgreSQL

---

## 에이전트의 도구 활용 방식

### 아키텍처

```
사용자 질문 (React)
    ↓
FastAPI POST /api/chat/message (또는 /message/stream)
    ↓
ChatService._build_prompt()  ← 유사 해결 절차 예시(pgvector) + 최근 10개 대화 + 현재 질문
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
최종 답변 텍스트 → 사용자에게 응답
```

### CodeAgent(smolagents)에서 바꾼 이유 (2026-09)

이전에는 smolagents `CodeAgent`가 LLM이 생성한 **Python 코드**를 백엔드 프로세스에서 실행했다. 지금은 LLM이 **JSON 인자**로 도구를 호출하고, 코드는 실행하지 않는다.

- **보안**: LLM 생성 코드 실행 제거 (`LocalPythonExecutor`는 샌드박스가 아니었음)
- **타입 검증**: 도구 인자를 JSON 스키마로 검증, 잘못된 인자는 재시도 프롬프트(`RetryPromptPart`)로 LLM에 되돌림 → step의 `error`로 표시
- **병렬 호출**: 독립적인 조회는 한 번의 모델 응답에서 여러 도구를 호출 (같은 질문 기준 CodeAgent 약 13초 → 약 7초)
- 도구는 하나의 DB 세션을 공유하므로 `sequential=True`로 등록해 실제 실행은 순차로 한다
- 정렬·필터링은 LLM이 결과를 보고 직접 하거나, 대상이 많으면 `graph_query`의 ORDER BY/LIMIT을 쓰도록 프롬프트로 안내

### 도구 등록 방식

각 도구는 `ChatTool` 서브클래스로 `name`, `description`, `inputs`(JSON 스키마 properties, `nullable: True`면 선택 인자), `forward()`를 정의한다.
`ChatTool.as_agent_tool()`이 `pydantic_ai.Tool.from_schema(...)`로 변환한다. 선택 인자에 `null`이 오면 `forward()` 기본값을 쓴다.

### 실제 질의 흐름 예시

#### 예시 1: "삼성전자를 가장 많이 보유한 ETF는?"

```
[Step 1] stock_search(query="삼성전자")
         → [{"code": "005930", "name": "삼성전자"}]
[Step 2] graph_query(cypher="MATCH (e:ETF)-[h:HOLDS]->(s:Stock {code: '005930'}) WITH e, h ORDER BY h.date DESC WITH e, head(collect(h)) as latest RETURN {etf_code: e.code, etf_name: e.name, weight: latest.weight} ORDER BY latest.weight DESC LIMIT 5")
         → [{"etf_code": "069500", "etf_name": "KODEX 200", "weight": "30.50%"}, ...]
[답변]   | ETF | 코드 | 비중 | ... 마크다운 표
```

#### 예시 2: "KODEX 200과 TIGER 200 비교해줘"

```
[Step 1] etf_search(query="KODEX 200")     ┐ 한 번의 모델 응답에서
[Step 2] etf_search(query="TIGER 200")     ┘ 병렬 호출
[Step 3] compare_etfs(etf_codes="069500,102110")
[답변]   비교 표
```

### 도구 사용 순서 가이드라인 (시스템 프롬프트)

1. **종목명** 등장 → `stock_search`로 코드 먼저 확인
2. **태그/테마** 등장 → instructions의 태그 목록에서 정확한 태그명 확인
3. **ETF명** 등장 → `etf_search`로 코드 먼저 확인
4. 확인된 코드/태그명으로 → **전용 도구** 실행
5. ETF 비교 → `compare_etfs` 사용
6. 전용 도구로 불가능한 복잡한 관계 → `graph_query`로 Cypher 직접 작성

### 에이전트 설정

```python
model = OpenAIChatModel(
    settings.llm_model,                 # LLM_MODEL (기본 qwen38-27b)
    provider=OpenAIProvider(
        base_url=settings.llm_api_base, # LLM_API_BASE (기본 http://localhost:4000)
        api_key=settings.llm_api_key,   # LLM_API_KEY
    ),
)
agent = Agent(model, instructions=..., tools=[t.as_agent_tool() for t in tools])
agent.run_stream_events(prompt, usage_limits=UsageLimits(request_limit=15))
```

| 설정 | 값 | 설명 |
|------|-----|------|
| LLM | `LLM_MODEL` (기본 qwen38-27b) | LiteLLM 프록시(OpenAI 호환), `pydantic-ai-slim[openai]` |
| 최대 모델 요청 | 15 | 무한 루프 방지 (`UsageLimitExceeded` 시 폴백) |
| 대화 히스토리 | 최근 10개 | 프롬프트에 "참고용" 텍스트로 포함 |
| 관찰 결과 제한 | 2,000자 | UI 성능 보호 |
| few-shot 예제 | 유사 해결 절차 최대 3개 | `code_examples` pgvector 검색 (`EMBEDDING_MODEL`, 768차원, `EMBEDDING_API_KEY`) |

### 해결 절차 예시(few-shot)와 피드백 루프

- `code_examples.code`에는 도구 호출을 `name(key="value")` 형태로 한 줄에 하나씩 저장한다. 목적은 질문 유형별로 맞는 **Cypher 패턴**을 보여 주는 것이다.
- 시드 예시 38개의 원본은 `docker/db/seed/code_examples.py`다. 고유명사는 `<종목명>`, `<ETF명>`, `<운용사>` 자리표시자로 두고, 종목·ETF·운용사는 Cypher에서 이름으로 바로 매칭한다(`stock_search` 호출 불필요). 고친 뒤 `python docker/db/seed/code_examples.py > docker/db/init/03_seed_code_examples.sql`로 SQL을 다시 만든다.
- 프롬프트에는 일반화된 질문(`question_generalized`)과 함께 들어가고, LLM은 자리표시자를 현재 질문의 값으로 바꿔 쓴다.
- 검색할 때도 사용자 질문을 같은 프롬프트로 일반화한 뒤 임베딩한다(`현대차와 기아…` → `특정 종목 2개…`). 일반화는 추론을 끄고 호출해 0.2~0.4초 걸린다.
- 채팅 로그의 `generated_code`는 성공한 도구 호출을 `name(key="value")` 한 줄씩 이어 붙인 것 → 관리자가 승인해 임베딩하면 새 예시가 된다

### 에러 처리 (폴백)

1. 정상 종료 → 최종 텍스트 반환
2. 요청 한도 초과/예외, 도구 결과 있음 → 마지막 도구 결과를 답변으로 사용
3. 모두 실패 → `"죄송합니다. 답변 생성에 실패했습니다. 다시 질문해 주세요."`

### 스트리밍 동작

`POST /api/chat/message/stream` 엔드포인트는 SSE(Server-Sent Events)로 실시간 전달:

```json
// 유사 예시가 있으면 먼저
{"type": "matched_examples", "data": {"examples": [...]}}

// 도구 호출 1건마다 (code = 도구 호출 표기)
{"type": "step", "data": {"step_number": 1, "code": "etf_search(query=\"KODEX\")", "observations": "...", "tool_calls": [...], "error": null}}

// 최종 답변
{"type": "answer", "data": {"answer": "최종 답변 텍스트"}}
```

프론트엔드에서 각 스텝을 접이식 UI로 표시하여 에이전트의 도구 호출 과정을 실시간으로 확인 가능합니다.
