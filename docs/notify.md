# 비중 변화 알림 서비스

## 개요

즐겨찾기 ETF의 보유종목 비중 변화를 **인앱 SSE** + **디스코드 웹훅**으로 알림.

## 아키텍처

```
DAG age_sync_universe (화~토 08:30)
  └─ HOLDS 수집 완료 (KIS API, 최근 거래일)
  └─ collection_runs INSERT + NOTIFY new_collection (pg_notify)
  └─ Discord 웹훅 발송 (admin 즐겨찾기 기반)

Backend
  └─ GET /api/notifications/stream — LISTEN new_collection (SSE)
  └─ GET /api/notifications/status — 새 알림 유무 조회
  └─ POST /api/notifications/check — 알림 확인 처리

Frontend
  └─ useNotification 훅 — SSE 연결 + 상태 관리
  └─ Header Bell 아이콘 — 빨간 dot 뱃지
  └─ 비중변화 페이지 진입 시 markChecked → 뱃지 제거
```

## DB 변경

### RDB

```sql
-- 수집 완료 기록
CREATE TABLE collection_runs (
    id SERIAL PRIMARY KEY,
    collected_at DATE NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 유저별 마지막 알림 확인 시각 (users 테이블 컬럼)
last_notification_checked_at TIMESTAMP

-- 역할: roles(admin, member) + user_roles
```

현재는 모두 `docker/db/init/02_schema.sql`에 포함되어 있다.

## 알림 채널

| 채널 | 대상 | ETF 소스 | 트리거 | 임계값 |
|------|------|----------|--------|--------|
| 인앱 SSE | 로그인 유저 본인 | 본인 즐겨찾기 | pg_notify → SSE push | - |
| 디스코드 | admin 유저만 | admin 즐겨찾기 | DAG 수집 완료 | 3%p 초과 (약 1주 전 HOLDS 대비) |

## Backend API

| 엔드포인트 | 메서드 | 인증 | 설명 |
|---|---|---|---|
| `/api/notifications/status` | GET | Bearer token | 새 알림 유무 (`has_new`, `latest_collected_at`) |
| `/api/notifications/check` | POST | Bearer token | `last_notification_checked_at` 갱신 |
| `/api/notifications/stream` | GET | query param `token` | SSE 스트림. pg_notify LISTEN으로 즉시 수신 |

SSE는 `EventSource`가 Authorization 헤더를 지원하지 않으므로 query param으로 토큰 전달.

## DAG 태스크

`sync_universe_age.py`의 `record_and_notify` 태스크:

1. `record_collection_run(date_str)` — `collection_runs` INSERT + `NOTIFY new_collection`
2. `send_discord_notification(date_str)` — admin WATCHES 기반 비중변화 요약 발송

의존관계: `sync_holdings → [sync_stock_prices, record_and_notify] → end`

### 중복 방지

- `collection_runs.collected_at`에 UNIQUE 제약 → `ON CONFLICT DO NOTHING`
- `rowcount > 0`일 때만 NOTIFY 발행 + 디스코드 발송
- 수동 트리거/Airflow retry 시 같은 날짜면 알림 스킵

## Frontend

### useNotification 훅 (`hooks/useNotification.tsx`)

- `NotificationProvider` — AuthProvider 내부에 래핑
- 초기 로드: `GET /status`로 `has_new` 확인
- SSE: `EventSource`로 `/stream` 연결, 이벤트 수신 시 `hasNew = true`
- `markChecked()` — `POST /check` 호출 + `hasNew = false`

### UI

- **Header**: Bell 아이콘에 `hasNew` 시 빨간 dot 뱃지 (`w-2 h-2 bg-red-500 rounded-full`)
- **WatchlistChangesPage**: 페이지 마운트 시 `markChecked()` 호출 → 뱃지 제거

## 유저 역할 (RDB user_roles)

- 역할은 AGE `User` 노드가 아니라 RDB `roles` / `user_roles`에 저장한다.
- `POST /api/auth/setup`(최초 설치)으로 만든 계정이 `admin`, `POST /api/auth/register`로 가입한 계정은 `member`.
- `auth_service.is_admin(db, user_id)`로 확인.
- 디스코드 알림은 `send_discord_notification`이 `user_roles`에서 admin user_id를 조회한 뒤, 해당 유저의 AGE WATCHES만 대상으로 한다.
- 비교 기준은 약 1주 전 HOLDS 날짜이며, KIS API는 과거 구성종목을 제공하지 않으므로 HOLDS 수집 시작 후 1주가 지나야 비교 대상이 생긴다.

## 환경 변수

| 변수 | 설명 | 필수 |
|------|------|------|
| `DISCORD_WEBHOOK_URL` | 디스코드 웹훅 URL | 선택 (미설정 시 디스코드 스킵) |

## 변경된 파일

> 알림 기능 도입 당시 기준 기록이다. 이후 역할 저장 위치는 RDB `user_roles`로 바뀌었고, DB 초기화 스크립트는 `02_schema.sql`로 통합되었다.

### Backend
- `models/collection_run.py` — CollectionRun ORM
- `models/user.py` — `last_notification_checked_at` 컬럼
- `routers/notifications.py` — status/check/stream 엔드포인트
- `services/graph_service.py` — User role 메서드 + `_get_holdings_at` 반환값 변경
- `services/auth_service.py` — 가입 시 role 설정
- `main.py` — notifications 라우터 등록

### Frontend
- `hooks/useNotification.tsx` — 알림 컨텍스트 + SSE
- `lib/api.ts` — notificationApi
- `App.tsx` — NotificationProvider
- `components/Header.tsx` — Bell 뱃지
- `app/WatchlistChangesPage.tsx` — markChecked

### Airflow
- `age_utils.py` — `record_collection_run`, `send_discord_notification` 추가. `detect_changes_for_dates`, `_compare_holdings` 제거
- `sync_universe_age.py` — `record_and_notify` 태스크로 교체
- `backfill_age.py` — `backfill_changes` 태스크 제거

### DB
- `docker/db/init/01_extensions.sql` — `collection_runs` 테이블, `users` 컬럼 추가
