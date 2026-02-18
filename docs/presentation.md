# ETF Atlas

> PostgreSQL 하나로 그래프 + 벡터 + 실시간 알림까지
>
> 18일, 79커밋의 사이드 프로젝트

---

## 왜 만들었나

- 평소 ETF 투자하면서 궁금했던 것들:
  - "삼성전자를 가장 많이 담은 ETF는?"
  - "액티브 ETF 운용사들이 요즘 어떤 종목을 사고 팔까?"
- 이 질문들은 본질적으로 **관계 탐색** 문제
- Apache AGE라는 PostgreSQL 그래프 확장이 눈에 띄었고
- smolagents로 AI 에이전트도 붙여보고 싶었다

```
첫 커밋: 2026-02-01   →   최신: 2026-02-18   →   총 79커밋
```

---

## ETF Atlas — 핵심 기능

| 기능 | 설명 |
|------|------|
| **종목 역추적** | "이 종목을 담은 ETF는?" → 비중 순 정렬 |
| **유사 ETF 탐색** | 보유종목 겹침도 기반 유사도 측정 |
| **비중 변화 감지** | 신규 편입 / 완전 제외 / 5%p 이상 변화 추적 |
| **AI 챗봇** | 자연어로 ETF 데이터 질의 |
| **포트폴리오** | 개인 포트폴리오 수익률 대시보드 |
| **실시간 알림** | 보유종목 변화 시 즉시 알림 |

---

## 전체 아키텍처

```
┌──────────────────────────────────────────────────────────┐
│                        ETF Atlas                          │
│                                                           │
│  React + TS         FastAPI            Airflow DAGs       │
│  shadcn/ui   ───▶   Pydantic     ◀─── (매일 08:00 수집)  │
│  Recharts           smolagents         pykrx / KRX API    │
│                                                           │
│              ┌────────────────────────────┐               │
│              │      PostgreSQL 17         │               │
│              │  ┌────────┬───────┬──────┐ │               │
│              │  │ Apache │  RDB  │  pg  │ │               │
│              │  │  AGE   │      │vector│ │               │
│              │  │ 그래프  │ 메타  │임베딩│ │               │
│              │  └────────┴───────┴──────┘ │               │
│              │     + pg_trgm + pg_notify  │               │
│              └────────────────────────────┘               │
└──────────────────────────────────────────────────────────┘
```

핵심: **PostgreSQL 하나에 5개 확장**이 공존

| 확장 | 역할 |
|------|------|
| Apache AGE | ETF-종목 그래프 탐색 |
| pgvector | 챗봇 few-shot 예제 임베딩 |
| pg_trgm | 한글 퍼지 검색 |
| pg_notify | 실시간 이벤트 알림 |
| (기본 RDB) | 사용자, 포트폴리오, 인증 |

---

## Part 1: Apache AGE

---

## Apache AGE란?

- **A**pache **AG**raph **E**xtension
- PostgreSQL 위에서 동작하는 **그래프 DB 확장**
- Cypher 쿼리 언어 지원 (Neo4j와 동일한 문법)
- 별도 DB 서버 없이, PostgreSQL 확장만 설치하면 끝

```sql
-- 설치 & 초기화
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('etf_graph');
```

---

## Neo4j vs Apache AGE

| | Neo4j | Apache AGE |
|--|-------|------------|
| **배포** | 별도 서버 필요 | PostgreSQL 확장 (추가 서버 불필요) |
| **라이선스** | Community (GPL) / Enterprise (유료) | Apache 2.0 (완전 무료) |
| **쿼리 언어** | Cypher | Cypher (호환, 일부 차이) |
| **RDB 연동** | 별도 커넥터 필요 | 같은 PostgreSQL 안에서 SQL + Cypher 혼용 |
| **생태계** | 풍부 (드라이버, 도구, 자료) | 아직 빈약 |
| **안정성** | 성숙 | 일부 버그 존재 (MERGE+SET 등) |

### 왜 AGE를 선택했나?

