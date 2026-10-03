# ETF Atlas API 스키마

> 인증 API는 현재 구현 기준이다. 그 외 섹션(종목/ETF/워치리스트/AI 추천)은 초기 설계안이며 실제 엔드포인트와 다를 수 있다. 현재 API 전체 목록은 Swagger(`http://localhost:9601/docs`)를 참고한다.

## 공통

### 응답 형식

```typescript
// 성공 응답
{
  "data": T,
  "message": "success"
}

// 에러 응답
{
  "error": {
    "code": "ERROR_CODE",
    "message": "에러 메시지"
  }
}
```

### 공통 에러 코드

| 코드 | HTTP | 설명 |
|------|------|------|
| `UNAUTHORIZED` | 401 | 인증 필요 |
| `TOKEN_EXPIRED` | 401 | 토큰 만료 |
| `FORBIDDEN` | 403 | 권한 없음 |
| `NOT_FOUND` | 404 | 리소스 없음 |
| `VALIDATION_ERROR` | 422 | 입력값 오류 |
| `INTERNAL_ERROR` | 500 | 서버 오류 |

---

## 인증 API

아이디/비밀번호 + 서버 세션 방식 (`backend/app/routers/auth.py`, `utils/session.py`). 인증 API는 공통 응답 래퍼 없이 객체를 그대로 반환하고, 에러는 FastAPI 기본 형식(`{"detail": "..."}`)을 따른다.
setup·register·login에 성공하면 응답 본문으로 사용자 정보를, `Set-Cookie`로 세션 쿠키 `etf_atlas_session`(HttpOnly, SameSite=Lax, Path=/api, 7일, `COOKIE_SECURE=true`면 Secure)를 내려준다. 이후 요청은 브라우저가 쿠키를 자동으로 보낸다 — JS는 토큰을 다루지 않는다.
서버는 토큰의 SHA-256 해시를 `auth_sessions`에 저장해 매 요청 대조한다. 로그아웃하거나 사용자가 삭제되면 세션이 즉시 무효가 된다.

**비밀번호/아이디 규칙** (setup, register 공통)
| 필드 | 규칙 |
|------|------|
| username | 3~50자, `^[A-Za-z0-9_.-]+$` |
| password | 8자 이상, 72바이트 이하 (bcrypt 한도) |
| name | 선택, 최대 255자 |

### GET /api/auth/setup-status

최초 설치(관리자 생성) 필요 여부. 사용자가 한 명도 없으면 `true` — 프론트엔드는 이 경우 `/setup`으로 리다이렉트한다.

**Response**
```typescript
{
  "setup_required": boolean
}
```

### POST /api/auth/setup

최초 관리자 계정 생성. 사용자가 0명일 때만 허용되며 `admin` 역할을 부여한다.

**Request**
```typescript
{
  "username": string,
  "password": string,
  "name"?: string | null
}
```

**Response** `201`
```typescript
{
  "id": number,
  "username": string,
  "name": string | null,
  "is_admin": boolean
}  // + Set-Cookie: etf_atlas_session=...
```

**에러**
| HTTP | detail | 설명 |
|------|--------|------|
| 409 | `Setup already completed` | 이미 사용자가 존재 |
| 409 | `Username already exists` | 아이디 중복 |

### GET /api/auth/invitations/{invite_token}

초대 링크를 아직 쓸 수 있는지 조회 (가입 화면 진입 시).

**Response**
```typescript
{
  "valid": boolean  // 없거나, 이미 쓰였거나, 만료됐으면 false
}
```

### POST /api/auth/register

초대 링크로 멤버 가입 (`member` 역할). 공개 가입은 없다. 초대는 관리자가 `POST /api/admin/invitations`로 만들며 1회용, 7일 유효.

**Request**
```typescript
{
  "username": string,
  "password": string,
  "name"?: string | null,
  "invite_token": string
}
```

**Response** `201` — `/api/auth/setup`과 동일

**에러**
| HTTP | detail | 설명 |
|------|--------|------|
| 400 | `Invalid invitation` | 초대가 없거나, 이미 쓰였거나, 만료됨 |
| 409 | `Username already exists` | 아이디 중복 (초대는 소모되지 않음) |

