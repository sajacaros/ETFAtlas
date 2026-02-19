# ETF Atlas 챗봇 도구(Tool) 정리

## 개요

ETF Atlas 챗봇은 **smolagents**의 `CodeAgent`를 사용하며, 총 **10개의 커스텀 도구**를 제공합니다.
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
| **보안** | 읽기 전용 (CREATE, MERGE, DELETE, SET, REMOVE, DROP 금지) |

**입력**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| `cypher` | string | O | Cypher 쿼리 (MATCH로 시작, RETURN은 단일 맵으로 감싸기) |

**출력**: 쿼리 결과 (JSON)

**그래프 스키마**
```
노드:
  - ETF(code, name, expense_ratio, updated_at)
  - Stock(code, name, is_etf)
  - Company(name)
  - Sector(name)
  - Market(name)
  - Tag(name)

관계:
  - (ETF)-[:HOLDS {date, weight, shares}]->(Stock)
  - (ETF)-[:MANAGED_BY]->(Company)
  - (Stock)-[:BELONGS_TO]->(Sector)
  - (Stock)-[:PART_OF]->(Market)
  - (ETF)-[:TAGGED]->(Tag)
  - (ETF)-[:HAS_CHANGE {date, change_type}]->(Stock)
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

## CodeAgent의 도구 활용 방식

### 아키텍처

```
사용자 질문 (React)
    ↓
FastAPI POST /api/chat/message (또는 /message/stream)
    ↓
ChatService._build_prompt()  ← 시스템 프롬프트 + 최근 10개 대화 + 현재 질문
    ↓
CodeAgent.run(prompt)  ← ReAct 루프 시작
    ↓
┌─────────────────────────────────────────────────┐
│  ReAct Loop (최대 10 스텝)                        │
│                                                   │
│  1. Thought: LLM이 무엇을 해야 하는지 추론         │
│  2. Action:  LLM이 Python 코드를 생성              │
│  3. Observation: 코드 실행 결과를 관찰              │
│  4. 반복 또는 final_answer() 호출                  │
└─────────────────────────────────────────────────┘
    ↓
final_answer("최종 답변 텍스트")
    ↓
사용자에게 응답 반환
```

### CodeAgent가 특별한 이유

일반적인 에이전트 프레임워크(LangChain 등)에서는 LLM이 **JSON**으로 도구 호출을 정의합니다:
```json
{"tool": "etf_search", "arguments": {"query": "KODEX"}}
```

하지만 CodeAgent는 LLM이 **Python 코드**를 직접 생성하고 실행합니다:
```python
# 에이전트가 생성한 코드 예시
results = etf_search(query="KODEX")
import json
data = json.loads(results)
codes = [item["code"] for item in data]
info = get_etf_info(etf_code=codes[0])
final_answer(f"KODEX 200의 정보: {info}")
```

이 방식의 장점:
- **도구 체이닝**: 변수에 결과를 저장하고 다음 도구의 입력으로 사용
- **데이터 가공**: Python의 리스트/딕셔너리 조작으로 결과를 자유롭게 변환
- **조건 분기**: if/else로 결과에 따라 다른 도구 호출 가능
- **반복 처리**: for 루프로 여러 항목을 순회하며 도구 호출 가능

### 실제 질의 흐름 예시

#### 예시 1: "삼성전자를 가장 많이 보유한 ETF는?"

```
[Step 1] Thought: 먼저 삼성전자의 종목 코드를 확인해야 합니다.
         Code: result = stock_search(query="삼성전자")
         Observation: [{"code": "005930", "name": "삼성전자"}]

[Step 2] Thought: 종목 코드 005930을 보유한 ETF를 그래프에서 조회합니다.
         Code: result = graph_query(cypher="""
             MATCH (e:ETF)-[h:HOLDS]->(s:Stock {code: '005930'})
             WITH e, h ORDER BY h.date DESC
             WITH e, head(collect(h)) as latest
             RETURN {etf_code: e.code, etf_name: e.name, weight: latest.weight}
             ORDER BY latest.weight DESC LIMIT 5
         """)
         Observation: [{"etf_code": "069500", "etf_name": "KODEX 200", "weight": 30.5}, ...]

