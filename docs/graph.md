# Apache AGE 그래프 데이터베이스

## 개요

ETF-종목 간 관계를 그래프로 모델링하여 유사 ETF 탐색, 종목 역추적, 포트폴리오 변동 감지 등을 수행한다. PostgreSQL 위에서 동작하는 Apache AGE 확장을 사용하며, Cypher 쿼리 언어로 조회한다.

- **확장**: Apache AGE 1.5.0 (PG16)
- **그래프 이름**: `etf_graph`
- **쿼리 언어**: Cypher (SQL 래핑)

## 왜 그래프인가

ETF-종목 관계는 다대다(N:M) 구조이며 관계 기반 질의가 핵심이다:

- "이 ETF가 보유한 종목은?" → 1홉 탐색
- "이 종목을 보유한 ETF는?" → 역방향 1홉
- "두 ETF의 공통 종목은?" → 2홉 패턴 매칭
- "보유종목이 가장 비슷한 ETF는?" → 집계 + 정렬

RDB JOIN으로도 가능하지만, 그래프는 관계 탐색이 직관적이고 다홉 쿼리에서 성능 이점이 있다.

## 그래프 스키마

```
                    ┌──────────┐
                    │ Company  │
                    │  {name}  │
                    └────▲─────┘
                         │ MANAGED_BY
                    ┌────┴─────┐          ┌──────────┐
                    │   ETF    │──HOLDS──▶│  Stock   │
                    │{code,    │          │{code,    │
                    │ name,    │          │ name,    │
                    │ updated} │          │ is_etf}  │
                    └────┬─────┘          └────┬─────┘
                         │ HAS_CHANGE          │ BELONGS_TO
                    ┌────▼─────┐          ┌────▼─────┐
                    │  Change  │          │  Sector  │
                    │{id,      │          │  {name}  │
                    │ stock_code,│         └────┬─────┘
                    │ change_type,│             │ PART_OF
                    │ weight..} │          ┌────▼─────┐
                    └──────────┘          │  Market  │
                                          │  {name}  │
                                          └──────────┘
```

### 노드

| 라벨 | 속성 | 생성 주체 | 설명 |
|------|------|-----------|------|
| ETF | code, name, updated_at | DAG: collect_etf_metadata | ETF 종목 |
| Stock | code, name, is_etf | DAG: collect_holdings | 보유 종목 (ETF인 경우 is_etf=true) |
| Company | name | DAG: collect_etf_metadata | 운용사 (삼성자산운용 등) |
| Sector | name | DAG: collect_holdings | 업종 (반도체, 자동차 등) |
| Market | name | DAG: collect_holdings | 시장 (KOSPI, KOSDAQ) |
| Change | id, stock_code, stock_name, change_type, before_weight, after_weight, weight_change, detected_at | DAG: detect_portfolio_changes | 보유종목 변동 이벤트 |

### 관계(엣지)

| 관계 | 방향 | 속성 | 설명 |
|------|------|------|------|
| MANAGED_BY | ETF → Company | - | 운용사 관계 |
| HOLDS | ETF → Stock | date, weight, shares | 보유종목 (날짜별 스냅샷) |
| BELONGS_TO | Stock → Sector | - | 업종 분류 |
| PART_OF | Sector → Market | - | 시장 구분 |
| HAS_CHANGE | ETF → Change | - | 변동 이력 |

## Cypher 쿼리 실행 방식

### AGE에서 Cypher 실행

Apache AGE는 Cypher를 SQL 함수로 래핑하여 실행한다:

```sql
-- 사전 설정 (세션마다 필요)
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Cypher 실행
SELECT * FROM cypher('etf_graph', $$
    MATCH (e:ETF {code: '069500'})-[:HOLDS]->(s:Stock)
    RETURN s.code, s.name, s.weight
$$) AS (code agtype, name agtype, weight agtype);
```

### 백엔드 실행 (graph_service.py)

SQLAlchemy를 통해 실행한다:

```python
class GraphService:
    def execute_cypher(self, query: str, params: Dict = None) -> List[Dict]:
        full_query = (
            "SET search_path = ag_catalog, \"$user\", public; "
            "LOAD 'age'; "
            f"SELECT * FROM cypher('etf_graph', $$ {query} $$) as (result agtype);"
        )
        result = self.db.execute(text(full_query), params or {})
        return [dict(row._mapping) for row in result]
```

### DAG 실행 (etf_daily_etl.py)

psycopg2 커서로 직접 실행한다. AGE 버그로 인해 `MERGE`와 `SET`을 분리하여 2단계로 수행:

```python
# 1단계: 노드 생성 (MERGE만)
execute_cypher(cur, "MERGE (e:ETF {code: $code}) RETURN e", {'code': ticker})

# 2단계: 속성 설정 (MATCH + SET)
execute_cypher(cur, """
    MATCH (e:ETF {code: $code})
    SET e.name = $name, e.updated_at = $updated_at
    RETURN e
""", {'code': ticker, 'name': name, 'updated_at': now})
```