- 이미 PostgreSQL을 쓰고 있으니 **인프라 추가 비용 = 0**
- 같은 DB 안에서 SQL 테이블과 그래프를 동시에 쿼리 가능
- 사이드 프로젝트에 Neo4j 서버까지 운영하기는 부담

---

## AGE: Cypher를 SQL로 감싸서 실행

Neo4j에서는 Cypher를 직접 실행하지만, AGE는 **SQL 함수로 래핑**

```sql
-- Neo4j
MATCH (e:ETF {code: '069500'})-[:HOLDS]->(s:Stock)
RETURN e.name, s.name, h.weight

-- Apache AGE (SQL 래핑)
SELECT * FROM cypher('etf_graph', $$
    MATCH (e:ETF {code: '069500'})-[h:HOLDS]->(s:Stock)
    RETURN {etf: e.name, stock: s.name, weight: h.weight}
$$) AS (result agtype);
```

### 주의사항: 단일 컬럼 반환

- AGE의 `cypher()` 함수는 `(result agtype)` **단일 컬럼**만 반환
- 여러 값을 리턴하려면 **맵으로 감싸야** 함

```sql
-- 에러 발생
RETURN e.name, s.name

-- 올바른 방법: 맵으로 감싸기
RETURN {etf: e.name, stock: s.name}
```

---

## AGE: ETF Atlas의 그래프 스키마

```
                    ┌──────────┐
                    │ Company  │
                    │  {name}  │
                    └────▲─────┘
                         │ MANAGED_BY
┌──────────┐        ┌────┴─────┐          ┌──────────┐
│   User   │─WATCHES│   ETF    │──HOLDS──▶│  Stock   │
│{user_id, │  ─────▶│{code,    │          │{code,    │
│ role}    │        │ name,    │          │ name}    │
└──────────┘        │ expense_ │          └────┬─────┘
                    │  ratio}  │               │ HAS_PRICE
                    └─┬───┬────┘          ┌────▼─────┐
                      │   │ TAGGED        │  Price   │
                 HAS_ │   ▼               │{date,    │
                CHANGE│ ┌──────┐          │ close,   │
                      │ │ Tag  │          │ volume}  │
                      │ │{name}│          └──────────┘
                 ┌────▼─────┐
                 │  Change  │
                 │{stock_code,│
                 │ change_type,│
                 │ weight..}  │
                 └───────────┘
```

- **7종 노드**: ETF, Stock, Company, Tag, Price, Change, User
- **6종 관계**: HOLDS, MANAGED_BY, TAGGED, HAS_PRICE, HAS_CHANGE, WATCHES

---

## AGE: 관계 탐색이 직관적인 이유

### "삼성전자를 담은 ETF는?" — 종목 역추적

```cypher
MATCH (e:ETF)-[h:HOLDS]->(s:Stock {code: '005930'})
WITH e, h ORDER BY h.date DESC
WITH e, head(collect(h)) as latest
RETURN {etf: e.name, weight: latest.weight}
ORDER BY latest.weight DESC
```

### "KODEX 200과 비슷한 ETF는?" — 유사도 탐색

```cypher
MATCH (e1:ETF {code: '069500'})-[h1:HOLDS]->(s:Stock)<-[h2:HOLDS]-(e2:ETF)
WHERE e1 <> e2
-- 보유종목 겹침 + 비중 유사도 계산
RETURN {etf: e2.name, overlap: COUNT(s), similarity: SUM(...)}
ORDER BY similarity DESC LIMIT 5
```

RDB로도 가능하지만, Cypher가 **읽는 사람 입장에서** 훨씬 직관적

---

## AGE: 날짜별 HOLDS 엣지 패턴

ETF의 보유종목은 매일 변한다. 같은 (ETF→Stock) 관계라도 날짜마다 별도 엣지가 쌓인다.

```
(KODEX 200)──[HOLDS {date:'2/17', weight:25.3}]──▶(삼성전자)
(KODEX 200)──[HOLDS {date:'2/18', weight:24.8}]──▶(삼성전자)
```

