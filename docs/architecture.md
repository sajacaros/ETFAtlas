# ETF Atlas 아키텍처

## 기술 스택

| 영역 | 기술 |
|------|------|
| **Frontend** | React, TypeScript, Vite, shadcn/ui, Recharts |
| **Backend** | FastAPI, Pydantic (Python 3.14) |
| **Database** | PostgreSQL 18 + Apache AGE 1.8.0 (Graph) + pgvector 0.8.6 |
| **Data Pipeline** | Airflow 3.3.2, 한국투자증권 KIS Open API, 네이버 증권(보수율), yfinance |
| **AI** | pydantic-ai (tool-calling 에이전트) + LiteLLM 프록시 (OpenAI 호환) |
| **Auth** | 아이디/비밀번호 (bcrypt) + JWT (PyJWT) |

---

## 전체 시스템 구조

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              ETF Atlas                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐    │
│  │   Frontend   │     │   Backend    │     │   Data Pipeline      │    │
│  │              │     │              │     │                      │    │
│  │  React + TS  │────>│   FastAPI    │     │   Airflow DAG        │    │
│  │  shadcn/ui   │     │  (JWT 인증)  │     │   (Daily 08:30)      │    │
│  │              │     │              │     │                      │    │
│  └──────────────┘     └──────┬───────┘     └──────────┬───────────┘    │
│                              │                        │                 │
│         ┌────────────────────┼────────────────────────┘                 │
│         │                    │                                          │
│         v                    v                                          │
│  ┌─────────────┐    ┌────────────────────────────────────────┐         │
│  │ KIS Open API│    │              PostgreSQL                 │         │
│  │ Open API    │    │  ┌────────────────┬─────────────────┐  │         │
│  └─────────────┘    │  │  Apache AGE    │   Relational    │  │         │
│                     │  │  (ETF/Stock)   │   (User/Auth)   │  │         │
│                     │  └────────────────┴─────────────────┘  │         │
│                     └────────────────────────────────────────┘         │
│                              ^                                          │
│                              │                                          │
│                     ┌────────┴───────┐     ┌────────────────┐          │
│                     │   pydantic-ai  │────>│ LiteLLM 프록시 │          │
│                     │   (AI Agent)   │     │ (LLM/임베딩)   │          │
│                     └────────────────┘     └────────────────┘          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 인증 (아이디/비밀번호 + JWT)

### 플로우

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  사용자  │     │ Frontend │     │ Backend  │
└────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │ 1. GET /api/auth/setup-status
     │                │───────────────>│
     │                │ setup_required │
     │                │<───────────────│
     │                │                │
     │  (setup_required = true → /setup 으로 리다이렉트)
     │ 2. 관리자 계정 입력             │
     │───────────────>│ POST /api/auth/setup
     │                │───────────────>│ (사용자 0명일 때만, admin 역할 부여)
     │                │                │
     │  (이후 → /login: 로그인 / 회원가입 탭)
     │ 3. 아이디/비밀번호              │
     │───────────────>│ POST /api/auth/login 또는 /register
     │                │───────────────>│ bcrypt 검증 / 해시 저장
     │                │   JWT 발급     │
     │                │<───────────────│
     │ 4. 로그인 완료 │ (localStorage 저장, Authorization: Bearer)
     │<───────────────│                │
