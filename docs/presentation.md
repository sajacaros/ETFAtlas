# ETF Atlas — Apache AGE & smolagents 기술 소개와 적용기

## 발표 정보
- **대상**: 개발자
- **시간**: 1시간+
- **슬라이드**: 27장

---

## Part 1. 오프닝 (3장)

### 슬라이드 1: 타이틀
- **제목**: ETF Atlas — Apache AGE & smolagents 기술 소개와 적용기
- **부제**: PostgreSQL 그래프 확장과 경량 AI 에이전트로 ETF 정보 서비스 만들기
- **발표자**: (이름)
- **날짜**: 2026년 2월

### 슬라이드 2: 문제 제기 — ETF 데이터의 복잡한 관계
- **질문**: "ETF 500개, 보유종목 수천 개 — 이 관계를 어떻게 탐색할까?"
- **관계형 DB의 한계**
  - "삼성전자를 가장 많이 보유한 ETF는?" → JOIN 3개 + GROUP BY + ORDER BY
  - "KODEX 200과 비슷한 ETF는?" → 자기 조인 + 서브쿼리 + HAVING
  - 쿼리가 복잡해질수록 성능과 가독성 모두 악화
- **자연어 질의의 어려움**
  - 사용자: "반도체 ETF 중 보수율 낮은 것" → 어떤 도구로?
  - LLM이 SQL을 생성? 그래프 쿼리를 생성? 도구를 호출?
- **키 비주얼**: 복잡한 SQL JOIN 쿼리 vs 간결한 Cypher MATCH 패턴 비교

### 슬라이드 3: 왜 이 기술들을 선택했나
- **배경**: 개인 관심사(ETF) + 기술 실험
- **Apache AGE 선택 이유**
  - ETF 데이터 = 관계 중심 → 그래프 DB 적합
  - Neo4j: AGPL 라이선스, 정책 변경 리스크
  - AGE: PostgreSQL 확장, Apache 2.0 라이선스
- **smolagents 선택 이유**
  - LangChain: 추상화 과다, 디버깅 어려움
  - smolagents: 최소 추상화, 코드 생성 기반
- **키 비주얼**: Neo4j 로고 → ? → AGE 로고, LangChain 로고 → ? → smolagents 로고

---

## Part 2. Apache AGE 기술 소개 (5장)

### 슬라이드 4: Apache AGE란?
- **정의**: PostgreSQL에 그래프 DB 기능을 추가하는 확장 (A Graph Extension)
- **핵심 특징 3가지**
  - PostgreSQL 위에서 동작 (별도 DB 불필요)
  - Cypher 쿼리 지원 (Neo4j 호환)
  - SQL + Cypher 혼용 가능
- **라이선스**: Apache 2.0 (상용 자유)
- **현재 상태**: Apache 인큐베이팅 프로젝트, PostgreSQL 17 지원
- **키 비주얼**: PostgreSQL 아이콘 + "graph extension" 다이어그램

### 슬라이드 5: Neo4j vs Apache AGE 비교
- **비교 테이블**

| 항목 | Neo4j | Apache AGE |
|------|-------|------------|
| 타입 | 전용 그래프 DB | PostgreSQL 확장 |
| 라이선스 | AGPL / 상용 | Apache 2.0 |
| 인프라 | 별도 서버 필요 | 기존 PostgreSQL 활용 |
| Cypher 지원 | 완전 지원 | 주요 기능 지원 (일부 미지원) |
| SQL 통합 | 불가 | 동일 DB에서 SQL + Cypher |
| 에코시스템 | 풍부 (드라이버, 시각화) | 제한적 (성장 중) |
| 대규모 순회 | 최적화됨 | PostgreSQL 엔진 의존 |

- **결론**: PostgreSQL 기반이면 AGE, 그래프 중심이면 Neo4j
- **키 비주얼**: 양쪽 비교 다이어그램 (인프라 구성도)

### 슬라이드 6: AGE 동작 방식 — Cypher in SQL
- **실행 방식**: SQL 안에서 `cypher()` 함수 호출
- **코드 예시**
  ```sql
  SELECT * FROM cypher('etf_graph', $$
      MATCH (e:ETF)-[h:HOLDS]->(s:Stock)
      WHERE e.code = '069500'
      RETURN {stock: s.name, weight: h.weight}
  $$) as (result agtype);
  ```
- **주의사항**
  - 그래프 이름 지정 필수 (`'etf_graph'`)
  - 결과 타입: `agtype` (AGE 전용)
  - 다중 RETURN → 맵으로 감싸야 함 `{key: value}`
