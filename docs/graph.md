# Apache AGE 그래프 데이터베이스

## 개요

ETF-종목 간 관계를 그래프로 모델링하여 유사 ETF 탐색, 종목 역추적, 포트폴리오 변동 감지 등을 수행한다. PostgreSQL 위에서 동작하는 Apache AGE 확장을 사용하며, Cypher 쿼리 언어로 조회한다.

- **확장**: Apache AGE 1.8.0 (PostgreSQL 18)
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
┌──────────┐        ┌────┴─────┐          ┌──────────┐
│   User   │─WATCHES│   ETF    │──HOLDS──▶│  Stock   │
│{user_id} │  ─────▶│{code,    │─CURRENT_▶│{code,    │
│          │        │ name,    │  HOLDS   │ name,    │
└──────────┘        │ expense_ratio,│     │ is_etf}  │
                    │ net_assets,│         └────┬─────┘
                    │ close_price,│             │ HAS_PRICE
                    │ return_1d/1w/1m,│    ┌────▼─────┐
                    │ market_cap_│     │  Price   │
                    │  change_1w}│     │{date,    │
                    └─────┬─────┘     │ open/high│
                          │ TAGGED    │ /low/close,│
                          │           │ volume,  │
                          ▼           │ nav, ...}│
                      ┌──────┐        └──────────┘
                      │ Tag  │              ▲
                      │{name}│              │ HAS_PRICE
                      └──────┘              │
                                       (Stock에서도
                                        HAS_PRICE
                                        연결)
```

### 노드

| 라벨 | 속성 | 생성 주체 | 설명 |
|------|------|-----------|------|
| ETF | code, name, expense_ratio, net_assets, close_price, return_1d, return_1w, return_1m, market_cap_change_1w, updated_at, manual_tags, tagged_at | DAG: collect_universe_and_prices, update_etf_returns. manual_tags는 관리자 페이지, tagged_at은 age_tagging | ETF 종목. manual_tags(태그 이름 리스트)가 있으면 age_tagging이 자동 태깅 대신 그 값을 쓴다 (빈 리스트 = 태그 없음 고정). tagged_at(`YYYY-MM-DD`)은 자동 태깅된 날짜로, 없으면 다음 age_tagging의 태깅 대상 |
| Stock | code, name, is_etf | DAG: collect_holdings | 보유 종목 (ETF인 경우 is_etf=true). 주식 이름은 KIS `hts_kor_isnm` |
| Company | name | DAG: collect_universe_and_prices | 운용사 (삼성자산운용 등) |
| Tag | name | DAG: age_tagging | 테마/분류 태그 (반도체, AI 등). ETF별 태그는 관리자 페이지에서 수동 지정 가능 |
| Price | date, open, high, low, close, volume, nav, market_cap, net_assets, trade_value, change_rate | DAG: collect_universe_and_prices, collect_stock_prices_for_dates | 일별 가격 데이터. OHLCV·거래대금은 KIS 일봉, ETF의 nav/net_assets/market_cap은 KIS 현재가 스냅샷이라 수집 시점의 최근 거래일에만 값이 있다 (이전 날짜는 null). change_rate는 Stock만 |
| User | user_id | Backend: graph_service | 사용자 (즐겨찾기용. 역할은 RDB `user_roles`) |

### 관계(엣지)

| 관계 | 방향 | 속성 | 설명 |
|------|------|------|------|
| MANAGED_BY | ETF → Company | - | 운용사 관계 |
| CURRENT_HOLDS | ETF → Stock | date, weight, shares | 현재 보유종목. ETF별로 가장 최근 수집일의 HOLDS를 복사한 것 (ETF당 최대 30개). 현재 구성종목 조회는 모두 이 관계를 쓴다 |
| HOLDS | ETF → Stock | date, weight, shares | 보유종목 이력 (날짜별 스냅샷). KIS API 호출 시점 구성종목을 최근 거래일 날짜로 저장, shares는 평가금액/현재가 추정치. KIS 제약으로 ETF당 비중 상위 30개까지만. 보유종목 변화·비중 이력 비교에만 쓴다 |
| TAGGED | ETF → Tag | - | 테마/분류 태그 |
| HAS_PRICE | ETF/Stock → Price | - | 일별 가격 연결 |
| WATCHES | User → ETF | added_at | 즐겨찾기 |

## Cypher 쿼리 실행 방식

### AGE에서 Cypher 실행

Apache AGE는 Cypher를 SQL 함수로 래핑하여 실행한다:

```sql
-- 사전 설정 (세션마다 필요)
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Cypher 실행
SELECT * FROM cypher('etf_graph', $$
    MATCH (e:ETF {code: '069500'})-[h:CURRENT_HOLDS]->(s:Stock)
    RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight}
    ORDER BY h.weight DESC LIMIT 10