```

### 구현 요소

| 요소 | 설명 |
|------|------|
| `bcrypt` | 비밀번호 해시 (`backend/app/utils/security.py`, 입력 최대 72바이트) |
| `PyJWT` | HS256 access token (기본 7일, `JWT_SECRET`), refresh token 없음 |
| 최초 설치 | 사용자가 0명이면 `/setup`에서 관리자 계정 생성 (`POST /api/auth/setup`) |
| 회원가입 | `POST /api/auth/register` — `member` 역할, 설치 완료 후에만 가능 |
| users 테이블 | username, password_hash, name 저장 (역할은 `roles`/`user_roles`) |

---

## 데이터 파이프라인 (Airflow)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  age_sync_universe DAG (화~토 08:30 KST)                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐              │
│  │  영업일     │     │  유니버스   │     │  구성종목   │              │
│  │  조회       │────>│  + ETF 가격 │────>│  (HOLDS)    │              │
│  │  (KIS 일봉) │     │ (KIS 마스터 │     │  (KIS Open  │              │
│  │             │     │ 현재가·일봉)│     │   API)      │              │
│  └─────────────┘     └──────┬──────┘     └──────┬──────┘              │
│                              │                   │                      │
│                              v                   v                      │
│                       ┌─────────────┐     ┌─────────────┐              │
│                       │ 수익률 계산 │     │ 주식 가격   │              │
│                       │ 룰 기반 태그│     │ (KIS 일봉)  │              │
│                       └─────────────┘     │ 수집 기록 + │              │
│                                           │ 알림        │              │
│                                           └─────────────┘              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

데이터 소스:
├── KIS 종목 마스터 파일 (kospi_code.mst)  # 전체 ETF 코드/이름 (그룹코드 EF, 인증 불필요)
├── KIS Open API (ETF/ETN 현재가)           # NAV·순자산·상장주수 → 유니버스 편입(500억), 최근 거래일 Price
├── KIS Open API (ETF 구성종목시세)         # 호출 시점 구성종목 → 최근 거래일 HOLDS
├── KIS Open API (국내주식기간별시세)       # ETF/주식 일봉, 영업일(기준 ETF 069500 일봉)
├── KIS Open API (국내휴장일조회)           # 장중 현재가 DAG의 개장일 판정 (market_calendar 캐시)
├── 네이버 증권 모바일 API (비공식)         # 신규 ETF 보수율
└── yfinance                                # 포트폴리오 티커 현재가 (RDB)

구성종목 변화:
└── 별도 Change 노드 없이, 두 날짜의 HOLDS 스냅샷을 조회 시점에 비교
    (KIS는 과거 날짜 조회 불가 → HOLDS 이력은 수집을 시작한 날부터 쌓임)
```

DAG 상세는 [dags.md](dags.md) 참고.

---

## 데이터 모델

### Apache AGE (Graph) - ETF/종목 데이터

```
Nodes:
┌─────────────────────────────────────────────────────────┐
│  (ETF)                                                  │
│  - code: string (PK)                                    │
│  - name: string                                         │
│  - expense_ratio, net_assets: float                     │
│  - close_price, return_1d/1w/1m, market_cap_change_1w   │
├─────────────────────────────────────────────────────────┤
│  (Stock)                                                │
│  - code: string (PK)                                    │
│  - name: string (KIS hts_kor_isnm)                      │
│  - is_etf: bool                                         │
├─────────────────────────────────────────────────────────┤
│  (Price)   date, open, high, low, close, volume, ...    │
│  (Company) name        (Tag) name        (User) user_id │
└─────────────────────────────────────────────────────────┘

Edges:
┌─────────────────────────────────────────────────────────┐
│  (ETF)-[:HOLDS {date, weight, shares}]->(Stock)         │
│  (ETF|Stock)-[:HAS_PRICE]->(Price)                      │
│  (ETF)-[:MANAGED_BY]->(Company)                         │
│  (ETF)-[:TAGGED]->(Tag)                                 │
│  (User)-[:WATCHES {added_at}]->(ETF)                    │
└─────────────────────────────────────────────────────────┘
```

상세는 [graph.md](graph.md) 참고.

### PostgreSQL (Relational) - 사용자/포트폴리오/가격 데이터

스키마 원본은 `docker/db/init/02_schema.sql`. 주요 테이블:

```sql
-- 사용자 (아이디/비밀번호 로그인)
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    last_notification_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 역할: roles(admin, member) + user_roles
-- 포트폴리오: portfolios, target_allocations, holdings, portfolio_snapshots
-- 가격 캐시: ticker_prices (ticker, date)
-- 수집 기록: collection_runs, KIS 토큰 캐시: kis_tokens, 개장일 캐시: market_calendar
-- 챗봇: chat_logs, code_examples (embedding vector(768))
```

즐겨찾기(워치리스트)는 RDB 테이블이 아니라 AGE `(User)-[:WATCHES]->(ETF)` 관계로 저장한다.

---

## API 설계

### 인증

```
GET  /api/auth/setup-status    # 최초 설치 필요 여부 {setup_required}
POST /api/auth/setup           # 최초 관리자 생성 (사용자 0명일 때만), JWT 발급
POST /api/auth/register        # 회원가입 (member), JWT 발급
POST /api/auth/login           # 로그인, JWT 발급
GET  /api/auth/me              # 내 정보 {id, username, name, is_admin}
```