### POST /api/auth/login

**Request**
```typescript
{
  "username": string,
  "password": string
}
```

**Response**
```typescript
{
  "id": number,
  "username": string,
  "name": string | null,
  "is_admin": boolean
}  // + Set-Cookie: etf_atlas_session=...
```

**에러**
| HTTP | detail | 설명 |
|------|--------|------|
| 401 | `Invalid username or password` | 아이디 또는 비밀번호 불일치 |

### POST /api/auth/logout

서버 세션을 폐기하고 쿠키를 지운다. 세션이 이미 없어도 `204`.

### GET /api/auth/me

내 정보 조회

**인증**: 세션 쿠키 필요

**Response**
```typescript
{
  "id": number,
  "username": string,
  "name": string | null,
  "is_admin": boolean
}
```

---

## 종목 API

### GET /api/stocks/search

종목 검색 (자동완성)

**Query Parameters**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| q | string | O | 검색어 (2자 이상) |
| limit | number | X | 결과 수 (기본: 10, 최대: 50) |

**Response**
```typescript
{
  "data": {
    "stocks": [
      {
        "code": string,      // "005930"
        "name": string,      // "삼성전자"
        "sector": string     // "반도체"
      }
    ]
  }
}
```

### GET /api/stocks/{code}/etfs

종목을 보유한 ETF 리스트 (역추적)

**Path Parameters**
| 파라미터 | 타입 | 설명 |
|----------|------|------|
| code | string | 종목 코드 |

**Query Parameters**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| type | string | X | "active" \| "passive" \| "all" (기본: all) |
| min_asset | number | X | 최소 자산규모 (억원) |
| sort | string | X | "weight" \| "asset" (기본: weight) |
| limit | number | X | 결과 수 (기본: 50) |
| offset | number | X | 페이지네이션 |

**Response**
```typescript
{
  "data": {
    "stock": {
      "code": string,
      "name": string
    },
    "total_count": number,
    "etfs": [
      {
        "code": string,           // "152100"
        "name": string,           // "TIGER 200"
        "type": "active" | "passive",
        "manager": string,        // "미래에셋자산운용"
        "total_asset": number,    // 억원 단위
        "weight": number,         // 해당 종목 비중 (%)
        "is_watchlist": boolean   // 워치리스트 등록 여부
      }
    ]
  }
}
```

---

## ETF API

### GET /api/etfs/search

ETF 검색 (자동완성)

**Query Parameters**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| q | string | O | 검색어 (2자 이상) |
| type | string | X | "active" \| "passive" \| "all" |
| limit | number | X | 결과 수 (기본: 10) |

**Response**
```typescript
{
  "data": {
    "etfs": [
      {
        "code": string,
        "name": string,
        "type": "active" | "passive",
        "manager": string
      }
    ]
  }
}
```

### GET /api/etfs/{code}

ETF 상세 정보

**Path Parameters**
| 파라미터 | 타입 | 설명 |
|----------|------|------|
| code | string | ETF 코드 |

**Response**
```typescript
{
  "data": {
    "code": string,
    "name": string,
    "type": "active" | "passive",
    "manager": string,           // 운용사
    "inception_date": string,    // 설정일 (YYYY-MM-DD)
    "total_asset": number,       // 총자산 (억원)
    "is_watchlist": boolean,
    "returns": {
      "1d": number,              // 전일 대비 수익률 (%)
      "1w": number,              // 1주 수익률
      "1m": number,              // 1달 수익률
      "3m": number,
      "1y": number
    }
  }
}
```

### GET /api/etfs/{code}/holdings

ETF 구성 종목

**Path Parameters**
| 파라미터 | 타입 | 설명 |
|----------|------|------|
| code | string | ETF 코드 |

**Query Parameters**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| date | string | X | 조회 날짜 (기본: 최신) |
| limit | number | X | 결과 수 (기본: 전체) |

**Response**
```typescript
{
  "data": {
    "date": string,              // 스냅샷 날짜
    "holdings": [
      {
        "stock_code": string,
        "stock_name": string,
        "sector": string,
        "weight": number,        // 비중 (%)
        "shares": number         // 보유 주수
      }
    ]
  }
}
```

