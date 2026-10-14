# ETF Atlas 프로젝트 개요

> 현재 구조·데이터 흐름·알려진 이슈를 한곳에 모은 문서다. 처음 보는 사람은 여기서 시작한다.

| 문서 | 내용 |
|---|---|
| `frontend/public/story.html` | 프로젝트 소개 (웹 화면의 Story) |
| `frontend/public/architecture.html` | 챗봇 아키텍처 (웹 화면의 Architecture) |
| [answer-skills.md](answer-skills.md) | 챗봇 답변 화면: 레이아웃·스킬 구현과 확장 |
| [chatbot_tools.md](chatbot_tools.md) | `agent` 스킬 안의 에이전트와 도구 10개 |
| [dags.md](dags.md) | Airflow DAG |
| [data-mapping.md](data-mapping.md) | 외부 데이터 소스 → DB 매핑 |
| [graph.md](graph.md) | AGE 그래프 스키마와 쿼리 |
| [postgresql.md](postgresql.md) | PostgreSQL 확장, Alembic 마이그레이션 |
| [search.md](search.md) | ETF 검색, 유사 ETF |
| [notify.md](notify.md) | 비중 변화 알림 (인앱·디스코드) |

API 전체 목록은 Swagger(`http://localhost:9601/docs`)를 본다.

## 1. 서비스 구성

한국 ETF(순자산 500억 이상 신규 편입 기준)를 탐색하고, 액티브 ETF의 비중 변화를 보고, 개인 포트폴리오를 관리하고, AI 챗봇에 질문하는 웹 서비스.

| 서비스 | 스택 | 포트 |
|---|---|---|
| db | PostgreSQL 18 + Apache AGE 1.8.0(그래프) + pgvector 0.8.6 + pg_trgm | 9602 |
| backend | FastAPI, SQLAlchemy 2.1(동기, psycopg2), pydantic-ai, Python 3.14 | 9601 |
| frontend | React 18 + Vite + TailwindCSS + shadcn/ui, 차트 Recharts·ECharts(챗봇), nginx 서빙 | 9600 |
| airflow | Airflow 3.3.2 (Python 3.14, LocalExecutor) — api-server / scheduler / dag-processor | 9603 |

같은 Postgres 인스턴스에 DB 두 개: 앱 DB `etf_atlas`, Airflow 메타데이터 DB `airflow`. 외부에 여는 포트는 frontend 하나이고 나머지는 127.0.0.1에만 바인딩한다.

## 2. 데이터 모델

**AGE 그래프 (`etf_graph`)** — 시장 데이터
- 노드: `ETF`(액티브 여부 `active`, 전체 구성종목 수 `component_count` 포함), `Stock`, `Company`(운용사), `Tag`, `Price`, `User`
- 관계: `(ETF)-[:CURRENT_HOLDS {date, weight, shares}]->(Stock)`(현재 보유, ETF당 최대 30개), `(ETF)-[:HOLDS {date, weight, shares}]->(Stock)`(날짜별 이력, 변화 비교용), `(ETF)-[:MANAGED_BY]->(Company)`, `(ETF)-[:TAGGED]->(Tag)`, `(ETF|Stock)-[:HAS_PRICE]->(Price)`, `(User)-[:WATCHES]->(ETF)`
- 날짜 키는 `'YYYY-MM-DD'` 문자열

**관계형 테이블** — 사용자/시계열. 스키마는 Alembic(`backend/migrations`)으로 관리하고 백엔드 기동 시 `alembic upgrade head`
- 사용자: `users`, `roles`, `user_roles`, `auth_sessions`, `invitations`, `password_resets`
- 포트폴리오: `portfolios`, `target_allocations`, `holdings`, `portfolio_snapshots`
- 시세·수집: `etfs`(코드/이름), `ticker_prices`(티커별 일 1건), `collection_runs`, `weight_changes`(액티브 ETF 비중 변화), `market_calendar`
- 챗봇: `chat_sessions`, `chat_logs`, `chat_slots`(답변 화면 영역), `code_examples`·`layout_examples`(`embedding vector(768)`)
- 설정: `ai_settings`, 디스코드 설정·발송 기록, `kis_tokens`(KIS 접근 토큰 캐시)

**암호화**: `holdings.quantity/avg_price`, `portfolio_snapshots`의 금액 컬럼은 앱 단 AES-256-GCM 암호문(TEXT) — `backend/app/utils/encryption.py`. `ENCRYPTION_KEY`는 한 번 정하면 바꾸면 안 된다.

## 3. Backend (`backend/app`)