$$) AS (result agtype);
```

### 백엔드 실행 (graph_service.py)

SQLAlchemy를 통해 실행한다. 콜론 이스케이프 + 파라미터 수동 치환:

```python
class GraphService:
    def execute_cypher(self, query: str, params: Dict = None) -> List[Dict]:
        # 1) $param → 실제 값으로 치환
        # 2) 콜론 이스케이프 (:ETF → \:ETF) — SQLAlchemy 바인드 파라미터 충돌 방지
        # 3) RETURN은 반드시 단일 맵으로 감싸기: RETURN {key1: val1, key2: val2}
```

### DAG 실행 (age_utils.py)

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

> **주의:** AGE 1.5.0에서 `MERGE ... SET`을 한 쿼리로 실행하면 오류가 발생하는 버그가 있어 MERGE와 SET을 별도 쿼리로 분리했다. AGE 1.8.0으로 올린 뒤에도 같은 패턴을 유지한다.

## 주요 쿼리 패턴

### 1. ETF 현재 보유종목 (CURRENT_HOLDS)

```cypher
MATCH (e:ETF {code: $etf_code})-[h:CURRENT_HOLDS]->(s:Stock)
RETURN {stock_code: s.code, stock_name: s.name, weight: h.weight}
ORDER BY h.weight DESC LIMIT 10
```

### 2. 유사 ETF 탐색

각 ETF의 현재 보유종목(CURRENT_HOLDS) 비중 겹침(min overlap)으로 유사도를 측정한다.

```cypher
MATCH (e1:ETF {code: $etf_code})-[h1:CURRENT_HOLDS]->(s:Stock)<-[h2:CURRENT_HOLDS]-(e2:ETF)
WHERE e1 <> e2
WITH e2, COUNT(s) as overlap,
     SUM(CASE WHEN h1.weight < h2.weight THEN h1.weight ELSE h2.weight END) as similarity
WHERE overlap >= $min_overlap
RETURN {etf_code: e2.code, name: e2.name, overlap: overlap, similarity: similarity}
ORDER BY similarity DESC LIMIT 5
```

### 3. 종목 보유 ETF 조회 (역추적)

```cypher
MATCH (e:ETF)-[h:CURRENT_HOLDS]->(s:Stock {code: $stock_code})
RETURN {etf_code: e.code, etf_name: e.name, weight: h.weight}
ORDER BY h.weight DESC
```

### 4. 태그별 ETF 조회

```cypher
MATCH (e:ETF)-[:TAGGED]->(t:Tag {name: '반도체'})
RETURN {code: e.code, name: e.name, expense_ratio: e.expense_ratio}
```

### 5. 운용사별 ETF

```cypher
MATCH (e:ETF)-[:MANAGED_BY]->(c:Company)
WHERE c.name CONTAINS '삼성'
RETURN {code: e.code, name: e.name, company: c.name}
```

### 6. ETF 가격 조회 (Price 노드)

```cypher
MATCH (e:ETF {code: $etf_code})-[:HAS_PRICE]->(p:Price)
WHERE p.date >= $start_date AND p.date <= $end_date
RETURN {date: p.date, close: p.close, volume: p.volume,
        market_cap: p.market_cap, net_assets: p.net_assets}
