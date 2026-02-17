# 비중 변화 알림 서비스 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 즐겨찾기 ETF 비중 변화를 인앱 SSE + 디스코드 웹훅으로 알림

**Architecture:** DAG 수집 완료 시 `collection_runs` 테이블에 기록하고 디스코드 웹훅 발송. 백엔드 SSE 엔드포인트가 30초 폴링으로 새 수집을 감지하여 프론트에 push. User 노드에 `role` 프로퍼티 추가(admin/member).

**Tech Stack:** FastAPI StreamingResponse (SSE), Discord Webhook (httpx), AGE User.role, PostgreSQL collection_runs 테이블

---

### Task 1: DB 스키마 변경 — collection_runs 테이블 + users.last_notification_checked_at

**Files:**
- Modify: `docker/db/init/01_extensions.sql`
- Modify: `backend/app/models/user.py`

**Step 1: `01_extensions.sql`에 collection_runs 테이블 추가**

users 테이블 뒤에 추가:

```sql
CREATE TABLE IF NOT EXISTS collection_runs (
    id SERIAL PRIMARY KEY,
    collected_at DATE NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

users 테이블에 컬럼 추가:

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_notification_checked_at TIMESTAMP;
```

**Step 2: User ORM 모델에 컬럼 추가**

`backend/app/models/user.py`의 User 클래스에 추가:

```python
last_notification_checked_at = Column(DateTime, nullable=True)
```

**Step 3: 실행 중인 DB에 수동 적용**

```bash
docker exec etf-atlas-db psql -U postgres -d etf_atlas -c "
CREATE TABLE IF NOT EXISTS collection_runs (
    id SERIAL PRIMARY KEY,
    collected_at DATE NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_notification_checked_at TIMESTAMP;
"
```

**Step 4: 커밋**

```bash
git add docker/db/init/01_extensions.sql backend/app/models/user.py
git commit -m "feat: collection_runs 테이블 및 users.last_notification_checked_at 추가"
```

---

### Task 2: CollectionRun ORM 모델 추가

**Files:**
- Create: `backend/app/models/collection_run.py`
- Modify: `backend/app/models/__init__.py`

**Step 1: ORM 모델 작성**

```python
# backend/app/models/collection_run.py
from sqlalchemy import Column, Integer, Date, DateTime
from datetime import datetime
from ..database import Base


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id = Column(Integer, primary_key=True, index=True)
    collected_at = Column(Date, nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
```

**Step 2: `__init__.py`에 import 추가**

```python
from .collection_run import CollectionRun
```

**Step 3: 커밋**

```bash
git add backend/app/models/collection_run.py backend/app/models/__init__.py
git commit -m "feat: CollectionRun ORM 모델 추가"
```

---

### Task 3: AGE User 노드에 role 프로퍼티 추가

**Files:**
- Modify: `backend/app/services/graph_service.py` (add_watch 메서드의 MERGE User 부분)
- Modify: `backend/app/services/auth_service.py` (get_or_create_user에서 AGE User 노드 role 설정)

**Step 1: graph_service.py에 유저 역할 조회/설정 메서드 추가**

`get_user_role`, `set_user_role` 메서드를 GraphService에 추가:

```python
def get_user_role(self, user_id: int) -> str:
    """유저 역할 조회. 없으면 'member'."""
    query = """
    MATCH (u:User {user_id: $user_id})
    RETURN {role: u.role}
    """
    rows = self.execute_cypher(query, {"user_id": user_id})
    if rows:
        result = self.parse_agtype(rows[0]["result"])
        return result.get("role") or "member"
    return "member"

def set_user_role(self, user_id: int, role: str):
    """유저 역할 설정."""
    query = """
    MERGE (u:User {user_id: $user_id})
    SET u.role = $role
    RETURN {role: u.role}
    """
    self.execute_cypher(query, {"user_id": user_id, "role": role})
    self.db.commit()

def get_admin_user_ids(self) -> list[int]:
    """admin 역할 유저 ID 목록."""
    query = """
    MATCH (u:User {role: 'admin'})
    RETURN {user_id: u.user_id}
    """
    rows = self.execute_cypher(query, {})
    return [self.parse_agtype(row["result"])["user_id"] for row in rows]
```

**Step 2: auth_service.py에서 유저 생성 시 역할 설정**

`get_or_create_user` 메서드 수정 — 새 유저 생성 후 AGE User 노드에 role 설정:

```python
def get_or_create_user(self, google_data: dict) -> User:
    user = self.db.query(User).filter(User.google_id == google_data["google_id"]).first()

    if user:
        user.name = google_data["name"]
        user.picture = google_data["picture"]
        self.db.commit()
        self.db.refresh(user)
        return user

    # 첫 번째 유저인지 확인
    is_first = self.db.query(User).count() == 0

    user = User(
        email=google_data["email"],
        name=google_data["name"],
        picture=google_data["picture"],
        google_id=google_data["google_id"]
    )
    self.db.add(user)
    self.db.commit()
    self.db.refresh(user)

    # AGE User 노드에 role 설정
    from .graph_service import GraphService
    graph = GraphService(self.db)
    graph.set_user_role(user.id, "admin" if is_first else "member")

    return user
```

**Step 3: 기존 유저에 admin role 수동 설정**

```bash
docker exec etf-atlas-db psql -U postgres -d etf_atlas -c "
LOAD 'age';
SET search_path = ag_catalog, '\$user', public;
SELECT * FROM cypher('etf_graph', \$\$
  MATCH (u:User)
  SET u.role = 'admin'
  RETURN u.user_id, u.role
\$\$) as (user_id agtype, role agtype);
"
```

**Step 4: 커밋**

```bash
git add backend/app/services/graph_service.py backend/app/services/auth_service.py
git commit -m "feat: AGE User 노드에 role 프로퍼티 추가 (admin/member)"
```

---

### Task 4: Notifications 라우터 — status + check 엔드포인트

**Files:**
- Create: `backend/app/routers/notifications.py`
- Modify: `backend/app/main.py`

**Step 1: notifications 라우터 생성**

```python
# backend/app/routers/notifications.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from ..database import get_db
from ..models.user import User
from ..models.collection_run import CollectionRun
from ..utils.jwt import get_current_user_id

router = APIRouter()


@router.get("/status")
async def get_notification_status(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """새 알림 유무 확인"""
    user = db.query(User).filter(User.id == user_id).first()
    latest = db.query(CollectionRun).order_by(CollectionRun.created_at.desc()).first()

    if not latest:
        return {"has_new": False, "latest_collected_at": None}

    has_new = (
        user.last_notification_checked_at is None
        or latest.created_at > user.last_notification_checked_at
    )
    return {
        "has_new": has_new,
        "latest_collected_at": latest.collected_at.isoformat(),
    }


@router.post("/check")
async def check_notifications(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """알림 확인 처리 (last_notification_checked_at 갱신)"""
    user = db.query(User).filter(User.id == user_id).first()
    user.last_notification_checked_at = datetime.now(timezone.utc)
    db.commit()
    return {"checked_at": user.last_notification_checked_at.isoformat()}
```

**Step 2: main.py에 라우터 등록**

```python
from .routers import auth, etfs, watchlist, portfolio, tags, chat, notifications

app.include_router(notifications.router, prefix="/api/notifications", tags=["Notifications"])
```

주의: `/api/notifications` 라우터를 `/api/watchlist` 뒤에 등록.

**Step 3: 커밋**

```bash
git add backend/app/routers/notifications.py backend/app/main.py
git commit -m "feat: 알림 status/check API 엔드포인트 추가"
```

---

### Task 5: SSE 스트림 엔드포인트

**Files:**
- Modify: `backend/app/routers/notifications.py`

**Step 1: SSE 엔드포인트 추가**

`notifications.py`에 SSE 스트림 엔드포인트 추가:

```python
import asyncio
import json
from fastapi.responses import StreamingResponse


@router.get("/stream")
async def notification_stream(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """SSE 스트림 — 30초마다 새 수집 확인"""
    user = db.query(User).filter(User.id == user_id).first()

    async def event_generator():
        last_checked = user.last_notification_checked_at
        while True:
            db.expire_all()
            latest = db.query(CollectionRun).order_by(
                CollectionRun.created_at.desc()
            ).first()

            if latest and (last_checked is None or latest.created_at > last_checked):
                data = json.dumps({
                    "type": "new_changes",
                    "collected_at": latest.collected_at.isoformat(),
                })
                yield f"data: {data}\n\n"
                last_checked = latest.created_at

            await asyncio.sleep(30)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

**Step 2: 커밋**

```bash
git add backend/app/routers/notifications.py
git commit -m "feat: SSE 알림 스트림 엔드포인트 추가"
```

---

### Task 6: DAG에 collection_runs 기록 + 디스코드 웹훅 태스크 추가

**Files:**
- Modify: `airflow/dags/age_utils.py` — `record_collection_run`, `send_discord_notification` 함수 추가
- Modify: `airflow/dags/sync_universe_age.py` — 태스크 추가

**Step 1: age_utils.py에 수집 기록 함수 추가**

```python
def record_collection_run(date_str: str):
    """collection_runs 테이블에 수집 완료 기록."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO collection_runs (collected_at) VALUES (%s) "
            "ON CONFLICT (collected_at) DO NOTHING",
            (date_str,)
        )
        conn.commit()
        log.info(f"Collection run recorded: {date_str}")
    finally:
        cur.close()
        conn.close()
```

**Step 2: age_utils.py에 디스코드 웹훅 함수 추가**

```python
def send_discord_notification(date_str: str):
    """admin 유저의 즐겨찾기 기반 비중변화를 디스코드로 발송."""
    import httpx

    webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
    if not webhook_url:
        log.info("DISCORD_WEBHOOK_URL not set — skipping Discord notification")
        return

    conn = get_db_connection()
    cur = init_age(conn)

    try:
        # admin 유저 조회
        results = execute_cypher(cur, """
            MATCH (u:User {role: 'admin'})-[:WATCHES]->(e:ETF)
            RETURN {user_id: u.user_id, etf_code: e.code, etf_name: e.name}
        """, {})

        if not results:
            log.info("No admin watches found — skipping Discord notification")
            return

        watches = []
        for row in results:
            raw = _parse_age_value(row[0])
            import json
            data = json.loads(raw)
            watches.append(data)

        # 전일 HOLDS 날짜 조회
        if watches:
            first_etf = watches[0]['etf_code']
            prev_results = execute_cypher(cur, """
                MATCH (e:ETF {code: $code})-[h:HOLDS]->(:Stock)
                WITH DISTINCT h.date as d
                WHERE d < $date
                RETURN {date: d}
                ORDER BY d DESC
                LIMIT 1
            """, {'code': first_etf, 'date': date_str})
            prev_date = None
            if prev_results:
                raw = _parse_age_value(prev_results[0][0])
                prev_data = json.loads(raw)
                prev_date = prev_data.get('date')

        if not prev_date:
            log.info("No previous date found — skipping Discord notification")
            return

        # ETF별 비중변화 수집
        changes_summary = []
        for w in watches:
            etf_code = w['etf_code']
            etf_name = w['etf_name']

            # 현재 날짜 holdings
            today_h = _query_holdings(cur, etf_code, date_str)
            prev_h = _query_holdings(cur, etf_code, prev_date)

            if not today_h or not prev_h:
                continue

            etf_changes = []
            all_codes = set(today_h.keys()) | set(prev_h.keys())
            for code in all_codes:
                curr = today_h.get(code)
                prev = prev_h.get(code)
                cw = curr['weight'] if curr else 0
                pw = prev['weight'] if prev else 0
                diff = cw - pw

                if abs(diff) <= 3:
                    continue

                if curr and not prev:
                    ct = "신규편입"
                elif prev and not curr:
                    ct = "편출"
                elif diff > 0:
                    ct = "증가"
                else:
                    ct = "감소"

                name = (curr or prev)['name']
                etf_changes.append(f"  {ct} {name}: {pw:.1f}% → {cw:.1f}% ({diff:+.1f}%p)")

            if etf_changes:
                changes_summary.append(f"**{etf_name}** ({etf_code})\n" + "\n".join(etf_changes))

        if not changes_summary:
            log.info("No significant changes — skipping Discord notification")
            return

        # 디스코드 메시지 발송
        message = f"📊 **ETF 비중 변화 알림** ({date_str})\n\n" + "\n\n".join(changes_summary)

        with httpx.Client() as client:
            resp = client.post(webhook_url, json={"content": message})
            resp.raise_for_status()

        log.info(f"Discord notification sent: {len(changes_summary)} ETFs with changes")

    except Exception as e:
        log.warning(f"Discord notification failed: {e}")
    finally:
        cur.close()
        conn.close()
```

**Step 3: sync_universe_age.py에 태스크 추가**

`record_and_notify` 함수 추가:

```python
def record_and_notify(**context):
    """수집 완료 기록 + 디스코드 알림."""
    dates = context['ti'].xcom_pull(task_ids='fetch_trading_dates')
    if not dates:
        return
    last_date = dates[-1]
    date_str = f"{last_date[:4]}-{last_date[4:6]}-{last_date[6:8]}"
    record_collection_run(date_str)
    send_discord_notification(date_str)
```

import 추가:

```python
from age_utils import (
    ..., record_collection_run, send_discord_notification,
)
```

태스크 정의:

```python
t_notify = PythonOperator(task_id='record_and_notify',
                           python_callable=record_and_notify, dag=dag)
```

의존관계 수정 — `t_changes` 자리를 `t_notify`로 교체:

```python
start >> t_dates >> t_universe
t_universe >> [t_holdings, t_returns, t_tags]
t_holdings >> [t_stock_prices, t_notify]
[t_stock_prices, t_notify, t_returns, t_tags] >> end
```

**Step 4: 커밋**

```bash
git add airflow/dags/age_utils.py airflow/dags/sync_universe_age.py
git commit -m "feat: DAG에 수집 기록 및 디스코드 알림 태스크 추가"
```

---

### Task 7: Change 노드 관련 코드 제거

**Files:**
- Modify: `airflow/dags/age_utils.py` — `detect_changes_for_dates`, `_query_holdings`, `_compare_holdings` 제거
- Modify: `airflow/dags/sync_universe_age.py` — `detect_portfolio_changes` 태스크 제거
- Modify: `airflow/dags/backfill_age.py` — `backfill_changes` 태스크 제거

**Step 1: age_utils.py에서 Change 관련 함수 제거**

삭제할 함수:
- `detect_changes_for_dates()` (라인 792-874)
- `_query_holdings()` (라인 877-898)
- `_compare_holdings()` (라인 901-933)

주의: `_query_holdings`는 `send_discord_notification`에서 사용하므로, 디스코드 함수에서 직접 인라인하거나 유지. Task 6에서 `_query_holdings`를 디스코드 함수 내에서 사용하므로 이 함수만 유지.

삭제 대상:
- `detect_changes_for_dates()` (라인 792-874)
- `_compare_holdings()` (라인 901-933)

**Step 2: sync_universe_age.py에서 detect_portfolio_changes 태스크 제거**

- `detect_portfolio_changes` 함수 삭제 (라인 104-127)
- `t_changes` 태스크 정의 삭제 (라인 192-193)
- import에서 `detect_changes_for_dates` 제거
- 의존관계는 Task 6에서 이미 `t_notify`로 교체됨

**Step 3: backfill_age.py에서 backfill_changes 태스크 제거**

- `backfill_changes` 함수 삭제 (라인 142-149)
- `t6` 태스크 정의 삭제 (라인 170-172)
- import에서 `detect_changes_for_dates` 제거
- 의존관계 수정: `t1 >> t2 >> t3 >> t4 >> t5 >> t7`
- `cleanup_graph`에서 Change 노드 삭제 코드 제거 (라인 77-83)

**Step 4: 커밋**

```bash
git add airflow/dags/age_utils.py airflow/dags/sync_universe_age.py airflow/dags/backfill_age.py
git commit -m "refactor: Change 노드 생성 코드 제거 (detect_changes_for_dates 등)"
```

---

### Task 8: Frontend 알림 API 클라이언트 + useNotification 훅

**Files:**
- Modify: `frontend/src/lib/api.ts` — notificationApi 추가
- Create: `frontend/src/hooks/useNotification.tsx` — SSE 연결 + 알림 상태 관리

**Step 1: api.ts에 notification API 추가**

```typescript
// Notification
export const notificationApi = {
  getStatus: async () => {
    const { data } = await api.get<{ has_new: boolean; latest_collected_at: string | null }>(
      '/notifications/status'
    )
    return data
  },
  check: async () => {
    const { data } = await api.post<{ checked_at: string }>('/notifications/check')
    return data
  },
}
```

**Step 2: useNotification 훅 생성**

```typescript
// frontend/src/hooks/useNotification.tsx
import { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react'
import { notificationApi } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { getToken } from '@/lib/auth'

interface NotificationContextType {
  hasNew: boolean
  markChecked: () => Promise<void>
}

const NotificationContext = createContext<NotificationContextType | undefined>(undefined)

export function NotificationProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth()
  const [hasNew, setHasNew] = useState(false)

  // 초기 상태 확인
  useEffect(() => {
    if (!isAuthenticated) {
      setHasNew(false)
      return
    }
    notificationApi.getStatus().then((s) => setHasNew(s.has_new)).catch(() => {})
  }, [isAuthenticated])

  // SSE 연결
  useEffect(() => {
    if (!isAuthenticated) return

    const token = getToken()
    if (!token) return

    const API_URL = import.meta.env.VITE_API_URL || ''
    const es = new EventSource(`${API_URL}/api/notifications/stream?token=${token}`)

    es.onmessage = () => {
      setHasNew(true)
    }

    es.onerror = () => {
      es.close()
    }

    return () => es.close()
  }, [isAuthenticated])

  const markChecked = useCallback(async () => {
    await notificationApi.check()
    setHasNew(false)
  }, [])

  return (
    <NotificationContext.Provider value={{ hasNew, markChecked }}>
      {children}
    </NotificationContext.Provider>
  )
}

export function useNotification() {
  const context = useContext(NotificationContext)
  if (context === undefined) {
    throw new Error('useNotification must be used within a NotificationProvider')
  }
  return context
}
```

주의: SSE는 EventSource가 Authorization 헤더를 지원하지 않으므로 query param으로 token 전달. 백엔드 SSE 엔드포인트에서 query param 인증도 지원하도록 수정 필요 (Task 5 수정 또는 여기서 처리).

**Step 3: SSE 엔드포인트에 query param 인증 추가**

`backend/app/routers/notifications.py`의 stream 엔드포인트 수정:

```python
from fastapi import Query as QueryParam
from ..utils.jwt import decode_access_token

@router.get("/stream")
async def notification_stream(
    token: str = QueryParam(...),
    db: Session = Depends(get_db),
):
    """SSE 스트림 — 30초마다 새 수집 확인"""
    payload = decode_access_token(token)
    user_id = int(payload.get("sub"))
    user = db.query(User).filter(User.id == user_id).first()
    # ... (나머지 동일)
```

**Step 4: 커밋**

```bash
git add frontend/src/lib/api.ts frontend/src/hooks/useNotification.tsx backend/app/routers/notifications.py
git commit -m "feat: 프론트엔드 알림 훅 및 SSE 연결 구현"
```

---

### Task 9: Frontend 헤더 알림 뱃지 + 비중변화 페이지 연동

**Files:**
- Modify: `frontend/src/components/Header.tsx` — Bell 아이콘에 뱃지 추가
- Modify: `frontend/src/app/WatchlistChangesPage.tsx` — 페이지 진입 시 markChecked 호출
- Modify: `frontend/src/App.tsx` — NotificationProvider 추가

**Step 1: App.tsx에 NotificationProvider 추가**

`AuthProvider` 안에 `NotificationProvider` 래핑:

```tsx
import { NotificationProvider } from '@/hooks/useNotification'

// ... Router 내부에서:
<AuthProvider>
  <NotificationProvider>
    {/* ... routes ... */}
  </NotificationProvider>
</AuthProvider>
```

기존 `AuthProvider`가 어디에 있는지 확인하여 그 안에 `NotificationProvider`를 넣기.

**Step 2: Header.tsx에 알림 뱃지 추가**

Bell 아이콘 링크를 수정 — `useNotification` 사용:

```tsx
import { useNotification } from '@/hooks/useNotification'

// Header 컴포넌트 내부:
const { hasNew } = useNotification()

// Bell 링크를 다음으로 교체:
<Link
  to="/watchlist/changes"
  className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground relative"
>
  <Bell className="w-4 h-4" />
  비중 변화
  {hasNew && (
    <span className="absolute -top-1 -right-1 w-2 h-2 bg-red-500 rounded-full" />
  )}
</Link>
```

**Step 3: WatchlistChangesPage.tsx에서 markChecked 호출**

페이지 마운트 시 알림 확인 처리:

```tsx
import { useNotification } from '@/hooks/useNotification'

// 컴포넌트 내부:
const { markChecked } = useNotification()

useEffect(() => {
  if (isAuthenticated) {
    markChecked()
  }
}, [isAuthenticated, markChecked])
```

**Step 4: 커밋**

```bash
git add frontend/src/App.tsx frontend/src/components/Header.tsx frontend/src/app/WatchlistChangesPage.tsx
git commit -m "feat: 헤더 알림 뱃지 및 비중변화 페이지 알림 확인 연동"
```

---

### Task 10: 빌드 확인 및 통합 테스트

**Step 1: 프론트엔드 빌드 확인**

```bash
cd frontend && npm run build
```

**Step 2: 백엔드 컨테이너 재빌드**

```bash
docker compose up -d --build backend
```

**Step 3: DB 마이그레이션 확인**

```bash
docker exec etf-atlas-db psql -U postgres -d etf_atlas -c "\d collection_runs"
docker exec etf-atlas-db psql -U postgres -d etf_atlas -c "\d users" | grep last_notification
```

**Step 4: API 동작 확인**

```bash
# status 확인
curl -H "Authorization: Bearer <token>" http://localhost:9601/api/notifications/status

# check 호출
curl -X POST -H "Authorization: Bearer <token>" http://localhost:9601/api/notifications/check
```

**Step 5: 커밋 (필요 시)**

```bash
git commit -m "fix: 통합 테스트 중 발견된 이슈 수정"
```