- **키 비주얼**: SQL 쿼리 안에 Cypher가 내장된 코드 블록 하이라이트

### 슬라이드 7: 그래프 데이터 모델링 — ETF 도메인
- **노드 (6종)**

| 노드 | 주요 속성 | 설명 |
|------|----------|------|
| ETF | code, name, net_assets, expense_ratio | ETF 종목 |
| Stock | code, name | 보유 종목 |
| Price | date, open/high/low/close, volume | 일별 가격 |
| Company | name | 운용사 |
| Tag | name | 테마 태그 |
| User | user_id, role | 사용자 |

- **관계 (5종)**

| 관계 | 방향 | 속성 | 설명 |
|------|------|------|------|
| HOLDS | ETF → Stock | weight, date, shares | 보유종목 비중 |
| HAS_PRICE | ETF/Stock → Price | - | 가격 이력 |
| MANAGED_BY | ETF → Company | - | 운용사 |
| TAGGED | ETF → Tag | - | 테마 분류 |
| WATCHES | User → ETF | added_at | 관심 종목 |

- **키 비주얼**: 그래프 다이어그램 (노드와 엣지 시각화)

### 슬라이드 8: Cypher 쿼리 실전 예시
- **예시 1: 유사 ETF 찾기** (보유종목 겹침)
  ```cypher
  MATCH (e1:ETF {code: '069500'})-[:HOLDS]->(s:Stock)
  MATCH (e2:ETF)-[:HOLDS]->(s) WHERE e1 <> e2
  WITH e2, COUNT(s) as overlap
  RETURN {code: e2.code, name: e2.name, overlap: overlap}
  ORDER BY overlap DESC LIMIT 5
  ```
- **예시 2: 특정 종목을 보유한 ETF 찾기**
  ```cypher
  MATCH (e:ETF)-[h:HOLDS]->(s:Stock {code: '005930'})
  RETURN {etf: e.name, weight: h.weight}
  ORDER BY h.weight DESC
  ```
- **관계형 SQL 대비 장점**: JOIN + GROUP BY + HAVING → MATCH 패턴 하나로 표현
- **키 비주얼**: Cypher 코드 + 결과 테이블 + 그래프 시각화

---

## Part 3. smolagents 기술 소개 (5장)

### 슬라이드 9: smolagents란?
- **정의**: Hugging Face의 경량 AI 에이전트 프레임워크 (2024년 말 공개)
- **핵심 철학**: 최소한의 추상화, 개발자가 제어
- **CodeAgent**: JSON 도구 호출 대신 Python 코드를 직접 생성
  - 변수 저장, 조건 분기, 반복 가능
  - 도구 간 데이터 전달이 자연스러움
- **구성 요소**: Model + Tools + Agent (이게 전부)
- **키 비주얼**: smolagents 아키텍처 다이어그램 (Model → CodeAgent → Tools)

### 슬라이드 10: LangChain vs smolagents
- **비교 테이블**

| 항목 | LangChain | smolagents |
|------|-----------|------------|
| 철학 | 모든 것을 추상화 | 필요한 것만 제공 |
| 도구 호출 | JSON 기반 | Python 코드 생성 |
| 에코시스템 | 수백 개 통합 | 핵심만 제공 |
| 학습 곡선 | 높음 (추상화 레이어 多) | 낮음 (코드 직접 읽기 가능) |
| 디버깅 | 어려움 (콜스택 깊음) | 쉬움 (코드가 곧 로그) |
| 고급 기능 | 내장 (메모리, RAG 등) | 직접 구현 |
| 코드 규모 | 대형 | 소형 (소스 읽기 가능) |

- **결론**: 도구 호출 중심 에이전트 → smolagents, 복잡한 RAG 체인 → LangChain
- **키 비주얼**: 추상화 레이어 비교 다이어그램

### 슬라이드 11: Tool 정의 방식
- **구조**: Tool 클래스 상속, 5가지 속성 정의
  ```python
  class ETFSearchTool(Tool):
      name = "etf_search"
      description = "ETF를 코드나 이름으로 검색합니다"
      inputs = {
          "query": {"type": "string", "description": "검색어"},
          "limit": {"type": "integer", "description": "결과 수"}
      }
      output_type = "string"

      def forward(self, query: str, limit: int = 10) -> str:
          results = self.graph.search_etfs(query, limit)
          return json.dumps(results, ensure_ascii=False)
  ```