> 이하 엔드포인트 목록은 초기 설계안이다. 현재 전체 API는 [api-schema.md](api-schema.md) 또는 Swagger(`/docs`) 참고.

### 종목 검색

```
GET /api/stocks/search?q={keyword}    # 종목 자동완성
GET /api/stocks/{code}/etfs           # 종목 보유 ETF 리스트
```

### ETF 조회

```
GET /api/etfs/search?q={keyword}              # ETF 자동완성
GET /api/etfs/{code}                          # ETF 상세
GET /api/etfs/{code}/holdings?date={date}     # 구성 종목
GET /api/etfs/{code}/changes?period={1m|3m|6m}# 포트폴리오 변화
GET /api/etfs/{code}/price?period={1w|1m|3m|1y}# 가격 (캔들)
```

### 워치리스트 (인증 필요)

```
GET    /api/watchlist           # 내 워치리스트 + 수익률
POST   /api/watchlist           # ETF 추가
DELETE /api/watchlist/{etf_code}# ETF 삭제
GET    /api/watchlist/changes   # 워치리스트 ETF 포트폴리오 변화
```

### AI 추천 (인증 필요)

```
GET /api/ai/recommendations     # 워치리스트 기반 종목 추천
```

---

## 핵심 Cypher 쿼리

```cypher
-- 1. 종목 역추적: 삼성전자를 담은 ETF
MATCH (e:ETF)-[h:HOLDS {date: $latest_date}]->(s:Stock {code: '005930'})
RETURN e.code, e.name, h.weight
ORDER BY h.weight DESC;

-- 2. ETF 포트폴리오 변화: 두 날짜의 HOLDS 스냅샷을 각각 조회해 애플리케이션에서 비교
--    (GraphService.get_etf_holdings_changes — added/removed/increased/decreased)
MATCH (e:ETF {code: $etf_code})-[h:HOLDS {date: $date}]->(s:Stock)
RETURN s.code, s.name, h.weight;
```

---

## 프로젝트 구조

```
ETFAtlas/
├── docs/                          # 상세 문서
│
├── frontend/                      # React + TS + Vite (nginx로 서빙)
│   ├── src/
│   │   ├── App.tsx                # 라우팅 (/setup 리다이렉트 가드 포함)
│   │   ├── app/                   # 페이지
│   │   │   ├── HomePage.tsx
│   │   │   ├── ETFDetailPage.tsx
│   │   │   ├── PortfolioPage.tsx, PortfolioDashboardPage.tsx
│   │   │   ├── WatchlistChangesPage.tsx
│   │   │   ├── SharedPortfoliosPage.tsx, SharedPortfolioDetailPage.tsx
│   │   │   ├── ChatPage.tsx, AdminPage.tsx
│   │   │   ├── LoginPage.tsx      # 로그인 / 회원가입 탭
│   │   │   └── SetupPage.tsx      # 최초 관리자 생성
│   │   ├── components/            # AccountForm, Header, ui/ (shadcn) 등
│   │   ├── hooks/                 # useAuth, useNotification 등
│   │   └── lib/                   # api.ts, auth.ts, PDF 내보내기
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py, config.py, database.py
│   │   ├── routers/               # auth, etfs, watchlist, portfolio, shared, tags, chat, notifications, admin
│   │   ├── models/                # SQLAlchemy 모델
│   │   ├── schemas/
│   │   ├── services/              # auth_service, graph_service, chat_service, embedding_service 등
│   │   ├── domain/
│   │   └── utils/                 # jwt.py, security.py(bcrypt), encryption.py
│   ├── tests/
│   └── requirements.txt
│
├── airflow/
│   ├── dags/                      # age_*, rdb_*, embed_code_examples, age_utils.py, kis_api_client.py, naver_client.py
│   └── requirements.txt
│
├── docker/
│   ├── airflow/Dockerfile         # apache/airflow:3.3.2-python3.14 + DAG 의존성
│   └── db/
│       ├── Dockerfile             # postgres:18 + AGE 1.8.0 + pgvector 0.8.6
│       └── init/
│           ├── 00_airflow_db.sql  # Airflow 메타데이터 DB 생성
│           ├── 01_extensions.sql  # age, vector, pg_trgm + etf_graph
│           ├── 02_schema.sql      # RDB 스키마
│           └── 03_seed_code_examples.sql
│
├── scripts/                       # graph_viewer 등 보조 스크립트
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Docker 이미지

### DB (PostgreSQL + AGE + pgvector)

```dockerfile
# docker/db/Dockerfile (요약)
FROM postgres:18-trixie

