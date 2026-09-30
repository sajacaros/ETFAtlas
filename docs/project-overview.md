# ETF Atlas 프로젝트 개요

> 2026-09-30 재가동 시점 기준 정리. 코드 구조·데이터 흐름·알려진 이슈·다음 할 일을 한곳에 모은 문서다.
> 세부 설계는 `architecture.md`, `dags.md`, `graph.md`, `postgresql.md`, `api-schema.md`를 참고.

## 1. 서비스 구성

한국 ETF(순자산 500억 이상 신규 편입 기준)를 탐색하고, 개인 포트폴리오를 관리하고, AI 챗봇에 질문하는 웹 서비스.

| 서비스 | 스택 | 포트 |
|---|---|---|
| db | PostgreSQL 18 + Apache AGE 1.8.0(그래프) + pgvector 0.8.6 + pg_trgm | 9602 |
| backend | FastAPI, SQLAlchemy 2.1(동기, psycopg2), Python 3.14 | 9601 |
| frontend | React 18 + Vite + TailwindCSS + shadcn/ui + Recharts, nginx 서빙 | 9600 |
| airflow | Airflow 3.3.2 (Python 3.14, LocalExecutor) — api-server / scheduler / dag-processor | 9603 |

같은 Postgres 인스턴스에 DB 두 개: 앱 DB `etf_atlas`, Airflow 메타데이터 DB `airflow`.

## 2. 데이터 모델

**AGE 그래프 (`etf_graph`)** — 시장 데이터
- 노드: `ETF`, `Stock`, `Company`(운용사), `Tag`, `Price`, `User`
- 관계: `(ETF)-[:HOLDS {date, weight, shares}]->(Stock)`, `(ETF)-[:MANAGED_BY]->(Company)`, `(ETF)-[:TAGGED]->(Tag)`, `(ETF|Stock)-[:HAS_PRICE]->(Price)`, `(User)-[:WATCHES]->(ETF)`
- 날짜 키는 `'YYYY-MM-DD'` 문자열

**관계형 테이블** (`docker/db/init/02_schema.sql`) — 사용자/시계열
- 사용자: `users`(username/password_hash), `roles`, `user_roles`
- 포트폴리오: `portfolios`, `target_allocations`, `holdings`, `portfolio_snapshots`
- 시세 캐시: `etfs`(코드/이름), `ticker_prices`(티커별 일 1건), `collection_runs`
- 챗봇: `chat_logs`, `code_examples`(`embedding vector(768)`)
- 외부 API: `kis_tokens`(KIS 접근 토큰 캐시)

**암호화**: `holdings.quantity/avg_price`, `portfolio_snapshots`의 금액 컬럼은 앱 단 AES-256-GCM 암호문(TEXT) — `backend/app/utils/encryption.py`. `ENCRYPTION_KEY`는 한 번 정하면 바꾸면 안 된다.

## 3. Backend (`backend/app`)

- `routers/` 9개. `portfolio.py`(~950줄)가 CRUD·정렬·공유·대시보드·리스크 분석·리밸런싱 계산을 모두 담당
- `domain/portfolio_calculation.py`: 리밸런싱/수익률 계산 순수 로직
- 인증: ID/비밀번호 + JWT(PyJWT, 7일). 비밀번호는 bcrypt. 보호 라우트는 모두 `utils/jwt.get_current_user_id` 하나에 의존, 관리자 판정은 `services/auth_service.is_admin`
  - 최초 실행 시 사용자가 0명이면 프론트가 `/setup`으로 보내고, 거기서 만든 계정이 admin
  - 이후 `/login`의 회원가입 탭으로 member 가입
- 챗봇(`services/chat_service.py`): smolagents `CodeAgent` + 도구 10개(ETF/종목 검색, 가격, 비교, Cypher 직접 실행 등). 질문과 유사한 Python 코드 예시를 pgvector로 찾아 few-shot으로 주입. 관리자가 채팅 로그를 승인하면 예시로 임베딩되는 피드백 루프(`routers/admin.py`)
- 알림: Airflow 수집 완료 시 `pg_notify('new_collection')` → 백엔드 LISTEN → SSE(`/api/notifications/stream`)

