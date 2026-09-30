# ETF Atlas

한국 ETF 시장을 탐색하고, 포트폴리오를 관리하며, AI 챗봇과 대화할 수 있는 올인원 ETF 분석 플랫폼입니다.

## 주요 기능

### ETF 탐색
- **ETF 검색** - 이름/종목코드로 ETF 검색 (pg_trgm 기반 유사 검색)
- **Top ETF** - 시가총액, 수익률 기준 정렬
- **ETF 상세** - 구성종목, 가격 차트(365일), 카테고리 태그
- **구성종목 변화 추적** - 1일/1주/1개월 비중 변화 감지 (구성종목은 매일 스냅샷으로 누적)
- **유사 ETF 추천** - 구성종목 겹침 기반 유사도 분석

### 포트폴리오 관리
- **포트폴리오 CRUD** - 생성, 수정, 삭제, 드래그앤드롭 정렬
- **보유종목 관리** - ETF/주식/현금 보유종목 추가 및 수정
- **목표 비중 설정** - 자산별 목표 배분 비율 관리
- **리밸런싱 계산** - 현재 비중 대비 목표 비중 기반 매수/매도 계산
- **포트폴리오 대시보드** - 일별 평가금액 추이 차트, 수익률 요약
- **통합 대시보드** - 전체 포트폴리오 합산 현황

### 관심종목(Watchlist)
- ETF 관심 등록/해제
- 관심종목 구성종목 비중 변화 알림 (3%p 이상)

### AI 챗봇
- ETF 관련 질문 응답 (pydantic-ai tool-calling 에이전트, 도구 10개)
- 유사 질문의 해결 절차(도구 호출 순서)를 pgvector로 검색해 few-shot 주입, 관리자 승인 기반 예시 축적
- 스트리밍 응답 지원

### 알림
- PostgreSQL LISTEN/NOTIFY 기반 실시간 SSE 알림
- 구성종목 변화 감지 시 자동 알림

### 데이터 파이프라인 (Airflow)
- **ETF 유니버스/가격** - KIS 종목 마스터 파일 + ETF 현재가·일봉으로 일별 수집 (순자산 500억 이상 국내 주식형 신규 편입)
- **구성종목** - 한국투자증권 KIS Open API `ETF 구성종목시세`로 매일 스냅샷 수집 (과거 날짜 조회 불가 → 백필 없음)
- **주식 가격 / 영업일 / 휴장일** - KIS Open API 일봉·국내휴장일조회
- **보수율** - 네이버 증권(신규 ETF 편입 시)
- **실시간 가격 + 포트폴리오 스냅샷** - 장중 10분 간격 현재가 갱신, 스냅샷 켠 포트폴리오의 평가금액 기록
- **자동 태깅** - LLM(LiteLLM 프록시) 기반 ETF 테마 분류

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| Frontend | React 18, TypeScript, Vite, TailwindCSS, shadcn/ui, Recharts |
| Backend | Python 3.14, FastAPI, SQLAlchemy 2.1 (동기, psycopg2), Pydantic 2 |
| Database | PostgreSQL 18 + Apache AGE 1.8 (그래프) + pgvector 0.8 + pg_trgm |
| Pipeline | Apache Airflow 3.3 (Python 3.14) |
| Auth | ID/비밀번호 (bcrypt) + JWT |
| AI | LiteLLM 프록시(OpenAI 호환) — `qwen38-27b`, `embedding-gemma-300m`(768d), pydantic-ai |
| 외부 데이터 | 한국투자증권 KIS Open API, 네이버 증권(보수율), yfinance(실시간 현재가) |

## 실행 방법

### 사전 요구사항

- Docker & Docker Compose
- API 키: LLM 프록시 키(채팅/임베딩), 한국투자증권 KIS 실전투자 앱키

### 1. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 편집하여 값을 입력합니다:

| 변수 | 설명 | 필수 |
|------|------|------|
| `JWT_SECRET` | JWT 서명 키 (`python -c "import secrets; print(secrets.token_hex(32))"`) | O |
| `ENCRYPTION_KEY` | 포트폴리오 금액 암호화 키 (32바이트 hex, 위와 같은 방법). **한 번 정하면 변경 금지** | O |
| `LLM_API_KEY` | LiteLLM 프록시 채팅 모델 키 — 챗봇, ETF 태깅 (`LLM_API_BASE`, `LLM_MODEL`로 변경 가능) | O |
| `EMBEDDING_API_KEY` | LiteLLM 프록시 임베딩 키 — 챗봇 예시 검색 (`EMBEDDING_API_BASE`, `EMBEDDING_MODEL`로 변경 가능) | O |
| `KIS_APP_KEY` / `KIS_APP_SECRET` | 한국투자증권 Open API 앱키 ([발급](https://apiportal.koreainvestment.com)) — ETF 목록/시세/구성종목, 주식 일봉, 영업일/휴장일 | O |
| `AIRFLOW_USER` / `AIRFLOW_PASSWORD` | Airflow UI 로그인 (기본 admin / admin) | - |
| `AIRFLOW_FERNET_KEY`, `AIRFLOW_SECRET_KEY`, `AIRFLOW_JWT_SECRET` | Airflow 내부 암호화/서명 키 | - |
| `DISCORD_WEBHOOK_URL` | 수집 완료 알림 | - |

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

처음 접속하면 **초기 설정(/setup) 화면**이 나옵니다. 여기서 만든 계정이 관리자(admin)가 되고, 이후 사용자는 로그인 화면의 회원가입 탭으로 가입합니다.

### 4. 초기 데이터 수집

Airflow UI에서 아래 DAG를 순서대로 수동 실행합니다:

1. **`age_sync_universe`** - ETF 유니버스·가격, 현재 구성종목, 주식 가격 (첫 실행은 최근 거래일 하루)
2. **`rdb_sync_metadata`** - RDB ETF 메타데이터 동기화
3. **`age_tagging`** - ETF 테마 태그 부여
4. **`embed_code_examples`** - 챗봇 코드 예시 임베딩

이후에는 `age_sync_universe`, `rdb_sync_metadata`, `rdb_realtime_prices`, `age_tagging`이 스케줄에 따라 자동 실행됩니다.
과거 이력 백필은 하지 않습니다. 데이터는 첫 실행일부터 매일 쌓이므로 1주/1개월 수익률·비중 변화, 포트폴리오 추이 차트는 데이터가 쌓인 뒤부터 보입니다.

### 백엔드 코드 수정 시

백엔드는 볼륨 마운트가 없으므로 코드 변경 후 재빌드가 필요합니다:

```bash
docker compose up -d --build backend
```

### 테스트

```bash
cd backend && pip install -r requirements-dev.txt && ENCRYPTION_KEY=00 pytest -q
cd airflow && pytest -q tests   # requests, pytest 필요
```

## 프로젝트 구조

```
etf-atlas/
├── frontend/          # React 프론트엔드
│   └── src/
│       ├── app/       # 페이지 컴포넌트
│       ├── components/# 공통 UI 컴포넌트
│       └── lib/       # API 클라이언트, 유틸리티
├── backend/           # FastAPI 백엔드
│   ├── app/
│   │   ├── routers/   # API 라우터 (auth, etfs, portfolios, ...)
│   │   ├── models/    # SQLAlchemy 모델
│   │   └── services/  # 비즈니스 로직 (챗봇, 그래프, 인증 ...)
│   └── tests/
├── airflow/           # 데이터 파이프라인
│   ├── dags/          # DAG 정의, KIS/네이버 클라이언트, AGE 유틸
│   └── tests/
├── docker/
│   ├── db/            # PostgreSQL + AGE + pgvector 이미지, init SQL
│   └── airflow/       # Airflow 이미지
├── docs/              # 문서 (시작은 docs/project-overview.md)
├── scripts/           # 그래프 뷰어 등 도구
├── docker-compose.yml
└── .env.example
```