최신 보유종목만 가져오려면:

```cypher
MATCH (e:ETF {code: '069500'})-[h:HOLDS]->(s:Stock)
WITH s, h ORDER BY h.date DESC          -- 날짜 역순 정렬
WITH s, head(collect(h)) as latest      -- 첫 번째(=최신)만 추출
RETURN {stock: s.name, weight: latest.weight}
ORDER BY latest.weight DESC
```

이 `ORDER BY + head(collect())` 패턴이 프로젝트 전체에서 반복됨

---

## AGE + SQLAlchemy: 공존의 어려움

FastAPI 백엔드에서는 SQLAlchemy로 DB에 접속한다.
그런데 Cypher와 SQLAlchemy의 문법이 **정면 충돌**한다.

### 문제 1: 콜론 충돌

```python
# SQLAlchemy text()는 :WORD를 바인드 파라미터로 인식
query = "MATCH (e:ETF)-[:HOLDS]->(s:Stock)"
#              ^^^^    ^^^^^^
#         "ETF라는 파라미터가 없습니다!" 에러

# 해결: 모든 콜론을 \: 로 이스케이프
escaped = query.replace(":", "\\:")
```

### 문제 2: 파라미터 표기 충돌

```python
# Cypher: $etf_code    ←  Cypher 파라미터
# SQLAlchemy: :etf_code ←  SQL 바인드 파라미터
# 같은 쿼리에 둘 다 있으면 카오스

# 해결: $param을 실제 값으로 직접 치환한 뒤 실행
```

---

## AGE: execute_cypher 실제 구현

```python
# backend/app/services/graph_service.py

def execute_cypher(self, query: str, params: Dict = None) -> List[Dict]:
    cypher = query

    # 1단계: $param → 실제 값으로 치환
    if params:
        for key, value in params.items():
            if isinstance(value, str):
                escaped = value.replace("'", "\\'")
                cypher = cypher.replace(f"${key}", f"'{escaped}'")
            elif isinstance(value, (int, float)):
                cypher = cypher.replace(f"${key}", str(value))

    # 2단계: SQL 래핑
    cypher_query = f"""
    SELECT * FROM cypher('etf_graph', $$
        {cypher}
    $$) as (result agtype);
    """

    full_query = f"SET search_path = ag_catalog; LOAD 'age'; {cypher_query}"

    # 3단계: 콜론 전부 이스케이프 (SQLAlchemy 충돌 방지)
    escaped_full = full_query.replace(":", "\\:")

    result = self.db.execute(text(escaped_full))
    return [dict(row._mapping) for row in result]
```

Neo4j 드라이버처럼 편하지 않다. 하지만 **같은 PostgreSQL 안에서** 동작하는 것의 이점이 크다.

---

## AGE: MERGE + SET 버그

AGE 1.5.0에서 발견한 버그 — 공식 문서에 없다.

```cypher
-- 이렇게 쓰면 에러 발생!
MERGE (e:ETF {code: '069500'})
SET e.name = 'KODEX 200'
RETURN e
```

```cypher
-- 해결: 2단계로 분리

-- 1단계: 노드 생성만
MERGE (e:ETF {code: '069500'}) RETURN e

-- 2단계: 속성 설정
MATCH (e:ETF {code: '069500'})
SET e.name = 'KODEX 200'
RETURN e
```

Airflow DAG에서 ETF 데이터를 적재할 때 이 패턴을 사용.
AGE 1.7.0으로 업그레이드 후에도 습관적으로 분리해서 쓰고 있다.

---

## Part 2: PostgreSQL NOTIFY / LISTEN

---

## pg_notify란?

PostgreSQL에 **내장된 비동기 메시지 브로커**

```
┌──────────┐    NOTIFY     ┌──────────────┐    LISTEN    ┌──────────┐
│ 발행자   │ ──────────▶  │  PostgreSQL  │ ──────────▶ │ 구독자   │
│ (Airflow)│   채널+페이로드 │  (메시지 큐)  │   이벤트 수신  │ (Backend)│
└──────────┘              └──────────────┘             └──────────┘
```