- **핵심 포인트**
  - description이 도구 선택을 결정 → 프롬프트 튜닝이 중요 (시행착오 파트에서 상세)
  - forward()에서 비즈니스 로직 실행
  - 반환값은 문자열 (JSON 직렬화)
- **키 비주얼**: smolagents Tool 코드 블록 + description 작성 팁

### 슬라이드 12: CodeAgent 동작 흐름
- **흐름도** (사용자 질문 → 최종 답변)
  1. 사용자 질문 입력
  2. 에이전트가 Python 코드 생성
  3. 코드 실행 (도구 호출)
  4. 실행 결과 관찰 (Observation)
  5. 추가 코드 생성 또는 최종 답변
  6. (반복, 최대 10스텝)
- **예시**: "삼성전자를 가장 많이 보유한 ETF는?"
  ```python
  # Step 1: 에이전트가 생성한 코드
  result = stock_search("삼성전자")
  stock_code = json.loads(result)[0]["code"]

  # Step 2: 그래프 쿼리
  etfs = graph_query("MATCH (e:ETF)-[h:HOLDS]->(s:Stock {code: '" + stock_code + "'}) ...")
  ```
- **JSON 호출 대비 장점**: 변수 재활용, 조건 분기, 에러 자동 수정
- **키 비주얼**: 단계별 흐름도 (코드 → 실행 → 관찰 → 반복)

### 슬라이드 13: 스트리밍 & 실행 과정 가시화
- **smolagents 스트리밍 API**
  - `ActionStep` / `FinalAnswerStep` 이벤트
  - SSE(Server-Sent Events)로 프론트엔드 전송
- **프론트엔드 UI**
  - 실시간 스텝 표시 (어떤 도구를 호출했는지)
  - 접을 수 있는 코드/결과 패널
  - 최종 답변은 마크다운 렌더링
- **효과**: AI 동작의 투명성 → 사용자 신뢰도 향상
- **키 비주얼**: 챗봇 UI 스크린샷 (스텝 펼침 상태)

---

## Part 4. ETF Atlas 프로젝트 적용 사례 (9장)

### 슬라이드 14: 프로젝트 개요
- **ETF Atlas**: 한국 ETF 정보 수집 / 분석 / AI 질의 서비스
- **주요 기능 4가지**
  1. ETF 탐색: 테마별 분류, 검색, 유사 ETF 찾기
  2. 포트폴리오 관리: 매수 기록, 목표 비중, 수익률 추적
  3. 워치리스트: 관심 ETF, 보유종목 변동 알림
  4. AI 챗봇: 자연어 ETF 데이터 질의
- **키 비주얼**: 4가지 기능 아이콘 + 한 줄 설명

### 슬라이드 15: 전체 아키텍처
- **Docker 4-서비스 구성**

| 서비스 | 기술 | 포트 | 역할 |
|--------|------|------|------|
| DB | PostgreSQL 17 + AGE + pgvector | 9602 | 관계형 + 그래프 + 벡터 |
| Backend | FastAPI (Python) | 9601 | REST API |
| Frontend | React + TS + Vite | 9600 | 웹 UI |
| Airflow | Apache Airflow 2.10 | 9603 | 데이터 파이프라인 |

- **핵심 포인트**: 하나의 PostgreSQL에 RDB + 그래프 + 벡터 공존
- **키 비주얼**: 4개 컨테이너 아키텍처 다이어그램 + 네트워크 연결

### 슬라이드 16: 데이터 파이프라인 & 데이터 플로우
- **DAG 3개**

| DAG | 스케줄 | 역할 |
|-----|--------|------|
| 일별 동기화 | 평일 08:00 | KRX → ETF/Price/Holdings 수집 |
| 주간 태깅 | 일요일 02:00 | 전체 ETF 테마 태그 재할당 |
| 백필 | 수동 | 과거 데이터 일괄 적재 |

- **전체 데이터 흐름**
  ```
  KRX API / pykrx → Airflow DAGs → PostgreSQL (AGE + RDB + pgvector)
      → FastAPI (GraphService / PriceService / ChatService) → React Frontend
  ```
- **데이터 소스**: KRX Open API (ETF 거래), pykrx (보유종목 PDF, 주식 가격), yfinance (폴백), OpenAI (태깅, 챗봇, 임베딩)
- **태깅 3단계 전략**: 규칙 기반 → 키워드 매칭 → LLM 분류 (GPT-4.1-mini)
- **키 비주얼**: Airflow DAG 스크린샷 + 좌→우 데이터 플로우 다이어그램

