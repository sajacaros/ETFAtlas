# ETF Atlas 아키텍처

## 기술 스택

| 영역 | 기술 |
|------|------|
| **Frontend** | React, TypeScript, shadcn/ui, Recharts |
| **Backend** | FastAPI, Pydantic, authlib (Google OAuth) |
| **Database** | PostgreSQL + Apache AGE (Graph) + pgvector |
| **Data Pipeline** | Airflow, pykrx |
| **AI** | smolagents |
| **Auth** | Google OAuth2 + JWT |

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
│  │  shadcn/ui   │     │              │     │   (Daily 08:00)      │    │
│  │              │     │              │     │                      │    │
│  └──────────────┘     └──────┬───────┘     └──────────┬───────────┘    │
│                              │                        │                 │
│         ┌────────────────────┼────────────────────────┘                 │
│         │                    │                                          │
│         v                    v                                          │
│  ┌─────────────┐    ┌────────────────────────────────────────┐         │
│  │   Google    │    │              PostgreSQL                 │         │
│  │   OAuth     │    │  ┌────────────────┬─────────────────┐  │         │
│  └─────────────┘    │  │  Apache AGE    │   Relational    │  │         │
│                     │  │  (ETF/Stock)   │   (User/Auth)   │  │         │
│                     │  └────────────────┴─────────────────┘  │         │
│                     └────────────────────────────────────────┘         │
│                              ^                                          │
│                              │                                          │
│                     ┌────────┴───────┐                                 │
│                     │   smolagents   │                                 │
│                     │   (AI Agent)   │                                 │
│                     └────────────────┘                                 │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 인증 (Google OAuth)

### 플로우

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  사용자  │     │ Frontend │     │ Backend  │     │  Google  │
└────┬─────┘     └────┬─────┘     └────┬─────┘     └────┬─────┘
     │                │                │                │
     │ 1. 로그인 클릭  │                │                │
     │───────────────>│                │                │
     │                │ 2. /auth/google│                │
     │                │───────────────>│                │
     │                │                │ 3. redirect    │
     │                │                │───────────────>│
     │                │                │                │
     │<───────────────────────────────────────────────────
     │                4. Google 로그인 페이지            │
     │                                                  │
     │                5. 인증 완료, code 전달            │
     │─────────────────────────────────────────────────>│
     │                │                │                │
     │                │                │<───────────────│
     │                │                │ 6. code + user │
     │                │                │    info        │
     │                │                │                │
     │                │ 7. JWT 발급    │                │
     │                │<───────────────│                │
     │                │                │                │
     │ 8. 로그인 완료 │                │                │
     │<───────────────│                │                │
     │                │                │                │
```

### 구현 요소

| 요소 | 설명 |
|------|------|
| `authlib` | Google OAuth2 클라이언트 |
| JWT | access token (1시간) + refresh token (7일) |
| users 테이블 | Google ID, email, name 저장 |

### 로드맵

```
v1: Google 로그인
v2: + 카카오
v3: + 네이버, 애플
```

---

## 데이터 파이프라인 (Airflow)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Daily ETL DAG (08:00 KST)                                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐              │
│  │  Task 1     │     │  Task 2     │     │  Task 3     │              │
│  │  ETF 목록   │────>│  구성종목   │────>│  가격 수집  │              │
│  │  수집       │     │  수집       │     │             │              │
│  │  (pykrx)    │     │  (pykrx)    │     │  (pykrx)    │              │
│  └─────────────┘     └─────────────┘     └──────┬──────┘              │
│                                                  │                      │
│                                                  v                      │
│                                          ┌─────────────┐               │
│                                          │  Task 4     │               │
│                                          │  스냅샷     │               │
│                                          │  저장 (AGE) │               │
│                                          └──────┬──────┘               │
│                                                  │                      │
│                                                  v                      │
│                                          ┌─────────────┐               │
│                                          │  Task 5     │               │
│                                          │  변화 감지  │               │
│                                          └─────────────┘               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘

pykrx 함수:
├── get_etf_ticker_list()            # ETF 목록
├── get_etf_portfolio_deposit_file() # 구성종목 (PDF)
└── get_etf_ohlcv_by_date()          # 가격 데이터

변화 감지 로직:
├── 신규 편입: 어제 없던 종목이 오늘 있음
├── 완전 제외: 어제 있던 종목이 오늘 없음
└── 비중 5%p 이상 변화: |오늘 비중 - 어제 비중| >= 5
```

