# 비중 변화 알림 서비스

## 개요

액티브 ETF 전체의 보유종목 비중 변화(이전 공시일 대비)를 **인앱 SSE** + **디스코드 웹훅**으로 알림.
Airflow가 수집 후 한 번 계산해 `weight_changes` 테이블에 저장하고, 웹 화면·빨간 점·디스코드가 모두 이 결과를 읽는다.

## 아키텍처

```
DAG age_sync_universe (매일 08:50·16:30, 구성종목은 개장일에만 그날 공시분)
  └─ HOLDS 수집 완료 (KIS API, 최근 거래일)
  └─ sync_weight_changes — 액티브 ETF 비중 변화 계산 → weight_changes 저장
  └─ record_collection — collection_runs INSERT + NOTIFY new_collection (계산 실패해도 실행)
  └─ notify_discord — weight_changes 중 기준값 초과를 디스코드로 발송 (없으면 "변화 없음")

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
| 인앱 (빨간 점 + `/changes` 페이지) | 모든 회원 (같은 내용) | 액티브 ETF 전체 | pg_notify → SSE push | 기준값 초과 (이전 공시일 대비) |
| 디스코드 | 웹훅 채널 | 액티브 ETF 전체 | DAG 수집 완료 | 기준값 초과 (기본 3%p, 신규편입 2%p, 이전 공시일 대비) |
| 디스코드 (주간 매수 의견) | 웹훅 채널 | ETF가 담은 주식 전체 | 백엔드, 토요일 07:00 | '사 볼 만하다' 상위 10개 — [weekly-opinion.md](weekly-opinion.md) |

기준값은 관리자 페이지 디스코드 탭에서 설정하며 웹과 디스코드가 같은 값을 쓴다. 신규편입은 따로 둔 신규편입 기준값(기본 2%p)을 쓴다. `weight_changes`에는 변화가 있는 종목을 크기와 상관없이 모두 저장하고 기준값은 읽을 때 적용한다.

## Backend API

| 엔드포인트 | 메서드 | 인증 | 설명 |
|---|---|---|---|
| `/api/notifications/status` | GET | 세션 쿠키 | 새 알림 유무 (`has_new`, `latest_collected_at`) |
| `/api/notifications/check` | POST | 세션 쿠키 | `last_notification_checked_at` 갱신 |
| `/api/notifications/stream` | GET | 세션 쿠키 | SSE 스트림. pg_notify LISTEN으로 즉시 수신 |

SSE도 같은 출처라 `EventSource`가 세션 쿠키를 자동으로 보낸다. 스트림이 열려 있는 동안 커넥션 풀을 붙잡지 않도록 인증할 때만 DB 세션을 연다.

### 디스코드 알림 설정 (관리자)

관리자 페이지 「알림」 탭에서 켜기/끄기, 웹훅 주소, 비중 변화 기준값(%p), 신규편입 기준값(%p)을 바꾼다. RDB `discord_settings`(id=1 한 행)에 저장되고, DAG가 발송할 때마다 읽으므로 재시작 없이 다음 수집부터 반영된다.

| 엔드포인트 | 메서드 | 설명 |
|---|---|---|
| `/api/admin/settings/discord` | GET | 설정 조회. 웹훅 주소는 끝 4자리만 보인다 (`webhook_url_masked`) |
| `/api/admin/settings/discord` | PUT | `{enabled, threshold, added_threshold?, rise_threshold?, webhook_url?}` 저장. `added_threshold`·`rise_threshold` 생략 시 기존 값 유지. `webhook_url` 생략 시 기존 주소 유지, `""`이면 삭제 |
| `/api/admin/settings/discord/test` | POST | 저장된 주소로 테스트 메시지 발송 |

- 웹훅 주소는 `https://discord.com/api/webhooks/`(또는 `discordapp.com`)로 시작해야 한다.
- 웹에서 저장한 주소가 없으면 환경변수 `DISCORD_WEBHOOK_URL`을 쓴다.
- 디스코드 메시지는 2,000자 제한이 있어 길면 ETF 단위로 나눠 여러 번 보낸다(헤더에 `(1/3)` 표시). ETF 하나가 2,000자를 넘으면 종목 줄 단위로 나누고 이어지는 조각에 `(계속)`을 붙인다. 429(rate limit)는 `retry_after`만큼 기다렸다 한 번 재시도한다.

