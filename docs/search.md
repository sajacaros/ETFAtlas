# 검색 및 추천 로직

## ETF 검색

### 엔드포인트

`GET /etfs/search?q={query}&limit={limit}`

### 검색 로직 (etf_service.py)

3단계 우선순위로 매칭한다:

```sql
WHERE name ILIKE :like_q        -- 1. 이름 부분 일치
   OR code ILIKE :like_q        -- 2. 코드 부분 일치
   OR LOWER(name) % LOWER(:q)   -- 3. pg_trgm 유사도 (임계값 0.3 이상)
ORDER BY
    (code ILIKE :like_q) DESC,              -- 코드 매칭 최우선
    (name ILIKE :like_q) DESC,              -- 이름 매칭 차선
    similarity(LOWER(name), LOWER(:q)) DESC  -- 유사도 점수순
```

| 단계 | 연산자 | 대소문자 | 설명 |
|------|--------|----------|------|
| 코드 매칭 | `ILIKE` | 무시 | 코드에 검색어 포함 여부 |
| 이름 매칭 | `ILIKE` | 무시 | 이름에 검색어 직접 포함 (예: '로봇') |
| 유사도 | `%` (pg_trgm) | `LOWER()` 적용 | 트라이그램 기반 유사 이름 매칭 |

**인덱스:** `etfs` 테이블에 GIN 인덱스 적용
```sql
CREATE INDEX idx_etfs_name_trgm ON etfs USING GIN (name gin_trgm_ops);
CREATE INDEX idx_etfs_code_trgm ON etfs USING GIN (code gin_trgm_ops);
```

### 검색 예시

| 검색어 | 매칭 방식 | 결과 예 |
|--------|----------|---------|
| `KODEX` | 코드 ILIKE | KODEX 200, KODEX 반도체 등 |
| `로봇` | 이름 ILIKE | KODEX 로봇산업, TIGER 로보틱스AI 등 |
| `반도채` (오타) | pg_trgm 유사도 | 반도체 관련 ETF |

## 종목(Stock) 검색

### 엔드포인트

`GET /stocks/search?q={query}&limit={limit}`

### 검색 로직 (stocks.py)

SQLAlchemy ORM의 `ilike`를 사용한 단순 패턴 매칭:

```python
Stock.code.ilike(f"%{q}%") | Stock.name.ilike(f"%{q}%")
```

pg_trgm은 사용하지 않는다.

## 역추적: 종목 → ETF

### 엔드포인트

`GET /stocks/{code}/etfs`

특정 종목을 보유한 ETF 목록을 비중 순으로 반환한다. `etf_holdings` 테이블 JOIN 조회.

## 유사 ETF 탐색

### 엔드포인트

`GET /etfs/{code}/similar?min_overlap={n}`

### 검색 로직 (graph_service.py)

Apache AGE 그래프에서 Cypher 쿼리로 보유종목 중복도를 계산한다:

```cypher
MATCH (e1:ETF {code: $etf_code})-[:HOLDS]->(s:Stock)<-[:HOLDS]-(e2:ETF)
WHERE e1 <> e2
WITH e2, COUNT(s) as overlap
WHERE overlap >= $min_overlap
RETURN e2.code as etf_code, overlap
ORDER BY overlap DESC
LIMIT 10
```

두 ETF가 공통으로 보유한 종목 수(overlap)가 `min_overlap`(기본 5) 이상인 ETF를 반환.

## AI 추천 (ETFRecommenderAgent)

### 엔드포인트

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/ai/recommend` | POST | 쿼리 기반 ETF 분석 |
| `/ai/signals` | GET | 워치리스트 기반 시그널 |
| `/ai/insights` | GET | 전체 시장 인사이트 |

### 모멘텀 분석 (recommender.py)

최근 5일 종가 기반으로 매매 시그널을 생성한다:

| 조건 | 시그널 | 신뢰도 |
|------|--------|--------|
| 5일간 +5% 이상 | BUY | 0.5 + 변동률/20 (최대 0.8) |
| 5일간 -5% 이상 | SELL | 0.5 + |변동률|/20 (최대 0.8) |
| -5% ~ +5% | HOLD | 0.5 (고정) |

### 인사이트 생성

시그널을 집계하여 요약 정보를 생성한다:
- 상승 모멘텀 ETF 그룹 → 분할 매수 제안
- 하락 주의 ETF 그룹 → 리스크 관리 제안

## 프론트엔드 검색 흐름

### 홈페이지 (HomePage.tsx)

탭 기반 검색 UI:
- **ETF 탭**: `etfsApi.search(query)` → ETF 목록 표시 → 클릭 시 상세 페이지 이동
- **종목 탭**: `stocksApi.search(query)` → 종목 목록 표시 → 클릭 시 해당 종목 보유 ETF 조회

### 종목 추가 다이얼로그 (AddTickerDialog.tsx)

포트폴리오에 종목 추가 시 사용:
- 2글자 이상 입력 시 자동 검색 (최대 5건)
- `CASH` 입력 시 현금으로 즉시 인식
- 검색 결과를 오버레이 드롭다운으로 표시 (레이아웃 유지)
- 선택 시 코드 및 이름 확정 → 비중/수량 입력