### GET /api/etfs/{code}/changes

ETF 포트폴리오 변화

**Path Parameters**
| 파라미터 | 타입 | 설명 |
|----------|------|------|
| code | string | ETF 코드 |

**Query Parameters**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| period | string | X | "1m" \| "3m" \| "6m" (기본: 1m) |

**Response**
```typescript
{
  "data": {
    "period": string,
    "changes": [
      {
        "date": string,                              // 변화 감지 날짜
        "type": "NEW" | "REMOVED" | "WEIGHT_CHANGE",
        "stock_code": string,
        "stock_name": string,
        "before_weight": number | null,              // 이전 비중
        "after_weight": number | null,               // 이후 비중
        "weight_diff": number | null                 // 비중 변화 (%p)
      }
    ]
  }
}
```

### GET /api/etfs/{code}/price

ETF 가격 데이터 (캔들차트용)

**Path Parameters**
| 파라미터 | 타입 | 설명 |
|----------|------|------|
| code | string | ETF 코드 |

**Query Parameters**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| period | string | X | "1w" \| "1m" \| "3m" \| "1y" (기본: 1m) |

**Response**
```typescript
{
  "data": {
    "prices": [
      {
        "date": string,      // YYYY-MM-DD
        "open": number,
        "high": number,
        "low": number,
        "close": number,
        "volume": number
      }
    ]
  }
}
```

---

## 워치리스트 API (인증 필요)

### GET /api/watchlist

내 워치리스트 조회

**인증**: 세션 쿠키 필요

**Response**
```typescript
{
  "data": {
    "watchlist": [
      {
        "etf_code": string,
        "etf_name": string,
        "type": "active" | "passive",
        "manager": string,
        "added_at": string,          // ISO 8601
        "returns": {
          "1d": number,
          "1w": number,
          "1m": number
        },
        "recent_changes_count": number  // 최근 1달 변화 수
      }
    ]
  }
}
```

### POST /api/watchlist

워치리스트에 ETF 추가

**인증**: 세션 쿠키 필요

**Request**
```typescript
{
  "etf_code": string
}
```

**Response**
```typescript
{
  "data": {
    "id": string,
    "etf_code": string,
    "added_at": string
  }
}
```

**에러**
| 코드 | 설명 |
|------|------|
| `ETF_NOT_FOUND` | 존재하지 않는 ETF |
| `ALREADY_EXISTS` | 이미 등록된 ETF |

### DELETE /api/watchlist/{etf_code}

워치리스트에서 ETF 삭제

**인증**: 세션 쿠키 필요

**Path Parameters**
| 파라미터 | 타입 | 설명 |
|----------|------|------|
| etf_code | string | ETF 코드 |

**Response**
```typescript
{
  "message": "success"
}
```

### GET /api/watchlist/changes

워치리스트 ETF들의 포트폴리오 변화

**인증**: 세션 쿠키 필요

**Query Parameters**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| period | string | X | "1m" \| "3m" \| "6m" (기본: 1m) |

**Response**
```typescript
{
  "data": {
    "changes": [
      {
        "etf_code": string,
        "etf_name": string,
        "date": string,
        "type": "NEW" | "REMOVED" | "WEIGHT_CHANGE",
        "stock_code": string,
        "stock_name": string,
        "before_weight": number | null,
        "after_weight": number | null,
        "weight_diff": number | null
      }
    ]
  }
}
```

---

## AI 추천 API (인증 필요)

### GET /api/ai/recommendations

워치리스트 기반 종목 추천

**인증**: 세션 쿠키 필요

**Query Parameters**
| 파라미터 | 타입 | 필수 | 설명 |
|----------|------|------|------|
| period | string | X | "1m" \| "3m" (기본: 1m) |

