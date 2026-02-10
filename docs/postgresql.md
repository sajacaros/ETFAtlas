# PostgreSQL 확장 기능

## 사용 중인 확장

| 확장 | 버전 | 용도 |
|------|------|------|
| Apache AGE | 1.5.0 | 그래프 데이터베이스 (ETF-종목 관계) |
| pgvector | 0.7.0 | 벡터 임베딩 저장 및 유사도 검색 |
| pg_trgm | 내장 | 트라이그램 기반 퍼지 텍스트 검색 |

## 1. Apache AGE (Graph Extension)

### 설치

PostgreSQL 16 이미지에서 소스 빌드로 설치한다 (`docker/db/Dockerfile`):

```dockerfile
RUN apt-get install -y build-essential libreadline-dev zlib1g-dev flex bison \
    postgresql-server-dev-16
RUN git clone --branch release/PG16/1.5.0 https://github.com/apache/age.git /tmp/age \
    && cd /tmp/age && make && make install
```

**필수 설정:** `shared_preload_libraries = 'age'` (postgresql.conf)

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
| ETF | code, name, updated_at | ETF 종목 |
| Stock | code, name, is_etf | 보유 종목 |
| Company | name | 운용사 |
| Sector | name | 업종/섹터 |
| Market | name | KOSPI/KOSDAQ |
| Change | id, stock_code, stock_name, change_type, before_weight, after_weight, weight_change, detected_at | 보유종목 변동 |

**관계(엣지):**

| 관계 | 속성 | 설명 |
|------|------|------|
| `(ETF)-[:MANAGED_BY]->(Company)` | - | 운용사 |
| `(ETF)-[:HOLDS]->(Stock)` | date, weight, shares | 보유종목 |
| `(Stock)-[:BELONGS_TO]->(Sector)` | - | 업종 분류 |
| `(Sector)-[:PART_OF]->(Market)` | - | 시장 구분 |
| `(ETF)-[:HAS_CHANGE]->(Change)` | - | 변동 이력 |

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
RUN git clone --branch v0.7.0 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector && make && make install
```

### 초기화

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 테이블

```sql
CREATE TABLE etf_embeddings (
    etf_code VARCHAR(20) PRIMARY KEY,
    embedding vector(1536),    -- 1536차원 벡터 (OpenAI 임베딩 호환)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Python 연동

```python
from pgvector.sqlalchemy import Vector

class ETFEmbedding(Base):
    embedding = Column(Vector(1536))
```

### 현재 상태

테이블과 모델이 정의되어 있으나, 임베딩 생성 및 시맨틱 검색 기능은 아직 미구현.

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
    (code ILIKE :like_q) DESC,
    (name ILIKE :like_q) DESC,
    similarity(LOWER(name), LOWER(:q)) DESC
```

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
SELECT DISTINCT ON (etf_code) etf_code, close_price
FROM etf_prices
WHERE etf_code = ANY(:tickers)
  AND close_price IS NOT NULL
ORDER BY etf_code, date DESC
```

`DISTINCT ON`은 PostgreSQL 전용으로, 지정한 컬럼 기준 첫 번째 행만 반환한다. 서브쿼리 없이 그룹별 최신 행을 가져올 수 있다.

### ANY() 배열 연산자

```sql
WHERE etf_code = ANY(:tickers)
```

배열 파라미터와 비교하여 IN절과 동일하게 동작하지만, 바인드 변수로 배열을 직접 전달할 수 있다.

### UPSERT (INSERT ... ON CONFLICT)

DAG에서 데이터 적재 시 중복 처리:

```sql
INSERT INTO etf_prices (etf_code, date, close_price, ...)
VALUES (...)
ON CONFLICT (etf_code, date)
DO UPDATE SET close_price = EXCLUDED.close_price, ...
```

## 5. DB 연결 설정

```python
# database.py
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,    # 커넥션 유효성 사전 검증
    pool_size=10,          # 기본 풀 크기
    max_overflow=20        # 추가 허용 커넥션
)
```

## 전체 테이블 목록

| 테이블 | 용도 | 특이사항 |
|--------|------|----------|
| users | 사용자 계정 | Google OAuth |
| etfs | ETF 마스터 | pg_trgm GIN 인덱스 |
| stocks | 종목 마스터 | ORM으로 생성 |
| etf_holdings | ETF 보유종목 | ORM으로 생성 |
| etf_prices | ETF 시세 | 복합 PK (code, date) |
| stock_prices | 종목 시세 | 복합 PK (code, date) |
| etf_embeddings | 벡터 임베딩 | pgvector 1536차원 |
| etf_universe | ETF 유니버스 | DAG 필터링 결과 |
| watchlists | 관심 목록 | CASCADE 삭제 |
| watchlist_items | 관심 종목 | UNIQUE(watchlist, etf) |
| portfolios | 포트폴리오 | 계산 기준 설정 |
| target_allocations | 목표 비중 | UNIQUE(portfolio, ticker) |
| holdings | 보유 수량 | UNIQUE(portfolio, ticker) |