- `routers/` 10개. `portfolio.py`(~1000줄)가 CRUD·정렬·공유·대시보드·리스크 분석·리밸런싱 계산을 모두 담당
- `domain/portfolio_calculation.py`: 리밸런싱/수익률 계산 순수 로직
- 인증: ID/비밀번호 + 서버 세션(HttpOnly 쿠키 `etf_atlas_session`, 7일, 토큰 해시를 `auth_sessions`에 저장). 비밀번호는 bcrypt. 보호 라우트는 모두 `utils/session.get_current_user_id` 하나에 의존, 관리자 판정은 `services/auth_service.is_admin`
  - 최초 실행 시 사용자가 0명이면 프론트가 `/setup`으로 보내고, 거기서 만든 계정이 admin
  - 공개 회원가입은 없다. 관리자가 만든 초대 링크(`/invite/{token}`, 1회용·7일 유효, `invitations` 테이블)로만 member 가입
  - 관리자 페이지 멤버 탭: 회원 목록, 관리자 권한 부여/회수, 강제 로그아웃, 삭제, 비밀번호 재설정 링크(`/reset-password/{token}`, 1회용·24시간, `password_resets`에 해시로 저장) (`services/member_service.py`)
  - `auth` 외 모든 API는 로그인 필요 (`etfs`·`tags`·`shared`는 `main.py`에서 라우터 단위로 인증)
- 챗봇(`services/answer/`): 질문 재작성 → 레이아웃 에이전트가 화면을 슬롯으로 설계 → 슬롯마다 스킬이 채운다(데이터 스킬은 그래프 조회, `narrative`는 해설, `agent`는 스킬로 안 되는 질문). 진행은 SSE로, 영역 내용은 `chat_slots`에 저장해 GET으로. 상세: `architecture.html`, `answer-skills.md`
  - `agent` 스킬 안의 `services/chat_service.py`: pydantic-ai tool-calling 에이전트 + 도구 10개. 유사한 해결 절차 예시를 pgvector로 찾아 few-shot으로 주입하고, 관리자가 승인한 채팅 로그도 예시가 된다. 상세: `chatbot_tools.md`
- 비중 변화 알림: Airflow가 계산한 `weight_changes`를 웹(`/changes`)·메뉴 배지·디스코드가 함께 읽는다. 수집 완료는 `pg_notify('new_collection')` → 백엔드 LISTEN → SSE. 상세: `notify.md`

### AI 연동
모든 LLM/임베딩 호출은 LiteLLM 프록시(OpenAI 호환)를 거친다.

| 설정 | 기본값 | 사용처 |
|---|---|---|
| `LLM_API_BASE` / `EMBEDDING_API_BASE` | `http://localhost:4000` | 채팅 / 임베딩 |
| `LLM_MODEL` | `qwen38-27b` (추론 모델) | 챗봇, 질문 일반화, ETF 태깅 |
| `EMBEDDING_MODEL` | `embedding-gemma-300m` (768차원) | 코드·레이아웃 예시 임베딩/검색 |

키는 채팅 모델(`LLM_API_KEY`)과 임베딩(`EMBEDDING_API_KEY`)이 다르다. 엔드포인트도 `LLM_API_BASE` / `EMBEDDING_API_BASE`로 따로 지정할 수 있다(기본값 동일).
관리자 페이지 > AI 탭에서 저장한 값(`ai_settings` 테이블, 키는 `ENCRYPTION_KEY`로 암호화)이 있으면 환경변수보다 우선한다.

- `qwen38-27b`는 reasoning 토큰을 먼저 소비하므로 `max_tokens`를 넉넉히(2048+) 줘야 `content`가 비지 않는다
- structured output(`response_format=json_schema`)이 프록시에서 동작함을 확인

## 4. 데이터 파이프라인 (Airflow)

| DAG | 스케줄(KST) | 역할 | 소스 |
|---|---|---|---|
| `rdb_sync_metadata` | 매일 08:40 | ETF 코드/이름 → RDB `etfs` | KIS 종목 마스터 파일(인증 불필요) |
| `age_sync_universe` | 매일 08:50 | 증분: 유니버스·가격(확정된 날까지) → 구성종목(개장일에만, 공시일 날짜) → 주식 가격·수익률 → 액티브 ETF 비중 변화 → 신규 ETF 태그 → 수집 기록·디스코드 | KIS, 네이버(보수율) |
| `rdb_realtime_prices` | 평일 9~15시 10분 간격 | 보유 티커 현재가 → `ticker_prices`, 스냅샷 갱신(`snapshot_enabled` 포트폴리오만) | yfinance, KIS(휴장일, `market_calendar`에 하루 1회 캐시) |
| `age_tagging` | 토 03:00 | 룰 + LLM 기반 태깅. 미태깅(`tagged_at` 없음) ETF만, `full_rebuild=true` 수동 실행 시 전체 | LLM 프록시 |
| `embed_code_examples` | 수동 | 코드 예시 질문 일반화 + 임베딩 | LLM 프록시 |

**백필 없음**: 첫 실행은 최근 거래일 하루만 수집하고 이후 매일 쌓인다. 1주/1개월 수익률, 포트폴리오 추이 차트, 리스크 분석은 데이터가 쌓인 만큼만 보인다.