### AI 연동
모든 LLM/임베딩 호출은 LiteLLM 프록시(OpenAI 호환)를 거친다.

| 설정 | 기본값 | 사용처 |
|---|---|---|
| `LLM_API_BASE` | `http://localhost:4000` | 전체 |
| `LLM_MODEL` | `qwen38-27b` (추론 모델) | 챗봇, 질문 일반화, ETF 태깅 |
| `EMBEDDING_MODEL` | `embedding-gemma-300m` (768차원) | 코드 예시 임베딩/검색 |

- `qwen38-27b`는 reasoning 토큰을 먼저 소비하므로 `max_tokens`를 넉넉히(2048+) 줘야 `content`가 비지 않는다
- structured output(`response_format=json_schema`)이 프록시에서 동작함을 확인

#### smolagents를 유지하는 이유 (2026-09 검토)
- 피드백 루프 전체가 "LLM이 작성한 Python 코드"를 단위로 동작한다: `code_examples`의 36개 시드와 승인 예시, `chat_logs.generated_code`, 관리자 페이지의 코드 리뷰, 챗 UI의 단계별 코드 표시
- CodeAgent는 한 스텝에서 여러 도구를 루프·정렬·조합하므로 "반도체 ETF 3개 수익률 비교" 같은 질문을 적은 왕복으로 처리한다
- qwen38-27b + 프록시 조합에서 도구 3회 호출·정렬·표 출력·`final_answer`까지 정상 동작 확인(약 13초)
- 네이티브 tool-calling으로 바꾸면 위 자산(예시 포맷, 관리 UI, 로그 스키마)을 전부 다시 만들어야 해서 지금은 이득이 적다
- 대신 모델 어댑터를 `LiteLLMModel` → `OpenAIModel`로 바꿔 `litellm` 패키지 의존성을 제거했다(프록시가 이미 LiteLLM)
- 주의: smolagents의 `LocalPythonExecutor`는 보안 샌드박스가 아니다. 허용 import는 `json`, `datetime`로 제한되어 있다

## 4. 데이터 파이프라인 (Airflow)

| DAG | 스케줄(KST) | 역할 | 소스 |
|---|---|---|---|
| `age_backfill` | 수동 | **초기 적재**: 유니버스·ETF 가격 이력 → 현재 구성종목 1회 → 주식 가격 이력 → 수익률 | KRX Open API, KIS, pykrx |
| `age_sync_universe` | 화~토 08:30 | 증분: 유니버스·가격 → 구성종목(최근 거래일) → 주식 가격·수익률·신규 ETF 태그 | KRX Open API, KIS, pykrx |
| `rdb_sync_metadata` | 평일 08:30 | ETF 코드/이름 → RDB `etfs` | KRX Open API |
| `rdb_realtime_prices` | 평일 9~15시 10분 간격 | 보유 티커 현재가 → `ticker_prices`, 스냅샷 갱신(`snapshot_enabled` 포트폴리오만) | yfinance, pykrx(장 운영 체크) |
| `age_tagging` | 토 03:00 | 룰 + LLM 기반 ETF 태그 재구성 | LLM 프록시 |
| `rdb_backfill` | 수동 | ETF 가격 이력(2025-01~) → `ticker_prices` | yfinance |
| `embed_code_examples` | 수동 | 코드 예시 질문 일반화 + 임베딩 | LLM 프록시 |

### 구성종목(HOLDS) — KIS Open API
- `airflow/dags/kis_api_client.py`: `ETF 구성종목시세[국내주식-073]` (`FHKST121600C0`)
- **날짜 지정 불가(호출 시점 스냅샷)** → 과거 구성종목 백필은 지원하지 않는다. 매일 쌓이는 데이터로만 1주/1개월 비중 변화가 계산된다
- 스냅샷은 DAG의 최근 거래일 날짜로 저장(08:30 실행 기준 직전 거래일)
- `shares`는 API에 수량 필드가 없어 `평가금액(etf_vltn_amt) / 현재가(stck_prpr)`로 역산한 추정치
- 토큰(24h 유효, 발급 1분 1회 제한)은 `kis_tokens`에 캐시, 호출 간 최소 간격 0.06s, `EGW00201`(초당 초과) 재시도, `EGW00123`(토큰 만료) 1회 재발급
- 실전투자 앱키 필요(`KIS_APP_KEY`, `KIS_APP_SECRET`)

