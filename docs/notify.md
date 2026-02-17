# 비중 변화 알림 서비스

## 개요

즐겨찾기 ETF의 보유종목 비중 변화를 **인앱 SSE** + **디스코드 웹훅**으로 알림.

## 아키텍처

```
DAG (평일 08:00)
  └─ HOLDS 수집 완료
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

-- 유저별 마지막 알림 확인 시각
ALTER TABLE users ADD COLUMN last_notification_checked_at TIMESTAMP;
```

### AGE

```cypher
-- User 노드에 role 프로퍼티
(User {user_id: 1, role: 'admin'})   -- 첫 가입자
(User {user_id: 2, role: 'member'})  -- 이후 가입자
```

## 알림 채널

| 채널 | 대상 | ETF 소스 | 트리거 | 임계값 |
|------|------|----------|--------|--------|
| 인앱 SSE | 로그인 유저 본인 | 본인 즐겨찾기 | pg_notify → SSE push | - |
| 디스코드 | admin 유저만 | admin 즐겨찾기 | DAG 수집 완료 | 3%p 초과 |

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

## 유저 역할 (AGE User.role)

- `GraphService.get_user_role(user_id)` / `set_user_role(user_id, role)` / `get_admin_user_ids()`
- `AuthService.get_or_create_user` — 첫 유저 `admin`, 이후 `member`
- 디스코드 알림은 `role='admin'` 유저의 WATCHES만 대상

## 환경 변수

| 변수 | 설명 | 필수 |
|------|------|------|
| `DISCORD_WEBHOOK_URL` | 디스코드 웹훅 URL | 선택 (미설정 시 디스코드 스킵) |

## 변경된 파일

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