**Response**
```typescript
{
  "data": {
    "analysis_date": string,
    "watchlist_count": number,       // 분석한 워치리스트 ETF 수
    "buy_signals": [
      {
        "stock_code": string,
        "stock_name": string,
        "sector": string,
        "signal_type": "NEW" | "WEIGHT_INCREASE",
        "signals": [                 // 개별 시그널 상세
          {
            "etf_code": string,
            "etf_name": string,
            "type": "NEW" | "WEIGHT_CHANGE",
            "weight_diff": number | null
          }
        ],
        "etf_count": number,         // 시그널 발생 ETF 수
        "strength": number           // 신호 강도 (1-5)
      }
    ],
    "sell_signals": [
      {
        "stock_code": string,
        "stock_name": string,
        "sector": string,
        "signal_type": "REMOVED" | "WEIGHT_DECREASE",
        "signals": [...],
        "etf_count": number,
        "strength": number
      }
    ],
    "insight": string                // AI 생성 인사이트 텍스트
  }
}
```

**에러**
| 코드 | 설명 |
|------|------|
| `EMPTY_WATCHLIST` | 워치리스트가 비어있음 |
| `INSUFFICIENT_DATA` | 분석할 데이터 부족 |

---

## 관리자 ETF 태그 API (관리자 권한 필요)

### GET /api/admin/etf-tags

전체 ETF(순자산순)와 현재 태그, 선택 가능한 태그 목록.

```json
{
  "items": [{"code": "069500", "name": "KODEX 200", "net_assets": 25188200000000, "tags": ["코스피"], "manual": false}],
  "tags": ["2차전지", "AI", "..."]
}
```

### PUT /api/admin/etf-tags/{etf_code}

ETF 태그를 수동 지정한다. 지정한 ETF는 `age_tagging`의 규칙/LLM 태깅에서 제외된다.

| body | 동작 |
|------|------|
| `{"tags": ["전력", "원전"]}` | 해당 태그로 고정 (`TAGGED` 즉시 교체) |
| `{"tags": []}` | 태그 없음으로 고정 |
| `{"tags": null}` | 수동 지정 해제. `tagged_at`도 지워 다음 `age_tagging` 실행에서 신규 ETF처럼 다시 태깅된다 (그때까지 현재 태그 유지) |

응답은 `items`의 원소 하나. 없는 태그는 400, 없는 ETF는 404.

---

## TypeScript 타입 정의 (프론트엔드용)

```typescript
// types/api.ts

// 공통
export interface ApiResponse<T> {
  data: T;
  message?: string;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
  };
}

// 인증
export interface User {
  id: number;
  username: string;
  name: string | null;
  is_admin: boolean;
}

// 종목
export interface Stock {
  code: string;
  name: string;
  sector: string;
}

// ETF
export interface ETF {
  code: string;
  name: string;
  type: 'active' | 'passive';
  manager: string;
  inception_date?: string;
  total_asset?: number;
  is_watchlist?: boolean;
}

export interface ETFDetail extends ETF {
  returns: {
    '1d': number;
    '1w': number;
    '1m': number;
    '3m': number;
    '1y': number;
  };
}

export interface ETFHolding {
  stock_code: string;
  stock_name: string;
  sector: string;
  weight: number;
  shares: number;
}

export interface ETFChange {
  date: string;
  type: 'NEW' | 'REMOVED' | 'WEIGHT_CHANGE';
  stock_code: string;
  stock_name: string;
  before_weight: number | null;
  after_weight: number | null;
  weight_diff: number | null;
}

export interface ETFPrice {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// 워치리스트
export interface WatchlistItem {
  etf_code: string;
  etf_name: string;
  type: 'active' | 'passive';
  manager: string;
  added_at: string;
  returns: {
    '1d': number;
    '1w': number;
    '1m': number;
  };
  recent_changes_count: number;
}

// AI 추천
export interface Signal {
  etf_code: string;
  etf_name: string;
  type: 'NEW' | 'REMOVED' | 'WEIGHT_CHANGE';
  weight_diff: number | null;
}

export interface StockSignal {
  stock_code: string;
  stock_name: string;
  sector: string;
  signal_type: 'NEW' | 'REMOVED' | 'WEIGHT_INCREASE' | 'WEIGHT_DECREASE';
  signals: Signal[];
  etf_count: number;
  strength: number;
}

export interface Recommendations {
  analysis_date: string;
  watchlist_count: number;
  buy_signals: StockSignal[];
  sell_signals: StockSignal[];
  insight: string;
}
```