RUN apt-get update && apt-get install -y \
    build-essential git postgresql-server-dev-18 libreadline-dev zlib1g-dev flex bison

# Apache AGE
RUN git clone --branch release/PG18/1.8.0 --depth 1 https://github.com/apache/age.git /tmp/age \
    && cd /tmp/age && make install

# pgvector
RUN git clone --branch v0.8.6 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector && make && make install

COPY init/ /docker-entrypoint-initdb.d/
RUN echo "shared_preload_libraries = 'age'" >> /usr/share/postgresql/postgresql.conf.sample
```

```sql
-- docker/db/init/01_extensions.sql
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('etf_graph');
```

init 스크립트는 빈 볼륨으로 처음 기동할 때만 실행된다 (별도 마이그레이션 스크립트 없음).

### Backend / Airflow

| 이미지 | 베이스 |
|--------|--------|
| backend | `python:3.14-slim` |
| frontend | `node:24-alpine` 빌드 → `nginx:alpine` |
| airflow | `apache/airflow:3.3.2-python3.14` + `airflow/requirements.txt` (공식 constraints-3.3.2/constraints-3.14.txt 적용) |

---

## 배포 구조 (Docker)

### 포트 할당

| 서비스 | 외부 포트 | 내부 포트 | URL |
|--------|----------|----------|-----|
| Frontend | 9600 | 80 | http://localhost:9600 |
| Backend | 9601 | 8000 | http://localhost:9601 |
| PostgreSQL | 9602 | 5432 | localhost:9602 |
| Airflow (api-server) | 9603 | 8080 | http://localhost:9603 |

### 서비스 구성 (docker-compose.yml)

| 서비스 | 설명 |
|--------|------|
| `db` | PostgreSQL 18 + AGE + pgvector. 앱 DB `etf_atlas`와 Airflow 메타데이터 DB `airflow`를 함께 호스팅 |
| `backend` | FastAPI (uvicorn) |
| `frontend` | nginx 정적 서빙 |
| `airflow-init` | `airflow db migrate` + SimpleAuthManager 비밀번호 파일 생성 (1회성) |
| `airflow-apiserver` | Airflow UI/API (`api-server`, LocalExecutor) |
| `airflow-scheduler` | 스케줄러 |
| `airflow-dag-processor` | DAG 파싱 |

Airflow UI 로그인은 SimpleAuthManager로 `AIRFLOW_USER`/`AIRFLOW_PASSWORD` 계정을 사용한다.

---

## 환경 변수

`.env.example` 참고. 주요 항목:

```env
# Backend
JWT_SECRET=                 # python -c "import secrets; print(secrets.token_hex(32))"
ENCRYPTION_KEY=             # 32-byte hex (AES-256-GCM), 한 번 정하면 변경 금지

# AI (LiteLLM 프록시, OpenAI 호환 API)
LLM_API_BASE=http://localhost:4000
LLM_API_KEY=                           # 채팅 모델 키
LLM_MODEL=qwen38-27b
EMBEDDING_API_BASE=http://localhost:4000
EMBEDDING_API_KEY=                     # 임베딩 키 (채팅 모델과 다름)
EMBEDDING_MODEL=embedding-gemma-300m   # 768차원

# Airflow
AIRFLOW_USER=admin
AIRFLOW_PASSWORD=admin
AIRFLOW_FERNET_KEY=
AIRFLOW_SECRET_KEY=
AIRFLOW_JWT_SECRET=

# 데이터 소스
KIS_APP_KEY=                # 한국투자증권 KIS Open API — ETF 현재가, ETF/주식 일봉, 구성종목, 영업일, 휴장일
KIS_APP_SECRET=
KIS_BASE_URL=               # 기본값 https://openapi.koreainvestment.com:9443

DISCORD_WEBHOOK_URL=        # (선택) 수집 완료 알림
```

---

## 개발 환경 실행

```bash
# 전체 서비스 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f

# 개별 서비스 재시작
docker-compose restart backend

# 종료
docker-compose down
```

### 접속 URL

| 서비스 | URL |
|--------|-----|
| 프론트엔드 | http://localhost:9600 |
| API 문서 (Swagger) | http://localhost:9601/docs |
| Airflow 대시보드 | http://localhost:9603 |