### 핵심 개념

```sql
-- 구독: 채널에 귀를 기울인다
LISTEN new_collection;

-- 발행: 채널에 메시지를 보낸다
NOTIFY new_collection, '2026-02-18';
```

- **별도 인프라 불필요** — Redis, RabbitMQ, Kafka 없이 PostgreSQL만으로 가능
- **채널 기반** — 이름만 맞추면 여러 구독자가 동시에 수신
- **페이로드 지원** — 문자열 데이터를 함께 전달 가능

---

## pg_notify: 왜 필요했나?

### 문제: "ETF 데이터 수집이 끝나면 프론트에 알려주고 싶다"

**v1: 30초 폴링 (= 사실상 polling)**

```
프론트 ──(30초마다)──▶ 백엔드 ──(DB 조회)──▶ PostgreSQL
                                             "새 데이터 있어?"
```

- 30초마다 "새 알림 있어?" 반복 질의
- 알림 지연 최대 30초
- 불필요한 DB 쿼리 반복

**v2: pg_notify 기반 Push**

```
데이터 수집 완료 → PostgreSQL에 NOTIFY → 백엔드가 LISTEN → SSE로 즉시 전달
```

- 이벤트 발생 시에만 전달 → 불필요한 쿼리 없음
- 지연 거의 0

---

## pg_notify: 발행 측 — Airflow DAG

```python
# airflow/dags/age_utils.py

def record_collection_run(date_str: str) -> bool:
    """수집 완료 기록 + pg_notify 발행"""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 수집 이력 기록 (중복 방지)
        cur.execute(
            "INSERT INTO collection_runs (collected_at) VALUES (%s) "
            "ON CONFLICT (collected_at) DO NOTHING",
            (date_str,)
        )
        inserted = cur.rowcount > 0

        if inserted:
            # 새 수집이면 NOTIFY 발행
            cur.execute("NOTIFY new_collection, %s", (date_str,))
            log.info(f"Collection recorded + notified: {date_str}")
        else:
            # 이미 수집된 날짜면 알림 생략 (중복 방지)
            log.info(f"Already exists: {date_str} — skip notify")

        conn.commit()
        return inserted
    finally:
        cur.close()
        conn.close()
```

`ON CONFLICT DO NOTHING` + `rowcount` 체크로 **중복 알림 방지**

---

## pg_notify: 수신 측 — SSE 스트림

```python
# backend/app/routers/notifications.py

@router.get("/stream")
async def notification_stream(token: str = QueryParam(...)):
    """SSE 스트림 — pg_notify LISTEN으로 새 수집 즉시 감지"""

    async def event_generator():
        conn = psycopg2.connect(settings.database_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute("LISTEN new_collection;")   # 채널 구독

        try:
            loop = asyncio.get_event_loop()
            while True:
                # select로 알림 대기 (5초 타임아웃)
                ready = await loop.run_in_executor(
                    None, lambda: select.select([conn], [], [], 5.0)
                )
                if ready[0]:
                    conn.poll()
                    while conn.notifies:
                        notify = conn.notifies.pop(0)
                        data = json.dumps({
                            "type": "new_changes",
                            "collected_at": notify.payload,  # 날짜 문자열
                        })
                        yield f"data: {data}\n\n"   # SSE 형식
        finally:
            cur.close()
            conn.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

---

## pg_notify: 전체 흐름

```
┌──────────┐         ┌──────────────┐         ┌──────────┐         ┌──────────┐
│ Airflow  │         │ PostgreSQL   │         │ FastAPI  │         │ React    │
│  DAG     │         │              │         │ Backend  │         │ Frontend │
└────┬─────┘         └──────┬───────┘         └────┬─────┘         └────┬─────┘
     │                      │                      │                    │
     │  INSERT + NOTIFY     │                      │                    │
     │─────────────────────▶│                      │                    │
     │  "new_collection"    │                      │                    │
     │  payload: "2026-02-18"                      │                    │
     │                      │   LISTEN 이벤트 수신  │                    │
     │                      │─────────────────────▶│                    │
     │                      │                      │  SSE: data: {...}  │
     │                      │                      │───────────────────▶│
     │                      │                      │                    │
     │                      │                      │                    │  알림 뱃지
     │                      │                      │                    │  업데이트