### 슬라이드 17: 기능 데모 — ETF 탐색
- **태그 페이지**: 반도체, AI, 2차전지 등 테마별 ETF 목록
  - Cypher: `(ETF)-[:TAGGED]->(Tag)` 관계 조회
- **ETF 상세**: 기본 정보 + 보유종목 TOP 10 + 가격 차트
  - Cypher: `(ETF)-[:HOLDS]->(Stock)` + `(ETF)-[:HAS_PRICE]->(Price)`
- **유사 ETF**: 보유종목 비중 유사도 기반 추천
  - Cypher: 공통 Stock의 MIN(비중) 합산 → 비중 합 대비 백분율로 정규화
- **키 비주얼**: 각 페이지 UI 스크린샷 (3분할)

### 슬라이드 18: 기능 데모 — 보유종목 변동 감지
- **워치리스트**: 관심 ETF 등록 (User → WATCHES → ETF)
- **변동 감지**: 기간별(1일/1주/1월) 보유종목 비중 변화 추적
  - 신규 편입 / 제외 / 비중 증가 / 비중 감소
- **알림**: 3%p 이상 변동 시 Discord 알림
  - 대상: `(User {role:'admin'})-[:WATCHES]->(ETF)` 관계 기반
- **예시**: KODEX 반도체 — SK하이닉스 비중 15% → 18% (+3%p)
- **키 비주얼**: 변동 감지 UI 스크린샷 + Discord 알림 메시지

### 슬라이드 19: 기능 데모 — AI 챗봇 구조
- **ChatService 구성**
  ```
  LiteLLMModel (GPT-4.1-mini)
      ↓
  CodeAgent (max_steps=10)
      ↓
  10개 커스텀 Tool → GraphService → AGE 그래프
  ```
- **도구 카테고리**

| 카테고리 | 도구 | 설명 |
|----------|------|------|
| 검색 | etf_search, stock_search, list_tags | 종목/테마 검색 |
| 정보 | get_etf_info, get_etf_prices, get_stock_prices, get_holdings_changes | 상세 데이터 |
| 분석 | find_similar_etfs, compare_etfs, graph_query | 비교/분석/직접 쿼리 |

- **핵심**: 모든 도구 → GraphService → AGE (두 기술의 교차점)
- **키 비주얼**: 도구 구조 다이어그램

### 슬라이드 20: 기능 데모 — AI 챗봇 Few-shot 학습
- **문제**: 에이전트가 정확한 Cypher 쿼리를 생성하지 못함
- **해결**: Few-shot 예시 주입
  - 119개 Cypher 쿼리 예시 사전 준비
  - pgvector에 임베딩 저장 (text-embedding-3-small)
  - 질문 유사도 기반 3개 예시 검색 → 프롬프트 주입
- **재미있는 조합**: 같은 PostgreSQL에서 pgvector(벡터 검색) + AGE(그래프 쿼리) 동시 사용
- **키 비주얼**: 질문 → 임베딩 → 유사 예시 → 프롬프트 주입 흐름도

### 슬라이드 21: 기능 데모 — AI 챗봇 실행 과정
- **데모 시나리오**: "반도체 ETF 중 보수율이 가장 낮은 것은?"
  1. `list_tags()` → 태그 목록 확인
  2. `graph_query()` → 반도체 태그 ETF 중 보수율 정렬
  3. 결과 마크다운 테이블 포맷팅
  4. 최종 답변 반환
- **실시간 스트리밍**: SSE로 각 단계 전송
- **UI**: 접었다 펼 수 있는 실행 과정 패널
- **키 비주얼**: 챗봇 대화 UI 스크린샷 (스텝 펼침 상태)

### 슬라이드 22: 기능 데모 — 포트폴리오 대시보드
- **포트폴리오 관리**: ETF/주식 매수 기록, 목표 비중 설정
- **가치 계산**: 현재가 × 수량 → 포트폴리오 가치
- **대시보드**: 일별 가치 변화 Recharts 차트
  - portfolio_snapshots 테이블 (RDB)
  - Airflow에서 가격 수집 후 자동 스냅샷
- **설계 포인트**: CRUD = RDB, 관계 탐색 = 그래프 (혼합 설계)
- **키 비주얼**: 포트폴리오 대시보드 UI 스크린샷

---

## Part 5. 시행착오 (3장)

### 슬라이드 23: smolagents — 프롬프트 엔지니어링 삽질
- **도구 description의 중요성**
  - Before: "ETF를 검색합니다" → 에이전트가 도구 대신 직접 Cypher 작성
  - After: "코드나 이름으로 ETF를 검색합니다. 특정 ETF를 찾을 때 사용하세요." → 정확도 향상
