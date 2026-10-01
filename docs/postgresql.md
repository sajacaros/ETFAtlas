# PostgreSQL 확장 기능

## 사용 중인 확장

| 확장 | 버전 | 용도 |
|------|------|------|
| Apache AGE | 1.8.0 | 그래프 데이터베이스 (ETF-종목 관계) |
| pgvector | 0.8.6 | 벡터 임베딩 저장 및 유사도 검색 |
| pg_trgm | 내장 | 트라이그램 기반 퍼지 텍스트 검색 |

## 1. Apache AGE (Graph Extension)

### 설치

PostgreSQL 18 이미지(`postgres:18-trixie`)에서 소스 빌드로 설치한다 (`docker/db/Dockerfile`):

```dockerfile
RUN apt-get install -y build-essential git libreadline-dev zlib1g-dev flex bison \
    postgresql-server-dev-18
RUN git clone --branch release/PG18/1.8.0 --depth 1 https://github.com/apache/age.git /tmp/age \
    && cd /tmp/age && make install
```

**필수 설정:** `shared_preload_libraries = 'age'` (postgresql.conf)

### 초기화 스크립트 (`docker/db/init/`)

빈 볼륨으로 처음 기동할 때 순서대로 실행된다 (별도 마이그레이션 스크립트 없음 — 스키마 변경 시 DB 재생성).

| 파일 | 내용 |
|------|------|
| `00_airflow_db.sql` | Airflow 메타데이터 DB `airflow` 생성 (앱 DB `etf_atlas`와 분리) |
| `01_extensions.sql` | `age`, `vector`, `pg_trgm` 확장 + `etf_graph` 생성 |
| `02_schema.sql` | RDB 테이블/인덱스, 기본 역할(admin, member) |
| `03_seed_code_examples.sql` | 챗봇 코드 예제 시드 (임베딩은 `embed_code_examples` DAG에서 생성) |

### 초기화 (01_extensions.sql)

```sql
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('etf_graph');  -- 그래프 생성
```

### 그래프 스키마 (`etf_graph`)

**노드:**

| 라벨 | 속성 | 설명 |
|------|------|------|
| ETF | code, name, expense_ratio, net_assets, close_price, return_1d/1w/1m, market_cap_change_1w | ETF 종목 |
| Stock | code, name, is_etf | 보유 종목 (이름은 KIS `hts_kor_isnm`) |
| Company | name | 운용사 |
| Tag | name | 테마/분류 태그 |
| Price | date, open, high, low, close, volume, ... | 일별 가격 |
| User | user_id | 사용자 (즐겨찾기용) |

**관계(엣지):**

| 관계 | 속성 | 설명 |
|------|------|------|
| `(ETF)-[:MANAGED_BY]->(Company)` | - | 운용사 |
| `(ETF)-[:HOLDS]->(Stock)` | date, weight, shares | 보유종목 (KIS 수집일 기준 스냅샷, shares는 추정치, 비중 상위 30개까지) |
| `(ETF)-[:TAGGED]->(Tag)` | - | 태그 |
| `(ETF\|Stock)-[:HAS_PRICE]->(Price)` | - | 가격 |
| `(User)-[:WATCHES]->(ETF)` | added_at | 즐겨찾기 |

상세는 [graph.md](graph.md) 참고.

### 사용 예 (graph_service.py)

```python
# Cypher 쿼리를 SQL 함수로 실행
self.db.execute(text("""
    SELECT * FROM ag_catalog.cypher('etf_graph', $$
        MATCH (e1:ETF {code: $etf_code})-[:HOLDS]->(s:Stock)<-[:HOLDS]-(e2:ETF)
        WHERE e1 <> e2
        WITH e2, COUNT(s) as overlap
        WHERE overlap >= $min_overlap
        RETURN e2.code, overlap
        ORDER BY overlap DESC
    $$) AS (code agtype, overlap agtype)
"""))
```

### 활용 기능

- 유사 ETF 탐색 (보유종목 겹침 수)
- 종목 → ETF 역추적
- 두 ETF 간 공통 보유종목 조회
- 종목의 ETF 노출도 (보유 ETF 수, 평균 비중)

## 2. pgvector (Vector Extension)

### 설치

```dockerfile
RUN git clone --branch v0.8.6 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector && make && make install
```

### 초기화

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 테이블

챗봇의 few-shot 코드 예제 저장소(`code_examples`)에서 사용한다.

```sql
CREATE TABLE code_examples (
    id SERIAL PRIMARY KEY,
    question TEXT NOT NULL,
    question_generalized TEXT,
    code TEXT NOT NULL,
    description TEXT,
    embedding vector(768),     -- embedding-gemma-300m (768차원)
    status VARCHAR(20) DEFAULT 'active',
    ...
);

CREATE INDEX idx_code_examples_embedding
    ON code_examples USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);
```

### Python 연동

`pgvector` 파이썬 패키지는 쓰지 않는다. ORM 모델에서는 `embedding`을 `Text`로 선언하고, 쓰기/검색은 raw SQL로 처리한다.

```python
# embedding_service.py — 코사인 거리 검색
SELECT id, question, code, embedding <=> :emb::vector AS distance
FROM code_examples
WHERE status = 'embedded' AND embedding <=> :emb::vector < :max_dist
ORDER BY embedding <=> :emb::vector
LIMIT :top_k
```

임베딩은 LiteLLM 프록시(`EMBEDDING_API_BASE`, `EMBEDDING_API_KEY`)의 `EMBEDDING_MODEL`(기본 `embedding-gemma-300m`)로 생성한다.

