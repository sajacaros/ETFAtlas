# ETF Atlas

한국 ETF 시장을 탐색하고, 포트폴리오를 관리하며, AI 챗봇과 대화할 수 있는 올인원 ETF 분석 플랫폼입니다.

## 주요 기능

### ETF 탐색
- **ETF 검색** - 이름/종목코드로 ETF 검색 (pg_trgm 기반 유사 검색)
- **목록** - 시가총액·수익률 정렬, 테마 태그, 액티브/패시브, 즐겨찾기
- **ETF 상세** - 구성종목(상위 30개 + 전체 종목 수), 가격 차트, 태그, 비중 변화, 보수율·분배율
- **유사 ETF** - 구성종목 비중 겹침 기반 유사도

### 액티브 ETF 비중 변화
- 액티브 ETF 전체의 신규 편입·편출·비중 증감을 공시일별로 표시 (Airflow가 수집 후 계산). 전날·1주·1개월 전과 비교
- 메뉴 배지와 디스코드 알림 (기준 %p는 관리자 페이지에서 설정, 신규 편입은 기준을 따로 둔다)

### 구성종목 분석
- ETF와 투자 비중을 넣으면 실제로 담기는 종목 비중을 계산

### 포트폴리오 관리
- **포트폴리오 CRUD** - 생성, 수정, 삭제, 드래그앤드롭 정렬, 공유
- **보유종목 관리** - ETF/주식/현금 보유종목 추가 및 수정
- **목표 비중 / 리밸런싱** - 현재 비중 대비 목표 비중 기반 매수/매도 계산
- **대시보드** - 일별 평가금액 추이, 수익률 요약, 전체 포트폴리오 합산

### 종목 스크리너
- 노드를 이어 `대상 종목 → 차트 필터 → AI 분석 → 결과` 순서로 이어 스크리너를 만들고 실행 (갈래를 나눠 교집합·합집합도 가능)
- 대상 종목: ETF가 담은 전체 종목 / 특정 ETF 구성종목 / 내 포트폴리오 실보유 / 직접 입력
- 필터: 이평 정배열·고가 대비 위치·수익률·거래량 배수·RSI·간이 VCP, MACD·스토캐스틱 골든크로스(과매도 구간 한정 가능)·볼린저 %B (시세는 검증 단계라 yfinance 1년 일봉), ETF 신호(담은 ETF 수, 액티브 ETF 신규 편입·비중 증가)
- AI 분석은 계산된 지표만 받아 근거를 정리하고, 스크리너는 저장해 다시 불러올 수 있다 — [docs/analysis-flow.md](docs/analysis-flow.md)
- 저장한 스크리너는 고른 종목이 날마다 기록되고, 다음 거래일 종가에 샀다고 보고 5·20·60거래일 뒤 KODEX 200 대비 초과수익·적중률·손익비·가장 나빴던 기록으로 채점한다
- 자동 실행을 켜면 영업일 장 마감 뒤 저장된 스크리너를 돌리고, 새로 들어오거나 빠진 종목을 디스코드로 알린다

### AI 챗봇
- 질문에 맞춰 화면을 설계하고 표·차트·해설로 답한다 (레이아웃 에이전트 + 스킬 21개)
- 표·차트의 숫자는 DB에서 바로 오고, LLM은 화면 설계와 해설, 정기보고서 읽기만 맡는다
- **ETF** - 가격·기간 수익률·비교·프로필·구성종목·겹침·순위(수익률·순자산·보수·분배율), 여러 ETF를 섞은 합산 비중
- **기업 분석** - ETF가 담은 종목을 DART로: 분기 실적, 밸류에이션(PER·PBR·ROE·FCF·역산 DCF), 유형 판정(성장·턴어라운드·경기민감 등), 공시, 정기보고서
- **정기보고서** - 밤마다 목차 트리로 색인해 두고, 질문이 오면 목차에서 답이 있는 절을 골라 그 절만 읽고 답한다(출처 절 표시). 매출 구성은 차트로 — [docs/report-index.md](docs/report-index.md)
- **차트 분석** - 이평·볼린저·MACD·RSI·스토캐스틱과 대가들의 규칙(와인스타인·미너비니·엘더·카드웰)으로 본 지표별 강세·약세 신호
- **살까 말까** - 차트·재무·보고서 관점마다 판정하고, 종합 의견(사 볼 만하다·지켜본다·사지 않는 편이 낫다)은 판정 점수로 규칙이 정한다
- 스킬로 안 되는 질문은 tool-calling 에이전트(도구 10개, 읽기 전용 Cypher 포함 + tool을 켠 데이터 스킬 9개)가 답한다
- 매일 아침 전날 대화를 LLM이 점검해 제대로 안 나온 답과 고칠 곳을 디스코드로 보고한다 (보고만, 고치는 건 사람)
- 구조는 앱 사이드바의 **Architecture** 페이지에서 볼 수 있다