### 구성종목(HOLDS / CURRENT_HOLDS) — KIS Open API
- `airflow/dags/kis_api_client.py`: `ETF 구성종목시세[국내주식-073]` (`FHKST121600C0`)
- **날짜 지정 불가(호출 시점 스냅샷)** → 과거 구성종목 백필은 지원하지 않는다. 매일 쌓이는 데이터로만 1주/1개월 비중 변화가 계산된다
- KIS는 개장일 08:30에 그날 공시분(직전 거래일 장 마감 기준 보유)으로 갱신한다. 개장일에만 받아 그날(공시일) 날짜로 저장하고, 비중 변화는 ETF별 직전 수집일과 비교한다. 주말·휴장일에는 받지 않는다
- 저장 후 그날 HOLDS가 있는 ETF의 `CURRENT_HOLDS`를 그날 HOLDS로 교체(`refresh_current_holds`). 현재 구성종목 조회는 `CURRENT_HOLDS`, 비중 변화·이력은 `HOLDS`를 읽는다. 조회 실패 ETF는 이전 구성종목 유지
- `shares`는 API에 수량 필드가 없어 `평가금액(etf_vltn_amt) / 현재가(stck_prpr)`로 역산한 추정치
- 토큰(24h 유효, 발급 1분 1회 제한)은 `kis_tokens`에 캐시, 호출 간 최소 간격 0.06s, `EGW00201`(초당 초과) 재시도, `EGW00123`(토큰 만료) 1회 재발급
- 실전투자 앱키 필요(`KIS_APP_KEY`, `KIS_APP_SECRET`)

### ETF 목록·유니버스·가격 — KIS
- 목록: KIS 종목 마스터 파일(`kospi_code.mst.zip`, 인증 불필요)의 ETF 그룹(`EF`, 약 1,175개)
- 신규 편입: 기존 유니버스 + 이름 필터(해외·레버리지·채권·원자재 등 제외) 통과 ETF만 `ETF/ETN 현재가`를 호출해 순자산 500억 이상이면 추가
- 가격: OHLCV·거래대금은 KIS 일봉(16시 전이면 전날까지만), NAV·순자산·시가총액은 현재가 API라 최근 거래일에만 기록
- 현재가 API의 분류(`bstp_kor_isnm`)로 액티브 여부, `etf_cnfg_issu_cnt`로 전체 구성종목 수를 기록
- 순자산(`etf_ntas_ttam`) 단위가 문서화되어 있지 않아 1억 미만 값은 억원으로 간주해 환산한다 — 실제 키로 확인 필요
- 호출 수는 하루 수백 회(현재가 + 일봉)

### 그 밖의 KIS 사용처
- 영업일: 기준 ETF(069500) 일봉 날짜 (`국내주식기간별시세`, 호출당 최대 100일)
- 주식 일봉: 같은 API로 종목당 기간 전체를 한 번에 조회
- 장 운영 체크: `국내휴장일조회`(KIS 요청: 1일 1회) → `market_calendar` 테이블에 캐시
- 구성종목 필터: 6자리 상장 코드 패턴(`is_listed_security_code`)으로 채권·현금·선물 제외

## 5. Frontend (`frontend/src`)

- 페이지 15개: 홈(검색·태그·액티브/패시브), ETF 상세, 액티브 ETF 비중 변화, 구성종목 분석, 포트폴리오, 대시보드(개별/통합), 공유 포트폴리오, 챗봇, 관리자, 내 정보, 로그인, 초기 설정, 초대 가입, 비밀번호 재설정
- 챗봇 답변 화면: `components/answer/` (레이아웃 트리 렌더링, ECharts 차트 빌더)
- 사이드바의 Story / Architecture는 `public/*.html` 정적 문서를 다이얼로그로 연다
- `hooks/useAuth.tsx`: setup-status 조회 → `App.tsx`의 `SetupGuard`가 `/setup`으로, `AuthGuard`가 미로그인 시 `/login`으로 리다이렉트 (`/login`·`/setup`·`/invite/*` 제외). API가 401을 주면 자동 로그아웃
- PDF 내보내기: jsPDF + NotoSansKR

## 6. 알려진 이슈 / 다음 할 일

- **보수율은 비공식 API**: KIS/KRX Open API 모두 ETF 총보수를 제공하지 않아 네이버 증권 모바일 API(`etfAnalysis.totalFee`)를 쓴다. 형식이 바뀌면 신규 ETF의 보수율만 비고 수집은 계속된다
- **실시간 현재가는 yfinance**: `rdb_realtime_prices`는 아직 yfinance(`.KS`)를 쓴다. KIS 현재가로 옮기면 시세 소스를 KIS 하나로 통일할 수 있다
- **테스트**: 백엔드(`backend/tests`: 인증·챗봇·답변 화면 등)와 KIS·유틸(`airflow/tests`)에 있다. 포트폴리오 계산(`domain/portfolio_calculation.py`) 단위 테스트가 비어 있다. 레이아웃 설계 품질은 `backend/evals/`로 본다
- **대형 파일**: `routers/portfolio.py`(1000줄), `frontend/src/app/PortfolioPage.tsx`(1100줄+), `airflow/dags/age_utils.py`(1500줄+) 분리 필요
- **프론트 lint 미동작**: `npm run lint`가 ESLint 설정 파일이 없어 실패(기존부터). ESLint 9 flat config로 새로 구성 필요
