# Architecture (React + FastAPI)

본 문서는 **React(TypeScript) + FastAPI** 기반 포트폴리오 비중 관리 서비스의 최종 소프트웨어 아키텍처를 정의한다.

본 서비스는 소수 사용자(개인 사용 또는 1~수명)를 대상으로 하며, 계산 정확성·설계 유연성·유지보수 단순성을 최우선 목표로 한다.

---

## 1. 기술 선택 요약

| 영역       | 선택                       | 이유                         |
| -------- | ------------------------ | -------------------------- |
| Frontend | React + TypeScript (SPA) | UI 단순성, Next.js 제거로 구조 최소화 |
| Backend  | FastAPI (Python)         | 계산 중심 도메인에 최적              |
| DB       | PostgreSQL               | 관계형 데이터 + 트랜잭션 안정성         |
| 인증       | Google OAuth             | 최소한의 인증, 낮은 진입 장벽          |
| 시세       | yfinance                 | 소규모 서비스에 충분한 정확도           |

---

## 2. 전체 시스템 아키텍처

```
[ React (TypeScript) SPA ]
            ↓
        [ FastAPI ]
  ├─ Auth (Google OAuth)
  ├─ Portfolio API
  ├─ Calculation Domain
  ├─ Price Service (yfinance)
            ↓
      [ PostgreSQL ]
```

* 서버는 단일 FastAPI 애플리케이션
* 계산 로직은 Backend Domain Layer에 집중
* Frontend는 상태 표현 및 입력 역할만 담당
* react version : 18.3
* python version : 3.13
* fastapi version : 0.128.2
* pydantic version : 2.12.5
* postgresql version : 16.11
* yfinance version : 1.1.0

---

## 3. Frontend 아키텍처

### 역할

* 포트폴리오 화면 렌더링
* 목표 비중 및 실제 수량 입력
* 계산 결과 테이블 표시
* 기준 금액 선택 UI 제공

### 원칙

* 계산 로직을 프론트엔드에 두지 않음
* 모든 수치는 API 응답을 그대로 표현

### 구조 예시

```
src/
 ├─ api/
 │   ├─ auth.ts
 │   ├─ portfolio.ts
 │   └─ holding.ts
 ├─ pages/
 │   ├─ Login.tsx
 │   └─ Portfolio.tsx
 ├─ components/
 │   ├─ PortfolioTable.tsx
 │   ├─ TargetEditor.tsx
 │   └─ HoldingEditor.tsx
 ├─ store/
 └─ types/
```

### 권장 라이브러리

* Vite
* React Query (서버 상태)
* Zustand (UI 상태 일부)

---

## 4. Backend 아키텍처 (FastAPI)

### 구조 원칙

* Layered Architecture
* Domain 중심 설계

```
app/
 ├─ main.py
 ├─ api/
 │   ├─ auth.py
 │   ├─ portfolio.py
 │   ├─ target_allocation.py
 │   └─ holding.py
 ├─ domain/
 │   └─ portfolio_calculation.py
 ├─ services/
 │   └─ price_service.py
 ├─ models/
 ├─ schemas/
 └─ db/
```

* `domain`은 비즈니스 로직의 단일 진실 원천
* API Layer는 요청/응답 변환만 담당

---

## 5. 핵심 도메인: Portfolio Calculation

### 책임

* 목표(Target)와 실제 보유(Holding) 병합
* 기준 금액 기반 목표 수량 계산
* 매수/매도 필요 수량 산출

### 입력

* TargetAllocation[]
* Holding[]
* CurrentPrice[]
* CalculationBase

### 출력

* 종목별 계산 결과 리스트

### 계산 규칙

* 표시 대상: 목표 또는 실제 중 하나라도 존재하는 종목
* 목표 수량 = (기준 금액 × 목표 비중) ÷ 현재가
* 구매 필요 수량 = 목표 수량 − 실제 수량
* **특수 종목 (CASH)**: 현재가 = 1로 고정, 시세 조회 생략

### 상태 판정

* 구매 필요 수량 > 0 : 매수
* 구매 필요 수량 < 0 : 매도
* 구매 필요 수량 = 0 : 유지

---

## 6. 기준 금액 관리

### 기준 종류

* TARGET_AMOUNT: 사용자가 입력한 목표 금액
* CURRENT_TOTAL: 실제 보유 총 평가 금액 (기본값)

### 규칙

* 실제 보유가 존재하면 기본 기준은 CURRENT_TOTAL
* 기준 변경 시 모든 결과 즉시 재계산

---

## 7. 설계 변경 시 처리 규칙

### 종목 삭제 (설계 기준)

* TargetAllocation 제거
* Holding이 존재할 경우:

  * 화면에 계속 표시
  * 목표 수량: 0
  * 구매 필요 수량: -보유 수량

### 종목 신규 추가

* TargetAllocation 추가
* Holding이 없는 경우:

  * 실제 수량: 0
  * 구매 필요 수량: 목표 수량

---

## 8. 인증 아키텍처

### 방식

* Google OAuth 단일 로그인

### 흐름

```
[ React ]
  └─ Google Login
        ↓
[ FastAPI ]
  ├─ Google ID Token 검증
  ├─ User 생성/조회
  └─ JWT 발급
```

### User 모델

```
User
- id
- provider (google)
- provider_user_id
- email
- name
- created_at
```

---

## 9. Price Service 아키텍처

### 구현

* yfinance 기반 시세 조회
* **KRW 전용**: 환율 변환 로직 없음

```
PriceService
 └─ yfinance
```

### 설계 원칙

* PriceProvider 인터페이스 유지
* 추후 Redis 또는 외부 API로 교체 가능

---

## 10. 데이터 저장 원칙

* DB에는 사용자 입력 데이터만 저장

  * 목표 비중
  * 실제 보유 수량
* 계산 결과는 저장하지 않음
* 모든 결과는 요청 시 Domain Layer에서 재계산

---

## 11. 확장 전략

### 단기 (MVP)

* 단일 FastAPI 서버
* PostgreSQL 단일 DB

### 중장기

* Price Service 분리
* Redis 도입
* Calculation Domain 서비스화

---

## 12. 요약

* 본 서비스는 **포트폴리오 관리 도구**
* React는 표현 계층, FastAPI는 비즈니스 로직 담당
* 초기 단순성을 유지하면서도 확장 가능한 구조를 채택
* 인증은 Google OAuth로 최소화하여 사용성을 우선한다