### 디스코드 알림
웹훅은 관리자 페이지에서 정하고, 같은 날짜·차례는 두 번 보내지 않는다.

| 알림 | 언제 |
|------|------|
| 액티브 ETF 비중 변화 (기준 넘은 것, 없으면 "변화 없음") | 매일 08:50 수집 뒤 |
| 일일 리포트 (오늘의 특징, 상승 ETF) | 매일 16:30 수집 뒤 |
| 스크리너 종목 변동 | 자동 실행을 켠 스크리너, 영업일 장 마감 뒤 |
| 챗봇 점검 | 매일 08:00 |
| 주간 매수 의견 (ETF가 담은 전 종목, '사 볼 만하다' 상위 10개) | 토요일 07:00 이후 — [docs/weekly-opinion.md](docs/weekly-opinion.md) |

### 관리자
- 회원 초대·관리, AI 설정, DART 키
- 챗봇 로그 검수, 화면 설계 예시·해결 절차 예시 관리
- ETF 태그 수동 지정, 디스코드 알림 설정

### 데이터 파이프라인 (Airflow)
- **ETF 유니버스/가격** - KIS 종목 마스터 파일 + ETF 현재가·일봉으로 일별 수집 (순자산 500억 이상 국내 주식형 신규 편입). 아침에 전날 값, 16:30에 그날 종가
- **구성종목** - KIS Open API `ETF 구성종목시세`로 개장일마다 공시분 수집 (과거 날짜 조회 불가 → 백필 없음)
- **주식 가격 / 영업일 / 휴장일** - KIS Open API 일봉·국내휴장일조회
- **보수율·분배율** - 네이버 증권
- **실시간 가격 + 포트폴리오 스냅샷** - 장중 10분 간격 현재가 갱신, 스냅샷 켠 포트폴리오의 평가금액 기록
- **DART** - 고유번호·공시·주요계정·현금흐름(영업활동현금흐름·설비투자)을 평일 저녁에 동기화
- **정기보고서 색인** - 최근 1년 정기보고서 원문을 목차 트리로 만들고, 노드마다 든 항목을 LLM이 한 줄로 요약, 종목별 최신 보고서 개요까지 미리 만든다 (매일 21:00, 밤새)
- **자동 태깅** - 규칙 + LLM(LiteLLM 프록시) 기반 ETF 테마 분류, 신규 ETF만
- **챗봇 점검** - 전날 대화의 실패·빈 영역·싫어요 같은 신호를 모아 세션마다 LLM이 판정

DAG별 스케줄은 [docs/dags.md](docs/dags.md). 스크리너 자동 실행과 주간 매수 의견은 Airflow가 아니라 백엔드 프로세스 안에서 돈다.

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| Frontend | React 18, TypeScript, Vite, TailwindCSS, shadcn/ui, Recharts |
| Backend | Python 3.14, FastAPI, SQLAlchemy 2.1 (동기, psycopg2), Pydantic 2 |
| Database | PostgreSQL 18 + Apache AGE 1.8 (그래프) + pgvector 0.8 + pg_trgm |
| Pipeline | Apache Airflow 3.3 (Python 3.14) |
| Auth | ID/비밀번호 (bcrypt) + 서버 세션 (HttpOnly 쿠키) |
| AI | LiteLLM 프록시(OpenAI 호환) — `qwen38-27b`, `embedding-gemma-300m`(768d), pydantic-ai |
| 외부 데이터 | 한국투자증권 KIS Open API, 금융감독원 DART OpenAPI(공시·실적·정기보고서), 네이버 증권(보수율·분배율), yfinance(실시간 현재가, 스크리너 일봉) |