```

추가로 **디스코드 웹훅**도 연동 — 관리자는 디스코드에서도 알림 수신

---

## Part 3: pgvector

---

## pgvector란?

PostgreSQL에서 **벡터 유사도 검색**을 지원하는 확장

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 핵심 개념

```
"반도체 ETF 추천해줘"
        │
        ▼ (임베딩 모델)
  [0.12, -0.34, 0.56, ...]   ← 1536차원 벡터
        │
        ▼ (코사인 유사도 검색)
  DB에 저장된 벡터들과 비교 → 가장 유사한 결과 반환
```

| 연산자 | 의미 |
|--------|------|
| `<=>` | 코사인 거리 (cosine distance) |
| `<->` | L2 거리 (유클리드) |
| `<#>` | 내적 (inner product) |

---

## pgvector: 왜 필요했나?

### 문제: AI 챗봇이 AGE용 Cypher를 잘 못 쓴다

LLM은 **Neo4j 기준** Cypher를 생성한다. 하지만 AGE는 미묘하게 다르다:

```cypher
-- LLM이 생성한 Cypher (Neo4j 스타일)
MATCH (e:ETF)-[:HOLDS]->(s:Stock)
RETURN e.name, s.name, h.weight

-- AGE에서 실제로 돌아가는 Cypher
MATCH (e:ETF)-[h:HOLDS]->(s:Stock)
WITH s, h ORDER BY h.date DESC
WITH s, head(collect(h)) as latest
RETURN {etf: e.name, stock: s.name, weight: latest.weight}
```

### 해결: Few-Shot RAG

- 100개의 "질문 → 올바른 AGE Cypher" 예제를 준비
- 각 질문을 벡터로 임베딩해서 pgvector에 저장
- 사용자 질문이 들어오면 유사한 예제를 찾아서 프롬프트에 주입
- LLM이 예제를 보고 AGE에 맞는 Cypher를 생성

---

## pgvector: 테이블 설계

```sql
-- docker/db/init/02_cypher_examples.sql

CREATE TABLE IF NOT EXISTS cypher_examples (
    id          SERIAL PRIMARY KEY,
    question    TEXT NOT NULL,           -- "반도체 ETF 알려줘"
    cypher      TEXT NOT NULL,           -- 올바른 AGE Cypher
    description TEXT,                    -- 설명
    embedding   vector(1536) NOT NULL,   -- 질문의 임베딩 벡터
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- IVFFlat 인덱스: 대량 벡터에서 빠른 유사도 검색
CREATE INDEX IF NOT EXISTS idx_cypher_examples_embedding
    ON cypher_examples
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
```

- `vector(1536)`: OpenAI `text-embedding-3-small` 모델의 차원 수
- `ivfflat`: 근사 최근접 이웃 검색 인덱스 (정확도↔속도 트레이드오프)
- `vector_cosine_ops`: 코사인 유사도 기준

---

## pgvector: 임베딩 생성과 시드 적재

```python
# backend/app/services/embedding_service.py

EMBEDDING_MODEL = "text-embedding-3-small"

def get_embedding(self, text_input: str) -> List[float]:
    """OpenAI API로 텍스트 → 1536차원 벡터 변환"""
    resp = self._client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text_input,
    )
    return resp.data[0].embedding   # [0.12, -0.34, 0.56, ...]
```