## 3. pg_trgm (Trigram Extension)

### 개념

문자열을 3글자 단위(trigram)로 분리하여 유사도를 계산하는 확장.

```
"KODEX" → {" K", "KO", "OD", "DE", "EX", "X "}
```

두 문자열 간 trigram 겹침 비율이 유사도 점수(0.0~1.0)가 된다.

### 초기화

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### 인덱스

현재 `02_schema.sql`에는 `etfs`의 트라이그램 GIN 인덱스가 없다 (ETF 수가 적어 순차 스캔). 필요 시 아래처럼 추가할 수 있다.

```sql
CREATE INDEX idx_etfs_name_trgm ON etfs USING GIN (name gin_trgm_ops);
CREATE INDEX idx_etfs_code_trgm ON etfs USING GIN (code gin_trgm_ops);
```

GIN(Generalized Inverted Index)은 트라이그램을 역인덱스로 저장하여 빠른 유사도 검색을 가능하게 한다.

### 주요 연산자/함수

| 연산자/함수 | 설명 | 예시 |
|------------|------|------|
| `%` | 유사도가 임계값(기본 0.3) 이상이면 TRUE | `name % '반도체'` |
| `similarity(a, b)` | 두 문자열의 유사도 점수 반환 (0.0~1.0) | `similarity(name, '반도체')` |
| `ILIKE` | 대소문자 무시 패턴 매칭 (PostgreSQL 전용) | `code ILIKE '%kodex%'` |

### 사용 위치 (etf_service.py)

```sql
WHERE name ILIKE :like_q           -- 이름 부분 문자열 매칭
   OR code ILIKE :like_q           -- 코드 부분 문자열 매칭
   OR LOWER(name) % LOWER(:q)     -- 트라이그램 유사도 매칭
ORDER BY
    CASE ... END,                  -- 코드/이름 정확·접두·부분 일치 우선순위 (0~7)
    e.name                         -- 동순위는 이름순
```

정렬 상세는 [search.md](search.md) 참고.

### ILIKE 참고

`ILIKE`는 **PostgreSQL 전용** 연산자이다. 다른 DB에서 대소문자 무시 검색:

| DB | 방법 |
|---|---|
| MySQL | `LIKE` 자체가 대소문자 무시 (collation 의존) |
| SQLite | `LIKE`가 ASCII 범위에서 대소문자 무시 |
| Oracle / SQL Server | `LOWER(col) LIKE LOWER(...)` |

## 4. PostgreSQL 전용 기능

### DISTINCT ON

`price_service.py`에서 종목별 최신 가격을 효율적으로 조회:

```sql
SELECT DISTINCT ON (ticker) ticker, price
FROM ticker_prices
WHERE ticker = ANY(:tickers)
ORDER BY ticker, date DESC
```

`DISTINCT ON`은 PostgreSQL 전용으로, 지정한 컬럼 기준 첫 번째 행만 반환한다. 서브쿼리 없이 그룹별 최신 행을 가져올 수 있다.

### ANY() 배열 연산자

```sql
WHERE ticker = ANY(:tickers)
```

배열 파라미터와 비교하여 IN절과 동일하게 동작하지만, 바인드 변수로 배열을 직접 전달할 수 있다.

### UPSERT (INSERT ... ON CONFLICT)

DAG에서 데이터 적재 시 중복 처리:

```sql
INSERT INTO ticker_prices (ticker, date, price, updated_at)
VALUES (...)
ON CONFLICT (ticker, date)
DO UPDATE SET price = EXCLUDED.price, updated_at = NOW()
```

## 5. DB 연결 설정

```python
# database.py
# psycopg2 드라이버 명시 (SQLAlchemy 2.1+ 기본은 psycopg3)
engine = create_engine(
    settings.database_url.replace("postgresql://", "postgresql+psycopg2://", 1),
    pool_pre_ping=True,    # 커넥션 유효성 사전 검증
    pool_size=10,          # 기본 풀 크기
    max_overflow=20        # 추가 허용 커넥션
)
```

## 전체 테이블 목록

앱 DB `etf_atlas` 기준 (`docker/db/init/02_schema.sql`). ETF/종목/보유종목/가격 이력은 RDB가 아니라 AGE 그래프에 있다.

| 테이블 | 용도 | 특이사항 |
|--------|------|----------|
| users | 사용자 계정 | username UNIQUE + bcrypt password_hash |
| roles | 역할 | admin, member |
| user_roles | 사용자-역할 매핑 | UNIQUE(user_id, role_id) |
| etfs | ETF 코드/이름 | pg_trgm 퍼지 검색, `rdb_sync_metadata` DAG이 적재 |
| portfolios | 포트폴리오 | 공유 토큰, snapshot_enabled |
| target_allocations | 목표 비중 | UNIQUE(portfolio_id, ticker) |
| holdings | 보유 수량 | UNIQUE(portfolio_id, ticker), quantity/avg_price 암호화 |
| portfolio_snapshots | 일별 평가금액 | UNIQUE(portfolio_id, date), 금액 컬럼 암호화 |
| ticker_prices | 티커별 일별 가격 캐시 | 복합 PK (ticker, date) |
| collection_runs | 수집 완료 기록 | collected_at UNIQUE, 알림 트리거 |
| kis_tokens | KIS 접근 토큰 캐시 | PK app_key_hash |
| chat_logs | 챗봇 대화 로그 | 피드백/검수 상태 |
| code_examples | 챗봇 코드 예제 | pgvector 768차원, ivfflat |
