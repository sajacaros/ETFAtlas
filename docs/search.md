# 검색 로직

## ETF 검색

ETF 검색은 두 가지다.

| 엔드포인트 | 대상 | 쓰는 곳 |
|---|---|---|
| `GET /api/etfs/search/universe?q=` | AGE 유니버스 ETF (이름·코드 포함 여부, 순자산 큰 순, 페이지) | 홈 화면 검색 |
| `GET /api/etfs/search?q=` | RDB `etfs` 전체 상장 ETF | 포트폴리오 종목 추가 다이얼로그 |

### 전체 ETF 검색 (etf_service.py)

이름/코드 부분 일치(공백 제거 포함), 띄어 쓴 단어가 순서와 상관없이 모두 포함("time 나스닥" → "TIME 미국나스닥100액티브"), 또는 pg_trgm 유사도로 후보를 찾고, 매칭 종류별 우선순위로 정렬한다 (요약):

```sql
WHERE e.name ILIKE :like_q OR e.code ILIKE :like_q
   OR REPLACE(e.name, ' ', '') ILIKE :like_stripped   -- 공백 무시 부분 일치
   OR LOWER(e.name) % LOWER(:q)                      -- pg_trgm 유사도 (임계값 0.3 이상)
ORDER BY
    CASE
        WHEN e.code ILIKE :q THEN 0                              -- 코드 정확 일치
        WHEN e.code ILIKE :like_q THEN 1                         -- 코드 부분 일치
        WHEN e.name ILIKE :q THEN 2                              -- 이름 정확 일치
        WHEN e.name ILIKE :starts_q THEN 3                       -- 이름 접두 일치
        WHEN REPLACE(e.name, ' ', '') ILIKE :starts_stripped THEN 4
        WHEN e.name ILIKE :like_q THEN 5                         -- 이름 부분 일치
        WHEN REPLACE(e.name, ' ', '') ILIKE :like_stripped THEN 6
        WHEN <모든 단어 포함> THEN 7
        ELSE 8                                                   -- 유사도 매칭만
    END,
    similarity(LOWER(e.name), LOWER(:q)) DESC,
    e.name
LIMIT :lim
```

> `etfs` 테이블은 code/name만 가진다 (순자산 등은 AGE ETF 노드).

| 단계 | 연산자 | 대소문자 | 설명 |
|------|--------|----------|------|
| 코드 매칭 | `ILIKE` | 무시 | 코드에 검색어 포함 여부 |
| 이름 매칭 | `ILIKE` | 무시 | 이름에 검색어 직접 포함 (예: '로봇') |
| 유사도 | `%` (pg_trgm) | `LOWER()` 적용 | 트라이그램 기반 유사 이름 매칭 |

**인덱스:** 현재 `docker/db/init/02_schema.sql`에는 GIN 인덱스가 없다 (ETF 수가 적어 순차 스캔). 필요 시 아래처럼 추가한다.
```sql
CREATE INDEX idx_etfs_name_trgm ON etfs USING GIN (name gin_trgm_ops);
CREATE INDEX idx_etfs_code_trgm ON etfs USING GIN (code gin_trgm_ops);
```

### 검색 예시

| 검색어 | 매칭 방식 | 결과 예 |
|--------|----------|---------|
| `KODEX` | 이름 접두 일치 | KODEX 200, KODEX 반도체 등 |
| `로봇` | 이름 부분 일치 | KODEX 로봇산업, TIGER 로보틱스AI 등 |
| `반도채` (오타) | pg_trgm 유사도 | 반도체 관련 ETF |

## 유사 ETF 탐색

`GET /api/etfs/{code}/similar?min_overlap={n}` (graph_service.py `find_similar_etfs`)

공통 보유종목(`CURRENT_HOLDS`)마다 두 ETF 비중 중 작은 값을 더해 유사도를 구하고, 기준 ETF의 비중 합으로 나눠 %로 정규화한다.
상위 30개만 저장해 비중 합이 100%가 아니기 때문이다. 공통 종목 수가 `min_overlap`(기본 5) 이상인 ETF 중 상위 5개.

```cypher
MATCH (e1:ETF {code: $etf_code})-[h1:CURRENT_HOLDS]->(s:Stock)<-[h2:CURRENT_HOLDS]-(e2:ETF)
WHERE e1 <> e2
WITH e2, COUNT(s) as overlap,
     SUM(CASE WHEN h1.weight < h2.weight THEN h1.weight ELSE h2.weight END) as similarity
WHERE overlap >= $min_overlap
RETURN {etf_code: e2.code, name: e2.name, overlap: overlap, similarity: similarity}
ORDER BY similarity DESC
LIMIT 5
```

## 프론트엔드 검색 흐름

### 홈페이지 (HomePage.tsx)

- 검색어가 있으면 유니버스 검색, 없으면 선택한 태그로 목록을 띄운다 (즐겨찾기 · 정렬 태그 · 액티브/패시브 · 테마 태그)
- 항목을 펼치면 구성종목을, 클릭하면 상세 페이지로 이동

### 종목 추가 다이얼로그 (AddTickerDialog.tsx)

포트폴리오에 종목 추가 시 사용:
- 2글자 이상 입력 시 전체 ETF 검색 (최대 50건)
- `CASH` 입력 시 현금으로 즉시 인식
- 선택 시 코드 및 이름 확정 → 비중/수량 입력