```python
def seed_if_empty(self):
    """서버 시작 시 cypher_examples가 비어있으면 시드 데이터 적재"""
    count = self.db.execute(text("SELECT COUNT(*) FROM cypher_examples")).scalar()
    if count > 0:
        return

    examples = json.loads(EXAMPLES_JSON.read_text())  # 100개 예제
    questions = [ex["question"] for ex in examples]
    embeddings = self.get_embeddings_batch(questions)  # 일괄 임베딩

    for ex, emb in zip(examples, embeddings):
        emb_str = "[" + ",".join(str(v) for v in emb) + "]"
        self.db.execute(text(
            "INSERT INTO cypher_examples (question, cypher, description, embedding) "
            "VALUES (:question, :cypher, :description, :emb\\:\\:vector)"
        ), {"question": ex["question"], "cypher": ex["cypher"],
            "description": ex.get("description", ""), "emb": emb_str})
```

---

## pgvector: 유사도 검색

```python
# backend/app/services/embedding_service.py

def find_similar_examples(self, question: str, top_k: int = 3) -> List[Dict]:
    """사용자 질문과 가장 유사한 Cypher 예제 top-k 검색"""

    emb = self.get_embedding(question)       # 질문 → 벡터
    emb_str = "[" + ",".join(str(v) for v in emb) + "]"

    query = text(
        "SELECT question, cypher, description, "
        "embedding <=> :emb\\:\\:vector AS distance "   # 코사인 거리
        "FROM cypher_examples "
        "ORDER BY embedding <=> :emb\\:\\:vector "      # 가까운 순
        "LIMIT :top_k"
    )

    rows = self.db.execute(query, {"emb": emb_str, "top_k": top_k})
    return [
        {"question": r.question, "cypher": r.cypher, "description": r.description}
        for r in rows
    ]
```

`<=>` 연산자: 코사인 거리 (0에 가까울수록 유사)

여기서도 `\\:\\:vector` — SQLAlchemy의 콜론 충돌을 피하기 위한 이스케이프

---

## pgvector: 챗봇 프롬프트에 주입

```python
# backend/app/services/chat_service.py

def _build_prompt(self, message: str, history: List[Dict]) -> str:
    parts = [SYSTEM_PROMPT]

    # pgvector 유사도 검색으로 관련 예제 top-3 찾기
    examples = self._embedding_service.find_similar_examples(message, top_k=3)

    if examples:
        parts.append("## 참고 Cypher 쿼리 예시")
        for ex in examples:
            parts.append(f"Q: {ex['question']}\n```cypher\n{ex['cypher']}\n```")

    parts.append(f"## 현재 질문:\n{message}")
    return "\n".join(parts)
```

### 결과: 프롬프트에 이런 식으로 주입됨

```
## 참고 Cypher 쿼리 예시
Q: 삼성전자를 담은 ETF는?
​```cypher
MATCH (e:ETF)-[h:HOLDS]->(s:Stock {code: '005930'})
WITH e, h ORDER BY h.date DESC
WITH e, head(collect(h)) as latest
RETURN {etf: e.name, weight: latest.weight}
​```

## 현재 질문:
반도체 관련 ETF 중에서 삼성전자 비중이 가장 높은 건?
```

LLM이 **AGE에 맞는 패턴**을 참고하여 정확한 Cypher를 생성하게 됨

---

## Part 4: smolagents

---

## smolagents란?

Hugging Face의 **경량 AI 에이전트 프레임워크**

- LLM에게 **도구(Tool)**를 주고 스스로 판단하여 호출하게 하는 구조
- LangChain보다 가볍고 단순

### ETF Atlas에서의 도구 구성

```
[smolagents 에이전트]
    │
    ├── get_etf_info        → AGE: ETF 상세 정보 조회
    ├── get_etf_prices      → AGE: Price 노드에서 가격 조회
    ├── search_etf          → RDB: pg_trgm 퍼지 검색
    ├── get_etf_holdings    → AGE: 보유종목 비중 조회
    ├── get_similar_etfs    → AGE: 유사 ETF 탐색
    └── search_stock        → AGE: 종목 역추적
```

### 흐름

