# 비중 변화 알림 서비스 설계

## 개요

즐겨찾기 ETF의 보유종목 비중 변화를 인앱(SSE) + 디스코드로 알림.

## 핵심 결정사항

- **데이터 소스**: 기존 HOLDS 비교 로직 재사용 (Change 노드 미사용, 제거)
- **인앱 알림**: SSE (Server-Sent Events) — 확장 가능한 실시간 채널
- **디스코드 알림**: admin 유저의 즐겨찾기 기반, DAG 태스크에서 웹훅 발송
- **새 알림 판단**: `last_notification_checked_at` vs `collection_runs.collected_at`
- **유저 역할**: AGE User 노드에 `role` 프로퍼티 (`admin`/`member`)
- **임계값**: 3%p 초과 (비중변화 페이지와 동일)

## 전체 흐름

```
DAG(08:00 평일)
  → HOLDS 수집 완료
  → collection_runs 테이블에 INSERT
  → 디스코드 웹훅 발송 (admin 즐겨찾기 기반 비중변화 요약)

Backend SSE (/api/notifications/stream)
  → 30초 폴링으로 collection_runs 확인
  → 유저의 last_notification_checked_at보다 새 수집이 있으면
  → SSE 이벤트 push

Frontend
  → SSE 수신 → 헤더 Bell 뱃지 + 토스트
  → 비중변화 페이지 진입 시 last_notification_checked_at 갱신 → 뱃지 제거
```

## DB 변경

### RDB

```sql
-- 새 테이블: DAG 수집 완료 기록
CREATE TABLE collection_runs (
    id SERIAL PRIMARY KEY,
    collected_at DATE NOT NULL UNIQUE,  -- 수집 대상 날짜
    created_at TIMESTAMP DEFAULT NOW()  -- 실행 완료 시각
);

-- users 테이블에 컬럼 추가
ALTER TABLE users ADD COLUMN last_notification_checked_at TIMESTAMP;
```

### AGE

```cypher
-- User 노드에 role 프로퍼티 추가
-- 첫 가입자: admin, 이후: member
(User {user_id: 1, role: 'admin'})
(User {user_id: 2, role: 'member'})
```

## Backend API

| 엔드포인트 | 메서드 | 역할 |
|---|---|---|
| `/api/notifications/stream` | GET | SSE 스트림. 로그인 유저별 새 알림 감지 시 이벤트 push |
| `/api/notifications/check` | POST | `last_notification_checked_at` 갱신 (비중변화 페이지 진입 시) |
| `/api/notifications/status` | GET | 새 알림 유무 반환 (초기 로드용, SSE 연결 전 상태 확인) |

## 디스코드 알림

- DAG 마지막 태스크로 실행
- `role='admin'` 유저의 AGE WATCHES 조회
- 각 ETF별 `get_etf_holdings_changes` 호출 (기존 로직)
- 3%p 초과 변화만 요약하여 디스코드 웹훅 발송
- `.env`에 `DISCORD_WEBHOOK_URL` 설정

## Change 노드 정리

- `age_utils.py`: `detect_changes_for_dates()`, `_compare_holdings()`, `_query_holdings()` 제거
- `sync_universe_age.py`: `detect_portfolio_changes` 태스크 제거
- `backfill_age.py`: `detect_changes_for_dates()` 호출 제거
- AGE 기존 Change 노드: 유지 (별도 마이그레이션으로 삭제)

## Frontend

- 헤더 Bell 아이콘: SSE 연결, 새 알림 시 뱃지 표시
- 비중변화 페이지 진입 시 `POST /notifications/check` 호출
- 페이지 최초 로드 시 `GET /notifications/status`로 초기 상태 확인
- SSE 이벤트 수신 시 토스트 알림 표시

## 유저 역할 관리

- 회원가입 시: AGE User 노드 생성할 때 `role` 프로퍼티 설정
- 첫 번째 유저(기존 유저 없을 때): `role: 'admin'`
- 이후 유저: `role: 'member'`
- RDB `users` 테이블에는 role 미저장 (AGE에서만 관리)
