# ETF Atlas API 스키마

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

### POST /auth/google

Google OAuth 로그인 시작

**Response**
```typescript
{
  "data": {
    "auth_url": string  // Google 로그인 페이지 URL
  }
}
```

### GET /auth/google/callback

Google OAuth 콜백 (Google에서 리다이렉트)

**Query Parameters**
| 파라미터 | 타입 | 설명 |
|----------|------|------|
| code | string | Google 인증 코드 |
| state | string | CSRF 방지 토큰 |

**Response**: 프론트엔드로 리다이렉트 (토큰 포함)
```
{FRONTEND_URL}/auth/callback?access_token=xxx&refresh_token=xxx
```

### POST /auth/refresh

토큰 갱신

**Request**
```typescript
{
  "refresh_token": string
}
```

**Response**
```typescript
{
  "data": {
    "access_token": string,
    "refresh_token": string,
    "expires_in": number  // 초 단위
  }
}
```

### POST /auth/logout

로그아웃

**Headers**
```
Authorization: Bearer {access_token}
```

**Response**
```typescript
{
  "message": "success"
}
```

### GET /auth/me

내 정보 조회

**Headers**
```
Authorization: Bearer {access_token}
```

**Response**
```typescript
{
  "data": {
    "id": string,        // UUID
    "email": string,
    "name": string,
    "created_at": string // ISO 8601
  }
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

**Headers**
```
Authorization: Bearer {access_token}
```

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

**Headers**
```
Authorization: Bearer {access_token}
```

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

**Headers**
```
Authorization: Bearer {access_token}
```

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

**Headers**
```
Authorization: Bearer {access_token}
```

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

**Headers**
```
Authorization: Bearer {access_token}
```

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
  id: string;
  email: string;
  name: string;
  created_at: string;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  expires_in: number;
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