```
사용자: "보수율 낮은 반도체 ETF 추천해줘"
    ↓
에이전트 판단: search_etf("반도체") 호출 → 결과 분석 → 보수율 정렬
    ↓
답변: "KODEX 반도체 (0.09%), TIGER 반도체 (0.19%) ..."
```

---

## Part 5: 하이브리드 아키텍처

---

## PostgreSQL 하나로 다 하기

### 처음에는 AGE에 올인했다

```
ETF 목록       → AGE
보유종목       → AGE
가격 데이터     → AGE
검색           → AGE  ← 느림...
사용자 데이터   → AGE  ← CRUD 불편...
```

### 현실: 각 확장의 강점을 살리는 역할 분담

| 데이터 | 저장소 | 이유 |
|--------|--------|------|
| ETF-종목 관계 | AGE (그래프) | 관계 탐색, 패턴 매칭 |
| ETF 검색 | RDB + pg_trgm | 텍스트 퍼지 검색 |
| 사용자/포트폴리오 | RDB | CRUD, 트랜잭션 |
| 챗봇 예제 | pgvector | 벡터 유사도 검색 |
| 실시간 알림 | pg_notify | 이벤트 기반 푸시 |
| 가격 캐시 | RDB (ticker_prices) | 단순 조회 + 10분 갱신 |

**모든 것이 하나의 PostgreSQL 안에서 동작**
→ 인프라 관리 비용 최소화

---

## 데이터 파이프라인