## DAG 태스크

`sync_universe_age.py`:

1. `sync_weight_changes` → `compute_weight_changes()` — 아직 계산하지 않은 HOLDS 날짜와 최근 5개 날짜를 계산해 `weight_changes`에 저장(날짜별 DELETE+INSERT), `weight_change_dates`에 완료 표시. 첫 실행이면 과거 전체를 채운다. 이전 HOLDS가 없는 ETF는 비교하지 않는다.
2. `record_collection` → `record_collection_run(date_str)` — `collection_runs` INSERT + `NOTIFY new_collection`. `trigger_rule='all_done'`이라 비중변화 계산이 실패해도 기록한다.
3. `notify_discord` → `send_discord_notification(date_str)` — 계산이 성공했을 때만 실행.

의존관계: `sync_holdings → sync_weight_changes → [record_collection, notify_discord] → end`

### 중복 방지

- `collection_runs.collected_at`에 UNIQUE 제약 → `ON CONFLICT DO NOTHING`, 새로 기록됐을 때만 NOTIFY
- 디스코드는 `discord_notification_logs`에 그 날짜의 성공(`sent`) 기록이 있으면 건너뛴다. 기준값을 넘는 변화가 없으면 "변화 없음" 메시지를 한 번 보내고(`items` 빈 배열로 기록), 그 뒤 실행(16:30 재수집)에서 변화가 생기면 변화 알림을 다시 보낸다
- 발송 실패는 이력에 `failed`로 남기고 예외를 올려 Airflow 재시도(3회, 5분 간격)로 다시 보낸다

## Frontend

### useNotification 훅 (`hooks/useNotification.tsx`)

- `NotificationProvider` — AuthProvider 내부에 래핑
- 초기 로드: `GET /status`로 `has_new` 확인
- SSE: `EventSource`로 `/stream` 연결, 이벤트 수신 시 `hasNew = true`
- `markChecked()` — `POST /check` 호출 + `hasNew = false`

### UI

- **Header**: Bell 아이콘에 `hasNew` 시 빨간 dot 뱃지 (`w-2 h-2 bg-red-500 rounded-full`)
- **ActiveChangesPage** (`/changes`): 페이지 마운트 시 `markChecked()` 호출 → 뱃지 제거

## 유저 역할 (RDB user_roles)

- 역할은 AGE `User` 노드가 아니라 RDB `roles` / `user_roles`에 저장한다.
- `POST /api/auth/setup`(최초 설치)으로 만든 계정이 `admin`, `POST /api/auth/register`로 가입한 계정은 `member`.
- `auth_service.is_admin(db, user_id)`로 확인.
- 알림 대상은 역할과 상관없이 액티브 ETF 전체다(ETF.active, KIS 분류로 매일 갱신).
- HOLDS 날짜는 구성종목 공시일(수집한 영업일)이고, 비교 기준은 ETF별 이전 HOLDS 날짜다. 공시일의 변화는 직전 영업일 장중 매매를 반영한다. KIS API는 과거 구성종목을 제공하지 않으므로 HOLDS 수집 이틀째부터 비교 대상이 생긴다.

## 환경 변수

| 변수 | 설명 | 필수 |
|------|------|------|
| `DISCORD_WEBHOOK_URL` | 디스코드 웹훅 URL. 관리자 페이지에서 저장한 주소가 있으면 그것이 우선 | 선택 (둘 다 없으면 디스코드 스킵) |

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