ORDER BY p.date
```

### 7. Stock 가격 조회

```cypher
MATCH (s:Stock {code: $stock_code})-[:HAS_PRICE]->(p:Price)
WHERE p.date >= $start_date AND p.date <= $end_date
RETURN {date: p.date, open: p.open, high: p.high, low: p.low,
        close: p.close, volume: p.volume, change_rate: p.change_rate}
ORDER BY p.date
```

### 8. 사용자 즐겨찾기

```cypher
MATCH (u:User {user_id: $user_id})-[r:WATCHES]->(e:ETF)
RETURN {etf_code: e.code, etf_name: e.name, added_at: r.added_at}
ORDER BY r.added_at DESC
```

## 그래프 vs RDB 역할 분담

| 데이터 | 저장소 | 이유 |
|--------|--------|------|
| ETF-종목 관계, 운용사, 태그 | AGE (그래프) | 관계 탐색, 패턴 매칭 |
| ETF/Stock 가격 시계열 | AGE (Price 노드) | HAS_PRICE 관계로 ETF/Stock에 연결 |
| 사용자 즐겨찾기 | AGE (WATCHES 관계) | 그래프 관계로 직접 조회 |
| 사용자 인증 데이터 | RDB (`users`) | CRUD, 트랜잭션 |
| 포트폴리오 | RDB (`portfolios`, `holdings`) | CRUD, 트랜잭션 |
| 포트폴리오 스냅샷 | RDB (`portfolio_snapshots`) | 시계열 집계 |
| 수집 이력 | RDB (`collection_runs`) | pg_notify 트리거 |

## 초기화 및 설정

### Docker 설정

```dockerfile
# docker/db/Dockerfile (FROM postgres:18-trixie)
# AGE 소스 빌드
RUN git clone --branch release/PG18/1.8.0 --depth 1 https://github.com/apache/age.git /tmp/age \
    && cd /tmp/age && make install

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

1. **MERGE + SET 분리**: AGE 1.5.0에서 `MERGE ... SET`을 한 쿼리로 실행하면 오류가 발생해 2단계로 분리했고, 1.8.0에서도 이 방식을 유지한다.
2. **콜론 이스케이프**: SQLAlchemy `text()` 사용 시 Cypher의 `:ETF`, `[:HOLDS]` 등을 `\:` 로 이스케이프해야 한다.
3. **파라미터 치환**: Cypher `$param`과 SQLAlchemy `:param`이 충돌. 수동으로 `$param` 값을 쿼리 문자열에 삽입하여 처리.
4. **단일 맵 반환**: `execute_cypher`는 `(result agtype)` 컬럼 하나만 반환. 다중 RETURN 값은 `RETURN {key1: val1, key2: val2}` 맵으로 감싸야 한다.
5. **반환 타입**: 모든 Cypher 결과는 `agtype`으로 반환되어 `parse_agtype()` 파싱 필요.
6. **HOLDS vs CURRENT_HOLDS**: HOLDS는 같은 ETF-Stock 쌍이라도 날짜마다 별도 엣지가 생겨 이력이 계속 쌓인다. 현재 구성종목은 HOLDS에서 최신 날짜를 고르지 말고 ETF당 최대 30개인 `CURRENT_HOLDS`를 읽는다. `collect_holdings`가 HOLDS 저장 후 그날 HOLDS가 있는 ETF의 CURRENT_HOLDS를 교체한다 (KIS 조회 실패 ETF는 이전 구성종목 유지, 이미 더 최근 날짜인 ETF는 건너뜀).
7. **HOLDS 이력 범위**: KIS API는 과거 날짜 구성종목을 조회할 수 없어 HOLDS 이력은 수집을 시작한 날부터만 쌓인다 (초기 적재 시 과거 HOLDS 백필 없음). 보유종목 변화는 Change 노드 없이 두 날짜의 HOLDS를 조회 시점에 비교해 계산한다.