```
┌─────────────────────────────────────────────────────────────┐
│  Airflow DAGs                                                │
│                                                               │
│  sync_universe_age (매일 08:00)                               │
│  ├── ETF 유니버스 수집 (pykrx)                                │
│  ├── 보유종목 수집 → AGE HOLDS 엣지                           │
│  ├── 가격 수집 → AGE Price 노드                               │
│  ├── 태깅 (반도체, AI, 2차전지, ...)                          │
│  ├── 비중 변화 감지 → AGE Change 노드                         │
│  ├── collection_runs 기록 + pg_notify ───▶ 실시간 알림        │
│  └── 디스코드 웹훅 발송 (관리자용)                            │
│                                                               │
│  realtime_prices_rdb (장중 10분 주기)                         │
│  └── 현재가 수집 → RDB ticker_prices                          │
│                                                               │
│  sync_metadata_rdb (매일)                                     │
│  └── ETF 메타데이터 → RDB etfs 테이블                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 주요 화면

### 홈: ETF 탐색

- 태그별 분류 (반도체, AI, 2차전지, ...)
- pg_trgm 기반 한글 퍼지 검색
- 즐겨찾기 (AGE WATCHES 관계)

### ETF 상세

- 보유종목 비중 차트
- 유사 ETF (보유종목 겹침도 기반)
- 가격 추이 차트 (Recharts)

### 포트폴리오 대시보드

- 개별/전체 합산 수익률 추이
- 드래그&드롭 순서 변경 (@dnd-kit)

### 비중 변화 알림

- 신규 편입 / 완전 제외 / 5%p 이상 변화
- SSE 실시간 알림 + 디스코드 웹훅

### AI 챗봇

- 자연어로 ETF 정보 질의
- few-shot RAG로 정확한 Cypher 생성

---

## 개발 타임라인 (git log 기반)

```
2/1  ██░░░░░░░░░░░░░░░░  v1 뼈대 (FastAPI + React + AGE + Airflow)
2/2  ██░░░░░░░░░░░░░░░░  첫 번째 버그 수정 (KRX API 응답 포맷)
2/3  ████░░░░░░░░░░░░░░  KRX API 모듈화, AGE 함정 발견 시작
2/4  ████░░░░░░░░░░░░░░  Graph Viewer UI 구현
2/5  █████░░░░░░░░░░░░░  운용사/섹터 탭 추가
2/6  ██████░░░░░░░░░░░░  포트폴리오 비중 관리
2/9  ████████░░░░░░░░░░  RDB 도입 (pg_trgm 검색) ← 하이브리드 전환점
2/10 █████████░░░░░░░░░  대시보드, 포트폴리오 스냅샷
2/11 ████████████░░░░░░  smolagents 챗봇 도입, 유사 ETF
2/12 █████████████░░░░░  PG 16→17, AGE 1.5→1.7 업그레이드
2/13 ██████████████░░░░  실시간 현재가, PriceService 리팩토링
2/14 ███████████████░░░  드래그&드롭, watchlist→AGE 전환
2/15 ████████████████░░  태그 시스템 개선
2/17 ██████████████████  알림 시스템 (pg_notify + SSE + Discord)
2/18 ██████████████████  pgvector few-shot RAG 도입
```

---

## 기술 스택

| 영역 | 기술 | 선택 이유 |
|------|------|-----------|
| Frontend | React + TypeScript + shadcn/ui | 빠른 UI 구성, 컴포넌트 재사용 |
| Charts | Recharts | React 네이티브 차트 라이브러리 |
| DnD | @dnd-kit | 접근성 좋은 드래그&드롭 |
| Backend | FastAPI + Pydantic | 타입 안전한 비동기 API |
| Auth | Google OAuth + JWT | 간편 로그인 |
| Graph DB | Apache AGE 1.7.0 | PG 확장, 추가 서버 불필요 |
| Search | pg_trgm | 한글 퍼지 검색 |
| Vector | pgvector 0.8.0 | 임베딩 유사도 검색 |
| Realtime | pg_notify + SSE | PG 내장 메시지 브로커 |
| AI Agent | smolagents | 경량 도구 기반 에이전트 |
| Embedding | OpenAI text-embedding-3-small | 1536차원 벡터 |
| Pipeline | Airflow + pykrx | 일배치 + 실시간 수집 |
| Infra | Docker Compose | 원커맨드 배포 |

---

## 숫자로 보는 프로젝트

| 지표 | 값 |
|------|-----|
| 개발 기간 | 18일 (2/1 ~ 2/18) |
| 총 커밋 | 79개 |
| 실제 개발일 | 15일 |
| fix 커밋 | 8개 |
| refactor 커밋 | 8개 |
| PostgreSQL 확장 | 5개 (AGE, pgvector, pg_trgm, pg_notify, RDB) |
| Few-shot 예제 | 100개 |
| 그래프 노드 종류 | 7종 |
| 그래프 관계 종류 | 6종 |
| DAG 이름 변경 횟수 | 3회 |
| PG 업그레이드 | 16 → 17 |
| AGE 업그레이드 | 1.5.0 → 1.7.0 |

---

## 배운 것들

1. **Apache AGE는 가능성이 크지만 아직 거칠다**
   - Neo4j 대비 생태계가 빈약하고, 문서화되지 않은 버그가 있다
   - 하지만 PostgreSQL과 같은 프로세스에서 돈다는 것은 강력한 이점

2. **"하나의 DB로 다 하겠다"는 환상이지만, PostgreSQL은 꽤 가깝다**
   - 그래프 + 벡터 + 전문검색 + 메시지 브로커가 모두 확장으로 존재
   - 각각의 전문 도구보다는 못하지만, 인프라 단순성의 가치가 크다

3. **LLM에게 도메인을 가르치려면 few-shot이 가장 효과적**
   - 시스템 프롬프트만으로는 AGE 특유의 문법을 학습시키기 어렵다
   - 유사 질문의 실제 쿼리 예제를 보여주면 정확도가 크게 올라간다

4. **pg_notify는 과소평가된 기능**
   - Redis Pub/Sub나 별도 메시지 큐 없이 실시간 이벤트 처리 가능
   - 소규모 서비스에서는 이것만으로 충분하다

---

## 앞으로의 계획

- 사내 배포 후 피드백 수집
- 카카오/네이버 소셜 로그인 추가
- ETF 추천 알고리즘 고도화
- 해외 ETF 확장 (미국 시장)
- AI 챗봇 Cypher 정확도 지속 개선

---

## Q&A

> 궁금한 점 있으시면 편하게 질문해 주세요.