> **주의:** AGE 1.5.0에서 `MERGE ... SET`을 한 쿼리로 실행하면 오류가 발생하는 버그가 있어, MERGE와 SET을 별도 쿼리로 분리한다.

## 주요 쿼리 패턴

### 1. 유사 ETF 탐색

보유종목 겹침 수(overlap)로 유사도를 측정한다.

```cypher
MATCH (e1:ETF {code: $etf_code})-[:HOLDS]->(s:Stock)<-[:HOLDS]-(e2:ETF)
WHERE e1 <> e2
WITH e2, COUNT(s) as overlap
WHERE overlap >= $min_overlap
RETURN e2.code as etf_code, overlap
ORDER BY overlap DESC
LIMIT 10
```

**API:** `GET /etfs/{code}/similar?min_overlap=5`

### 2. 종목 보유 ETF 조회 (역추적)

특정 종목을 보유한 모든 ETF를 비중 순으로 반환한다.

```cypher
MATCH (e:ETF)-[r:HOLDS]->(s:Stock {code: $stock_code})
RETURN e.code as etf_code, r.weight as weight
ORDER BY r.weight DESC
```

### 3. 두 ETF 공통 보유종목

```cypher
MATCH (e1:ETF {code: $etf_code1})-[:HOLDS]->(s:Stock)<-[:HOLDS]-(e2:ETF {code: $etf_code2})
RETURN s.code as stock_code
```

### 4. 종목 노출도 (ETF 편입 현황)

해당 종목이 몇 개의 ETF에 포함되어 있는지, 평균 비중은 얼마인지 조회한다.

```cypher
MATCH (e:ETF)-[r:HOLDS]->(s:Stock {code: $stock_code})
RETURN COUNT(e) as etf_count, AVG(r.weight) as avg_weight
```

### 5. 포트폴리오 변동 감지 (DAG)

전일 대비 보유종목을 비교하여 Change 노드를 생성한다.

```cypher
-- 오늘 보유종목
MATCH (e:ETF {code: $etf_code})-[h:HOLDS {date: $date}]->(s:Stock)
RETURN s.code as stock_code, s.name as stock_name, h.weight as weight

-- 변동 기록
MATCH (e:ETF {code: $etf_code})
CREATE (c:Change {
    id: $change_id,
    stock_code: $stock_code,
    stock_name: $stock_name,
    change_type: $change_type,
    before_weight: $before_weight,
    after_weight: $after_weight,
    weight_change: $weight_change,
    detected_at: $detected_at
})
CREATE (e)-[:HAS_CHANGE]->(c)
RETURN c
```

### 6. ETF-종목 관계 생성/갱신

```cypher
MERGE (e:ETF {code: $etf_code})
MERGE (s:Stock {code: $stock_code})
MERGE (e)-[r:HOLDS]->(s)
SET r.weight = $weight
RETURN e, r, s
```

## 그래프 vs RDB 역할 분담

| 데이터 | 저장소 | 이유 |
|--------|--------|------|
| ETF-종목 관계, 운용사, 섹터 | AGE (그래프) | 관계 탐색, 패턴 매칭 |
| ETF 메타데이터 (검색용) | RDB (`etfs`) | pg_trgm 텍스트 검색 |
| 시계열 가격 데이터 | RDB (`etf_prices`, `stock_prices`) | 시간순 정렬, 집계 쿼리 |
| 사용자 데이터 | RDB (`users`, `portfolios` 등) | CRUD, 트랜잭션 |
| 벡터 임베딩 | RDB (`etf_embeddings`) | pgvector 유사도 검색 |

## 초기화 및 설정

### Docker 설정

```dockerfile
# docker/db/Dockerfile
# AGE 소스 빌드
RUN git clone --branch release/PG16/1.5.0 https://github.com/apache/age.git /tmp/age \
    && cd /tmp/age && make && make install

# postgresql.conf에 추가
shared_preload_libraries = 'age'
```

### SQL 초기화 (01_extensions.sql)

```sql
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('etf_graph');
SET search_path = public;
```

### 세션별 필수 설정

AGE를 사용하는 모든 DB 세션에서 아래 설정이 필요하다:

```sql
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
```

## 알려진 제약 및 주의사항

1. **MERGE + SET 분리**: AGE 1.5.0에서 `MERGE ... SET`을 한 쿼리로 실행하면 오류 발생. 반드시 2단계로 분리.
2. **파라미터 바인딩**: AGE의 Cypher는 SQL 바인드 변수를 직접 지원하지 않아 문자열 치환으로 처리 (SQL 인젝션 주의, 내부 사용만 가정).
3. **반환 타입**: 모든 Cypher 결과는 `agtype`으로 반환되어 파싱 필요.
4. **날짜별 HOLDS 엣지**: 같은 ETF-Stock 쌍이라도 날짜마다 별도 엣지가 생성되어 시간에 따른 이력이 쌓인다.
5. **변동 감지**: 전일 = 단순 -1일 계산으로, 휴장일은 미고려 (향후 개선 필요).