## 실행 방법

### 사전 요구사항

- Docker & Docker Compose
- API 키: LLM 프록시 키(채팅/임베딩), 한국투자증권 KIS 실전투자 앱키, DART OpenAPI 키(기업 분석용, 관리자 페이지에서 등록)

### 1. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 편집하여 값을 입력합니다:

| 변수 | 설명 | 필수 |
|------|------|------|
| `COOKIE_SECURE` | 세션 쿠키 Secure 플래그. https로 서비스할 때만 `true` (http에서 켜면 로그인 불가) | - (기본 false) |
| `ENCRYPTION_KEY` | 포트폴리오 금액 암호화 키 (32바이트 hex, 위와 같은 방법). **한 번 정하면 변경 금지** | O |
| `LLM_API_KEY` | LiteLLM 프록시 채팅 모델 키 — 챗봇, ETF 태깅 (`LLM_API_BASE`, `LLM_MODEL`로 변경 가능) | O |
| `EMBEDDING_API_KEY` | LiteLLM 프록시 임베딩 키 — 챗봇 예시 검색 (`EMBEDDING_API_BASE`, `EMBEDDING_MODEL`로 변경 가능) | O |
| `KIS_APP_KEY` / `KIS_APP_SECRET` | 한국투자증권 Open API 앱키 ([발급](https://apiportal.koreainvestment.com)) — ETF 목록/시세/구성종목, 주식 일봉, 영업일/휴장일 | O |
| `AIRFLOW_USER` / `AIRFLOW_PASSWORD` | Airflow UI 로그인 (기본 admin / admin) | - |
| `AIRFLOW_FERNET_KEY`, `AIRFLOW_SECRET_KEY`, `AIRFLOW_JWT_SECRET` | Airflow 내부 암호화/서명 키 | - |
| `DISCORD_WEBHOOK_URL` | 디스코드 알림 웹훅. 관리자 페이지에서 저장한 값이 있으면 그 값이 우선 | - |

### 2. 서비스 실행

```bash
docker compose up -d --build
```

### 3. 접속 및 초기 설정

| 서비스 | URL |
|--------|-----|
| Frontend | http://localhost:9600 |
| Backend API Docs | http://localhost:9601/docs |
| Airflow | http://localhost:9603 (`AIRFLOW_USER` / `AIRFLOW_PASSWORD`) |

외부에는 Frontend(9600)만 열립니다. Backend(9601), DB(9602), Airflow(9603)는 호스트 자신에만 열리고, 브라우저의 API 요청은 Frontend가 `/api`로 받아 백엔드에 넘깁니다. 서버에 배포했다면 Airflow UI와 API 문서는 SSH 터널로 접속하세요: `ssh -L 9603:localhost:9603 -L 9601:localhost:9601 <서버>` 후 http://localhost:9603, http://localhost:9601/docs

처음 접속하면 **초기 설정(/setup) 화면**이 나옵니다. 여기서 만든 계정이 관리자(admin)가 됩니다. 모든 화면은 로그인해야 쓸 수 있고 공개 회원가입은 없습니다. 멤버는 관리자가 관리 페이지의 **멤버 초대** 탭에서 만든 초대 링크(1회용, 7일 유효)로 가입합니다. 가입한 멤버는 **멤버** 탭에서 관리자 권한 부여·강제 로그아웃·삭제를 할 수 있고, 비밀번호를 잊은 멤버에게는 재설정 링크(1회용, 24시간 유효)를 만들어 전달합니다.

### 4. 초기 데이터 수집

Airflow UI에서 아래 DAG를 순서대로 수동 실행합니다:

1. **`age_sync_universe`** - ETF 유니버스·가격, 현재 구성종목, 주식 가격 (첫 실행은 최근 거래일 하루)
2. **`rdb_sync_metadata`** - RDB ETF 메타데이터 동기화
3. **`age_tagging`** - ETF 테마 태그 부여
4. **`embed_code_examples`** - 챗봇 코드 예시 임베딩
5. **`backfill_prices`** - ETF·종목 가격 이력 백필 (기본 400일, 1개월~1년 수익률·차트 분석용)
6. **`dart_sync_rdb`** - DART 고유번호·공시·주요계정·현금흐름 (관리자 페이지 **DART** 탭에 키를 먼저 등록)
7. **`dart_report_index`** - 정기보고서 목차 트리 색인 (처음에는 보고서가 수천 건이라 2~3일 밤에 나눠 끝난다)

이후에는 아래가 스케줄에 따라 자동 실행됩니다 (KST).

| DAG | 스케줄 |
|-----|--------|
| `chat_review` | 매일 08:00 |
| `rdb_sync_metadata` | 매일 08:40 |
| `age_sync_universe` | 매일 08:50, 16:30 |
| `rdb_realtime_prices` | 평일 09:00~15:50, 10분마다 |
| `dart_sync_rdb` | 평일 19:20 |
| `dart_report_index` | 매일 21:00 |
| `age_tagging` | 토 03:00 |


가격(종가·거래량)은 `backfill_prices`로 지난 1년을 채울 수 있습니다. NAV·순자산·시가총액과 구성종목은 날짜 지정이 안 돼 백필하지 않으므로, 비중 변화·시가총액 증감은 첫 실행일부터 쌓인 만큼 보입니다.

### 백엔드 코드 수정 시

백엔드는 볼륨 마운트가 없으므로 코드 변경 후 재빌드가 필요합니다:

```bash
docker compose up -d --build backend
```

### DB 스키마 변경

RDB 스키마는 Alembic으로 관리합니다. 모델(`backend/app/models`)을 고친 뒤 `backend/migrations/versions/`에 리비전을 추가하면, 백엔드 컨테이너가 시작할 때 `alembic upgrade head`로 적용합니다. 자세한 절차는 [docs/postgresql.md](docs/postgresql.md#스키마-마이그레이션-alembic)를 참고하세요.

### 테스트

```bash
cd backend && pip install -r requirements-dev.txt && ENCRYPTION_KEY=00 pytest -q
cd airflow && pytest -q tests   # requests, pytest 필요
```

## 프로젝트 구조

```
etf-atlas/
├── frontend/          # React 프론트엔드
│   ├── public/        # story.html · architecture.html (앱 안의 Story / Architecture 문서 원본)
│   └── src/
│       ├── app/       # 페이지 컴포넌트
│       ├── components/# 공통 UI 컴포넌트
│       └── lib/       # API 클라이언트, 유틸리티
├── backend/           # FastAPI 백엔드
│   ├── app/
│   │   ├── routers/   # API 라우터 (auth, etfs, portfolios, ...)
│   │   ├── models/    # SQLAlchemy 모델
│   │   ├── domain/    # 챗봇·스크리너가 같이 쓰는 계산 (지표, 신호, 실적, 밸류에이션, 유형, 매수 의견 규칙)
│   │   └── services/  # 비즈니스 로직 (챗봇 answer/, 스크리너 flow/, 보고서 색인, 주간 매수 의견 ...)
│   └── tests/
├── airflow/           # 데이터 파이프라인
│   ├── dags/          # DAG 정의, KIS/네이버/DART 클라이언트, AGE 유틸
│   └── tests/
├── docker/
│   ├── db/            # PostgreSQL + AGE + pgvector 이미지, init SQL
│   └── airflow/       # Airflow 이미지
├── docs/              # 개발 문서 (시작은 docs/project-overview.md)
├── scripts/           # 그래프 뷰어 등 도구
├── docker-compose.yml
└── .env.example
```