[Step 3] Thought: 결과를 정리하여 답변합니다.
         Code: final_answer("삼성전자(005930)를 가장 많이 보유한 ETF는 ...\n1. KODEX 200: 30.5%\n...")
```

#### 예시 2: "KODEX 200과 TIGER 200 비교해줘"

```
[Step 1] Thought: 두 ETF의 코드를 먼저 확인합니다.
         Code:
           kodex = etf_search(query="KODEX 200")
           tiger = etf_search(query="TIGER 200")

[Step 2] Thought: 확인된 코드로 비교 도구를 호출합니다.
         Code: result = compare_etfs(etf_codes="069500,102110")
         Observation: [{"code": "069500", ...}, {"code": "102110", ...}]

[Step 3] Thought: 비교 결과를 표 형태로 정리합니다.
         Code: final_answer("## KODEX 200 vs TIGER 200 비교\n| 항목 | KODEX 200 | TIGER 200 |\n...")
```

#### 예시 3: "반도체 관련 ETF 보수율 낮은 순으로"

```
[Step 1] Thought: 먼저 반도체 관련 태그명을 확인합니다.
         Code: tags = list_tags()
         Observation: [{"name": "반도체", "count": 15}, ...]

[Step 2] Thought: 반도체 태그가 있으므로 그래프 쿼리로 조회합니다.
         Code: result = graph_query(cypher="""
             MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '반도체'})
             RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio}
             ORDER BY e.expense_ratio ASC
         """)

[Step 3] Code: final_answer("반도체 ETF (보수율 낮은 순):\n1. ...")
```

### 도구 사용 순서 가이드라인 (시스템 프롬프트)

에이전트에게 주어진 도구 사용 순서 규칙:

1. **종목명** 등장 → `stock_search`로 코드 먼저 확인
2. **태그/테마** 등장 → `list_tags`로 정확한 태그명 확인
3. **ETF명** 등장 → `etf_search`로 코드 먼저 확인
4. 확인된 코드/태그명으로 → **전용 도구** 실행
5. ETF 비교 → `compare_etfs` 사용
6. 전용 도구로 불가능한 복잡한 관계 → `graph_query`로 Cypher 직접 작성

### 에이전트 설정

```python
CodeAgent(
    tools=[...10개 도구...],
    model=LiteLLMModel(model_id="gpt-4.1-mini"),
    additional_authorized_imports=["json"],  # 허용 임포트
    max_steps=10,                            # 최대 추론 스텝
)
```

| 설정 | 값 | 설명 |
|------|-----|------|
| LLM | gpt-4.1-mini | LiteLLM을 통한 OpenAI 모델 |
| 최대 스텝 | 10 | 무한 루프 방지 |
| 허용 임포트 | json | 보안상 최소 임포트만 허용 |
| 대화 히스토리 | 최근 10개 | 토큰 비용 최적화 |
| 관찰 결과 제한 | 2,000자 | UI 성능 보호 |

### 에러 처리 (3단계 폴백)

1. `agent.run()` 성공 → 결과 + 스텝 반환
2. `agent.run()` 실패, 관찰 결과 있음 → 마지막 관찰 결과를 답변으로 사용
3. 모두 실패 → `"죄송합니다. 답변 생성에 실패했습니다. 다시 질문해 주세요."`

### 스트리밍 동작

`POST /api/chat/message/stream` 엔드포인트는 SSE(Server-Sent Events)로 실시간 전달:

```json
// 추론 단계마다
{"type": "step", "data": {"step_number": 1, "code": "...", "observations": "...", "tool_calls": [...], "error": null}}

// 최종 답변
{"type": "answer", "data": {"answer": "최종 답변 텍스트"}}
```

프론트엔드에서 각 스텝을 접이식 UI로 표시하여 에이전트의 사고 과정을 실시간으로 확인 가능합니다.