## 5. Frontend (`frontend/src`)

- 페이지 13개: 홈(검색/Top), ETF 상세, 포트폴리오, 대시보드(개별/통합), 관심종목 변화, 공유 포트폴리오, 챗봇, 관리자, 로그인, 초기 설정
- `hooks/useAuth.tsx`: setup-status 조회 → `App.tsx`의 `SetupGuard`가 `/setup`으로 리다이렉트
- PDF 내보내기: jsPDF + NotoSansKR

## 6. 2026-09 재가동 변경 요약

| 영역 | 이전 | 이후 |
|---|---|---|
| Python | backend 3.11 / airflow 3.12 | 3.14 |
| Airflow | 2.10.4, 단일 컨테이너(webserver+scheduler), 기동 시 pip install | 3.3.2 커스텀 이미지, api-server/scheduler/dag-processor 분리, 메타DB 분리 |
| DB | PG17 + AGE 1.7.0 + pgvector 0.8.0, init SQL + 수동 마이그레이션 | PG18 + AGE 1.8.0 + pgvector 0.8.6, 깨끗한 init SQL 4개 |
| 인증 | Google OAuth | ID/비밀번호, 최초 setup 페이지에서 admin 생성 |
| AI | OpenAI 직접 호출(gpt-4.1-mini, text-embedding-3-small 1536d), langchain, litellm | LiteLLM 프록시(qwen38-27b, embedding-gemma-300m 768d), openai SDK만 사용 |
| 구성종목 | pykrx KRX 스크래핑(날짜별) | KIS Open API(현재 스냅샷), 과거 백필 제거 |
| 기타 | python-jose, passlib | PyJWT, bcrypt, 인증/KIS 단위 테스트 추가 |

이전 기능별 설계 문서(`docs/plans/*`, 2026-02~03)는 모두 구현 완료되어 삭제했다(git 이력에 남아 있음): 실시간 가격 수집, 포트폴리오 드래그 정렬, few-shot Cypher→Python 코드 예시, 포트폴리오 데이터 암호화, 포트폴리오 공유, 가격 백필, 리스크 분석, PDF 다운로드, `snapshot_enabled` 토글.

## 7. 알려진 이슈 / 다음 할 일

- **pykrx 잔존**: 영업일 판단, 주식 일봉(Naver), 장 운영 체크, 보수율(KRX 스크래핑 — pykrx 1.2.9부터 `KRX_ID`/`KRX_PW` 필요)에 여전히 사용. pykrx가 `pandas<3`을 요구해 Airflow constraints(pandas 3)를 벗어나 설치한다. KIS 일봉/휴장일 API로 옮기면 의존성을 제거할 수 있다
- **스키마 마이그레이션 도구 없음**: init SQL은 볼륨 최초 생성 시에만 실행된다. 스키마를 바꾸면 기존 DB에는 수동 ALTER가 필요. 운영 데이터가 쌓이기 전에 Alembic 도입 검토
- **테스트 부족**: 인증(`backend/tests`)과 KIS 클라이언트(`airflow/tests`)만 있다. `domain/portfolio_calculation.py` 단위 테스트가 다음 우선순위
- **대형 파일**: `routers/portfolio.py`, `frontend/src/app/PortfolioPage.tsx`(1000줄+), `airflow/dags/age_utils.py`(1200줄+) 분리 필요
- **프론트 lint 미동작**: `npm run lint`가 ESLint 설정 파일이 없어 실패(기존부터). ESLint 9 flat config로 새로 구성 필요
- **CodeAgent 실행 격리**: LLM 생성 코드가 백엔드 프로세스에서 실행된다. 외부 공개 전 샌드박스(E2B/Docker executor 등) 검토
- **KIS 첫 호출 검증**: 실제 앱키로 `python airflow/dags/kis_api_client.py 069500`을 실행해 `output2` 필드(특히 비중 단위, 평가금액 기준)를 확인할 것