---

## 데이터 모델

### Apache AGE (Graph) - ETF/종목 데이터

```
Nodes:
┌─────────────────────────────────────────────────────────┐
│  (ETF)                                                  │
│  - code: string (PK)                                    │
│  - name: string                                         │
│  - type: "active" | "passive"                           │
│  - manager: string                                      │
│  - inception_date: date                                 │
├─────────────────────────────────────────────────────────┤
│  (Stock)                                                │
│  - code: string (PK)                                    │
│  - name: string                                         │
│  - sector: string                                       │
├─────────────────────────────────────────────────────────┤
│  (Change)                                               │
│  - id: string (PK)                                      │
│  - date: date                                           │
│  - type: "NEW" | "REMOVED" | "WEIGHT_CHANGE"            │
│  - stock_code: string                                   │
│  - stock_name: string                                   │
│  - before_weight: float (nullable)                      │
│  - after_weight: float (nullable)                       │
└─────────────────────────────────────────────────────────┘

Edges:
┌─────────────────────────────────────────────────────────┐
│  (ETF)-[:HOLDS {date, weight, shares}]->(Stock)         │
│  (ETF)-[:HAS_CHANGE]->(Change)                          │
└─────────────────────────────────────────────────────────┘
```

### PostgreSQL (Relational) - 사용자/인증/가격 데이터

```sql
-- 사용자
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_id VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

-- 워치리스트
CREATE TABLE watchlist (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    etf_code VARCHAR(20) NOT NULL,
    added_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, etf_code)
);

-- ETF 가격 (시계열)
CREATE TABLE etf_price (
    etf_code VARCHAR(20),
    date DATE,
    open INT,
    high INT,
    low INT,
    close INT,
    volume BIGINT,
    PRIMARY KEY (etf_code, date)
);

-- 리프레시 토큰
CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(500) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## API 설계

### 인증

```
POST /auth/google              # Google OAuth 시작
GET  /auth/google/callback     # Google 콜백, JWT 발급
POST /auth/refresh             # 토큰 갱신
POST /auth/logout              # 로그아웃
GET  /auth/me                  # 내 정보
```

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
RETURN e.code, e.name, e.type, h.weight
ORDER BY h.weight DESC;

-- 2. ETF 포트폴리오 변화 조회
MATCH (e:ETF {code: $etf_code})-[:HAS_CHANGE]->(c:Change)
WHERE c.date >= $start_date
RETURN c.type, c.stock_code, c.stock_name,
       c.before_weight, c.after_weight, c.date
ORDER BY c.date DESC;

-- 3. 워치리스트 ETF들의 공통 신규편입 종목
MATCH (e:ETF)-[:HAS_CHANGE]->(c:Change {type: 'NEW'})
WHERE e.code IN $watchlist_codes AND c.date >= $start_date
RETURN c.stock_code, c.stock_name, count(*) as etf_count
ORDER BY etf_count DESC;
```

---

## 프로젝트 구조

```
etf-atlas/
├── docs/
│   ├── v1-spec.md
│   ├── architecture.md
│   └── ui-design.md
│
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx              # 메인 (종목 검색)
│   │   │   ├── etf/[code]/page.tsx   # ETF 상세
│   │   │   ├── watchlist/page.tsx    # 워치리스트
│   │   │   ├── ai/page.tsx           # AI 추천
│   │   │   └── login/page.tsx        # 로그인
│   │   ├── components/
│   │   │   ├── auth/
│   │   │   │   └── GoogleLoginButton.tsx
│   │   │   ├── search/
│   │   │   ├── etf/
│   │   │   ├── watchlist/
│   │   │   └── ai/
│   │   ├── hooks/
│   │   │   ├── useAuth.ts
│   │   │   └── ...
│   │   └── lib/
│   │       ├── api.ts
│   │       └── auth.ts
│   └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── routers/
│   │   │   ├── auth.py
│   │   │   ├── stocks.py
│   │   │   ├── etfs.py
│   │   │   ├── watchlist.py
│   │   │   └── ai.py
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   └── watchlist.py
│   │   ├── services/
│   │   │   ├── auth_service.py
│   │   │   ├── graph_service.py
│   │   │   └── etf_service.py
│   │   ├── agents/
│   │   │   └── recommender.py
│   │   └── utils/
│   │       └── jwt.py
│   └── requirements.txt
│
├── airflow/
│   └── dags/
│       └── etf_daily_etl.py
│
├── docker/
│   └── db/
│       ├── Dockerfile
│       └── init/
│           └── 01_extensions.sql
│
├── docker-compose.yml
├── .env
└── README.md
```

