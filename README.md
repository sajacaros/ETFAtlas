# ETF Atlas

한국 ETF 시장을 탐색하고, 포트폴리오를 관리하며, AI 챗봇과 대화할 수 있는 올인원 ETF 분석 플랫폼입니다.

## 주요 기능

### ETF 탐색
- **ETF 검색** - 이름/종목코드로 ETF 검색 (pg_trgm 기반 유사 검색)
- **Top ETF** - 시가총액, 수익률 기준 정렬
- **ETF 상세** - 구성종목, 가격 차트(365일), 카테고리 태그
- **구성종목 변화 추적** - 1일/1주/1개월 비중 변화 감지
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
- ETF 관련 질문 응답 (tool-calling 기반 에이전트)
- 스트리밍 응답 지원

### 알림
- PostgreSQL LISTEN/NOTIFY 기반 실시간 SSE 알림
- 구성종목 변화 감지 시 자동 알림

### 데이터 파이프라인 (Airflow)
- **ETF 유니버스 수집** - KRX API 기반 일별 자동 수집 (순자산 500억 이상)
- **구성종목/가격 수집** - ETF 및 개별 주식 OHLCV 데이터
- **포트폴리오 스냅샷** - 장 마감 후 일별 평가금액 자동 기록
- **실시간 가격** - 장중 10분 간격 가격 업데이트
- **자동 태깅** - GPT-4.1-mini 기반 ETF 카테고리 자동 분류

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| Frontend | React 18, TypeScript, Vite, TailwindCSS, shadcn/ui, Recharts |
| Backend | FastAPI, SQLAlchemy 2.0 (async), Pydantic |
| Database | PostgreSQL + Apache AGE (그래프) + pgvector + pg_trgm |
| Pipeline | Apache Airflow |
| Auth | Google OAuth 2.0 + JWT |
| AI | Anthropic Claude, OpenAI GPT, smolagents |

## 실행 방법

### 사전 요구사항

- Docker & Docker Compose
- Google OAuth 클라이언트 ID ([Google Cloud Console](https://console.cloud.google.com)에서 발급)

### 1. 환경변수 설정

```bash
cp .env.example .env
```

`.env` 파일을 편집하여 필수 값을 입력합니다:

| 변수 | 설명 | 필수 |
|------|------|------|
| `GOOGLE_CLIENT_ID` | Google OAuth 클라이언트 ID | O |
| `GOOGLE_CLIENT_SECRET` | Google OAuth 클라이언트 시크릿 | O |
| `VITE_GOOGLE_CLIENT_ID` | 프론트엔드용 Google 클라이언트 ID (위와 동일 값) | O |
| `JWT_SECRET` | JWT 서명 키 (임의 문자열) | O |
| `OPENAI_API_KEY` | ETF 자동 태깅용 | O |
| `ANTHROPIC_API_KEY` | AI 챗봇용 | O |
| `KRX_AUTH_KEY` | KRX Open API 인증키 ([발급](https://openapi.krx.co.kr)) | - |

### 2. 서비스 실행

```bash
docker compose up -d
```

### 3. 접속

| 서비스 | URL |
|--------|-----|
| Frontend | http://localhost:9600 |
| Backend API Docs | http://localhost:9601/docs |
| Airflow | http://localhost:9603 (admin / admin) |

### 4. 초기 데이터 수집

서비스 시작 후 Airflow 웹 UI에서 아래 DAG를 순서대로 실행합니다:

1. **`age_sync_universe`** - ETF 유니버스 및 가격 데이터 수집 (첫 실행 시 최근 45일 백필)
2. **`etf_rdb_etl`** - RDB 메타데이터 동기화
3. **`portfolio_snapshot`** - 포트폴리오 스냅샷 생성 (포트폴리오 생성 후)

이후에는 각 DAG가 평일 스케줄에 따라 자동 실행됩니다.

### 백엔드 코드 수정 시

백엔드는 볼륨 마운트가 없으므로 코드 변경 후 재빌드가 필요합니다:

```bash
docker compose up -d --build backend
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
│   └── app/
│       ├── routers/   # API 라우터 (auth, etfs, portfolios, ...)
│       ├── models/    # SQLAlchemy 모델
│       └── services/  # 비즈니스 로직
├── airflow/           # 데이터 파이프라인
│   └── dags/          # Airflow DAG 정의
├── docker/            # DB 초기화 스크립트
│   └── db/init/       # SQL 스키마 및 익스텐션 설정
├── docs/              # 아키텍처 문서
├── docker-compose.yml
└── .env.example
```