- **시스템 프롬프트 규칙**
  - "태그 이름 사용 전 반드시 list_tags 호출"
  - "정렬 방향 명시" 등 구체적 행동 지침 필요
- **Few-shot 예시의 효과**
  - 예시 없이: 부정확한 Cypher 생성 빈번
  - 유사 예시 3개 주입: 쿼리 정확도 대폭 향상
- **교훈**: smolagents의 코드는 간단하지만, 프롬프트 튜닝에 시간이 많이 듦
- **키 비주얼**: Before/After 프롬프트 비교 + 정확도 변화

### 슬라이드 24: 가격 데이터 이전 — RDB에서 AGE로
- **처음 설계**: `etf_prices`, `stock_prices` RDB 테이블에 가격 저장
  - 장점: 익숙한 SQL 쿼리, ORM 지원
  - 문제: 챗봇이 가격 데이터를 조회할 때 SQL과 Cypher를 오가야 함
- **전환 동기**
  - 챗봇 도구가 GraphService를 통해 AGE만 조회하는 구조
  - 가격도 그래프에 있으면 `(ETF)-[:HAS_PRICE]->(Price)` 한 번에 탐색 가능
  - "삼성전자 최근 가격 + 보유 ETF" 같은 복합 질의가 단일 Cypher로 해결
- **전환 과정**
  - Price 노드 설계: `{date, open, high, low, close, volume}`
  - `(ETF/Stock)-[:HAS_PRICE]->(Price)` 관계 추가
  - PriceService 캐시 전략: cache(60s) → AGE 당일종가 → yfinance → AGE 최신종가(폴백)
  - RDB `etf_prices`/`stock_prices` 테이블 제거
- **교훈**: 데이터 저장소는 "어디서 주로 조회하느냐"에 맞춰야 함. 챗봇이 주 소비자라면 챗봇이 접근하는 저장소에 데이터를 두는 것이 자연스러움
- **키 비주얼**: Before (RDB + AGE 분리) → After (AGE 통합) 아키텍처 비교

### 슬라이드 25: 그래프 vs 관계형 — 어디에 뭘 넣을까
- **처음 접근**: 모든 데이터를 그래프에 → 비효율 발견
- **최종 판단**

| 그래프에 적합 | 관계형에 적합 |
|--------------|--------------|
| 관계 탐색 (ETF-종목, 유사 ETF) | 단순 CRUD (사용자, 포트폴리오) |
| 시계열 + 관계 (날짜별 비중 변화) | 집계/정렬 (스냅샷, 가치 계산) |
| 다대다 관계 (워치리스트) | 트랜잭션 (인증, 주문) |

- **AGE의 장점**: 한 DB에서 두 패러다임 혼용 가능
- **결론**: "전부 그래프" 또는 "전부 관계형"이 아닌 혼합 설계가 현실적
- **키 비주얼**: 데이터별 저장소 분류 다이어그램

---

## Part 6. 회고 & 마무리 (2장)

### 슬라이드 26: 기술 선택 회고
- **Apache AGE 총평**

| 좋았던 점 | 아쉬운 점 |
|----------|----------|
| PostgreSQL 하나로 RDB + 그래프 + 벡터 | Cypher 지원 불완전 (Neo4j 대비) |
| 인프라 복잡도 감소 | ORM 통합 가이드 부재 |
| Apache 2.0 라이선스 | 커뮤니티 규모 작음 |

- **smolagents 총평**

| 좋았던 점 | 아쉬운 점 |
|----------|----------|
| 도구 정의 직관적 | 문서 부족 |
| CodeAgent의 유연한 코드 생성 | 고급 기능 직접 구현 필요 |
| 소스 코드가 읽을 만한 규모 | 프롬프트 의존도 높음 |

- **추천 상황**
  - AGE: 이미 PostgreSQL 사용 + 그래프 쿼리가 부분 워크로드
  - smolagents: 도구 호출 중심 에이전트 빠른 프로토타이핑

### 슬라이드 27: Q&A
- **감사합니다. 질문 받겠습니다.**
- **추가 토픽**
  - AGE 성능 (인덱싱, 대규모 데이터)
  - smolagents vs CrewAI 등 다른 경량 프레임워크
  - KRX 데이터 수집 팁 (pykrx, API 제한)
  - Docker 구성 및 배포
- **연락처 / 프로젝트 링크**