---

## Docker 이미지

### DB (PostgreSQL + AGE + pgvector)

```dockerfile
# docker/db/Dockerfile
FROM apache/age:latest

# pgvector 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    postgresql-server-dev-16 \
    && rm -rf /var/lib/apt/lists/*

RUN cd /tmp \
    && git clone --branch v0.7.0 https://github.com/pgvector/pgvector.git \
    && cd pgvector \
    && make \
    && make install

# 정리
RUN apt-get remove -y build-essential git postgresql-server-dev-16 \
    && apt-get autoremove -y
```

```sql
-- docker/db/init/01_extensions.sql
-- 확장 활성화
CREATE EXTENSION IF NOT EXISTS age;
CREATE EXTENSION IF NOT EXISTS vector;

-- AGE 그래프 생성
LOAD 'age';
SET search_path = ag_catalog, "$user", public;
SELECT create_graph('etf_graph');
```

---

## 배포 구조 (Docker)

### 포트 할당

| 서비스 | 외부 포트 | 내부 포트 | URL |
|--------|----------|----------|-----|
| Frontend | 9600 | 3000 | http://localhost:9600 |
| Backend | 9601 | 8000 | http://localhost:9601 |
| PostgreSQL | 9602 | 5432 | localhost:9602 |
| Airflow | 9603 | 8080 | http://localhost:9603 |

### HTTPS 요구사항

| 환경 | URL | HTTPS |
|------|-----|-------|
| 개발 (localhost) | `http://localhost:96xx` | 불필요 (Google이 localhost 예외 허용) |
| 프로덕션 | 실제 도메인 | 필수 |

### docker-compose.yml

```yaml
services:
  frontend:
    build: ./frontend
    ports:
      - "9600:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:9601
      - NEXT_PUBLIC_GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
    depends_on:
      - backend

  backend:
    build: ./backend
    ports:
      - "9601:8000"
    environment:
      - DATABASE_URL=postgresql://etfatlas:etfatlas@db:5432/etfatlas
      - GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
      - GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
      - GOOGLE_REDIRECT_URI=http://localhost:9601/auth/google/callback
      - JWT_SECRET=${JWT_SECRET}
      - FRONTEND_URL=http://localhost:9600
    depends_on:
      - db

  db:
    build: ./docker/db
    ports:
      - "9602:5432"
    environment:
      - POSTGRES_USER=etfatlas
      - POSTGRES_PASSWORD=etfatlas
      - POSTGRES_DB=etfatlas
    volumes:
      - etfatlas_pgdata:/var/lib/postgresql/data
      - ./docker/db/init:/docker-entrypoint-initdb.d

  airflow:
    image: apache/airflow:latest
    ports:
      - "9603:8080"
    environment:
      - AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=postgresql://etfatlas:etfatlas@db:5432/etfatlas
      - AIRFLOW__CORE__EXECUTOR=LocalExecutor
      - AIRFLOW__CORE__LOAD_EXAMPLES=false
    volumes:
      - ./airflow/dags:/opt/airflow/dags
    depends_on:
      - db

volumes:
  etfatlas_pgdata:
```

---

## 환경 변수

```env
# .env
GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxx
JWT_SECRET=your-secret-key

# Google OAuth 설정 시 Authorized redirect URIs에 추가:
# http://localhost:9601/auth/google/callback
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
