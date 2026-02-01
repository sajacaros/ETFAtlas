# Google OAuth 설정 가이드

## 개요

ETF Atlas v1에서 Google 로그인을 사용하기 위한 Google Cloud Console 설정 가이드

---

## 1. Google Cloud 프로젝트 생성

### 1.1 Google Cloud Console 접속

1. [Google Cloud Console](https://console.cloud.google.com) 접속
2. Google 계정으로 로그인

### 1.2 새 프로젝트 생성

1. 상단 프로젝트 선택 드롭다운 클릭
2. **새 프로젝트** 클릭
3. 프로젝트 정보 입력:
   - 프로젝트 이름: `etf-atlas` (또는 원하는 이름)
   - 조직: 개인 계정이면 "조직 없음" 선택
4. **만들기** 클릭

---

## 2. OAuth 동의 화면 설정

### 2.1 동의 화면 구성

1. 좌측 메뉴: **API 및 서비스** > **OAuth 동의 화면**
2. User Type 선택:
   - **외부** 선택 (개인 프로젝트의 경우)
   - **만들기** 클릭

### 2.2 앱 정보 입력

**1단계: OAuth 동의 화면**

| 필드 | 값 |
|------|-----|
| 앱 이름 | ETF Atlas |
| 사용자 지원 이메일 | 본인 이메일 |
| 앱 로고 | (선택사항) |
| 앱 도메인 | (개발 단계에서는 비워둠) |
| 개발자 연락처 이메일 | 본인 이메일 |

**저장 후 계속** 클릭

**2단계: 범위**

1. **범위 추가 또는 삭제** 클릭
2. 다음 범위 선택:
   - `email` - 이메일 주소 확인
   - `profile` - 이름, 프로필 사진
   - `openid` - OpenID Connect

```
선택된 범위:
- .../auth/userinfo.email
- .../auth/userinfo.profile
- openid
```

**저장 후 계속** 클릭

**3단계: 테스트 사용자**

개발 중에는 테스트 사용자 등록 필요:

1. **+ ADD USERS** 클릭
2. 테스트에 사용할 Google 계정 이메일 입력
3. **추가** 클릭

> ⚠️ 앱이 "테스트" 상태일 때는 등록된 테스트 사용자만 로그인 가능

**저장 후 계속** 클릭

**4단계: 요약**

설정 확인 후 **대시보드로 돌아가기**

---

## 3. OAuth 2.0 클라이언트 ID 생성

### 3.1 사용자 인증 정보 생성

1. 좌측 메뉴: **API 및 서비스** > **사용자 인증 정보**
2. 상단 **+ 사용자 인증 정보 만들기** 클릭
3. **OAuth 클라이언트 ID** 선택

### 3.2 클라이언트 ID 설정

| 필드 | 값 |
|------|-----|
| 애플리케이션 유형 | **웹 애플리케이션** |
| 이름 | ETF Atlas Backend |

**승인된 JavaScript 원본** (선택사항)
```
http://localhost:9600
```

**승인된 리디렉션 URI** (필수)
```
http://localhost:9601/auth/google/callback
```

> 📌 포트 번호가 아키텍처 문서와 일치하는지 확인

### 3.3 클라이언트 ID/Secret 저장

**만들기** 클릭 후 표시되는 정보 저장:

```
클라이언트 ID: xxxxxxxxxxxx.apps.googleusercontent.com
클라이언트 보안 비밀번호: xxxxxxxxxxxxxxxxxxxxxxxx
```

> ⚠️ 클라이언트 보안 비밀번호는 이 화면에서만 확인 가능. 반드시 안전한 곳에 저장!

---

## 4. 환경 변수 설정

### 4.1 .env 파일 생성

프로젝트 루트에 `.env` 파일 생성:

```env
# Google OAuth
GOOGLE_CLIENT_ID=xxxxxxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx

# JWT
JWT_SECRET=your-super-secret-key-change-this-in-production

# URLs
FRONTEND_URL=http://localhost:9600
BACKEND_URL=http://localhost:9601
GOOGLE_REDIRECT_URI=http://localhost:9601/auth/google/callback

# Database
DATABASE_URL=postgresql://etfatlas:etfatlas@localhost:9602/etfatlas
```

### 4.2 .gitignore 확인

`.env` 파일이 Git에 커밋되지 않도록 확인:

```gitignore
# .gitignore
.env
.env.local
.env.*.local
```

---

## 5. 백엔드 구현 예시

### 5.1 의존성 설치

```bash
pip install authlib httpx python-jose[cryptography]
```

### 5.2 OAuth 설정 (config.py)

```python
# backend/app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    jwt_secret: str
    frontend_url: str

    class Config:
        env_file = ".env"

settings = Settings()
```

### 5.3 OAuth 라우터 (routers/auth.py)

```python
# backend/app/routers/auth.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config

from app.config import settings
from app.services.auth_service import create_user_if_not_exists, create_tokens

router = APIRouter(prefix="/auth", tags=["auth"])

# OAuth 설정
config = Config(environ={
    "GOOGLE_CLIENT_ID": settings.google_client_id,
    "GOOGLE_CLIENT_SECRET": settings.google_client_secret,
})

oauth = OAuth(config)
oauth.register(
    name='google',
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)


@router.get("/google")
async def google_login(request):
    """Google OAuth 로그인 시작"""
    redirect_uri = settings.google_redirect_uri
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request):
    """Google OAuth 콜백 처리"""
    try:
        # Google에서 토큰 받기
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get('userinfo')

        if not user_info:
            raise HTTPException(status_code=400, detail="Failed to get user info")

        # 사용자 생성/조회
        user = await create_user_if_not_exists(
            google_id=user_info['sub'],
            email=user_info['email'],
            name=user_info.get('name', '')
        )

        # JWT 토큰 생성
        tokens = create_tokens(user.id)

        # 프론트엔드로 리다이렉트 (토큰 포함)
        redirect_url = (
            f"{settings.frontend_url}/auth/callback"
            f"?access_token={tokens['access_token']}"
            f"&refresh_token={tokens['refresh_token']}"
        )
        return RedirectResponse(url=redirect_url)

    except Exception as e:
        # 에러 시 프론트엔드 에러 페이지로 리다이렉트
        return RedirectResponse(
            url=f"{settings.frontend_url}/auth/error?message={str(e)}"
        )


@router.post("/refresh")
async def refresh_token(refresh_token: str):
    """토큰 갱신"""
    # 구현...
    pass


@router.get("/me")
async def get_me(current_user = Depends(get_current_user)):
    """현재 사용자 정보"""
    return {"data": current_user}
```

### 5.4 JWT 유틸 (utils/jwt.py)

```python
# backend/app/utils/jwt.py
from datetime import datetime, timedelta
from jose import jwt, JWTError
from app.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 7


def create_access_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "exp": expire,
        "type": "access"
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "exp": expire,
        "type": "refresh"
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def create_tokens(user_id: str) -> dict:
    return {
        "access_token": create_access_token(user_id),
        "refresh_token": create_refresh_token(user_id),
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
```

---

## 6. 프론트엔드 구현 예시

### 6.1 로그인 버튼 컴포넌트

```typescript
// frontend/src/components/auth/GoogleLoginButton.tsx
'use client';

import { Button } from '@/components/ui/button';

const BACKEND_URL = process.env.NEXT_PUBLIC_API_URL;

export function GoogleLoginButton() {
  const handleLogin = () => {
    // 백엔드의 Google OAuth 엔드포인트로 리다이렉트
    window.location.href = `${BACKEND_URL}/auth/google`;
  };

  return (
    <Button onClick={handleLogin} variant="outline" className="w-full">
      <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24">
        {/* Google 아이콘 SVG */}
      </svg>
      Google로 계속하기
    </Button>
  );
}
```

### 6.2 콜백 페이지

```typescript
// frontend/src/app/auth/callback/page.tsx
'use client';

import { useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';

export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setTokens } = useAuth();

  useEffect(() => {
    const accessToken = searchParams.get('access_token');
    const refreshToken = searchParams.get('refresh_token');

    if (accessToken && refreshToken) {
      // 토큰 저장
      setTokens(accessToken, refreshToken);
      // 메인 페이지로 이동
      router.push('/');
    } else {
      // 에러 처리
      router.push('/login?error=auth_failed');
    }
  }, [searchParams, router, setTokens]);

  return (
    <div className="flex items-center justify-center min-h-screen">
      <p>로그인 처리 중...</p>
    </div>
  );
}
```

### 6.3 인증 훅

```typescript
// frontend/src/hooks/useAuth.ts
'use client';

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  setTokens: (access: string, refresh: string) => void;
  clearTokens: () => void;
}

export const useAuth = create<AuthState>()(
  persist(
    (set) => ({
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,

      setTokens: (access, refresh) => set({
        accessToken: access,
        refreshToken: refresh,
        isAuthenticated: true,
      }),

      clearTokens: () => set({
        accessToken: null,
        refreshToken: null,
        isAuthenticated: false,
      }),
    }),
    {
      name: 'auth-storage',
    }
  )
);
```

---

## 7. 테스트

### 7.1 로컬 테스트 절차

1. Docker 서비스 실행
   ```bash
   docker-compose up -d
   ```

2. 브라우저에서 접속
   ```
   http://localhost:9600
   ```

3. "Google로 로그인" 클릭

4. Google 로그인 페이지에서 테스트 사용자로 로그인

5. 콜백 처리 확인
   - 성공 시: 메인 페이지로 이동
   - 실패 시: 에러 페이지로 이동

### 7.2 일반적인 오류

| 오류 | 원인 | 해결 |
|------|------|------|
| `redirect_uri_mismatch` | 리디렉션 URI 불일치 | Google Console에서 URI 확인 |
| `access_denied` | 테스트 사용자 미등록 | OAuth 동의 화면에서 사용자 추가 |
| `invalid_client` | 클라이언트 ID/Secret 오류 | .env 파일 확인 |

---

## 8. 프로덕션 배포 시 변경사항

### 8.1 OAuth 동의 화면 게시

1. **API 및 서비스** > **OAuth 동의 화면**
2. **앱 게시** 클릭
3. Google 검토 필요 (1~2주 소요)

### 8.2 리디렉션 URI 추가

프로덕션 도메인 추가:
```
https://etf-atlas.com/auth/google/callback
```

### 8.3 환경 변수 변경

```env
FRONTEND_URL=https://etf-atlas.com
BACKEND_URL=https://api.etf-atlas.com
GOOGLE_REDIRECT_URI=https://api.etf-atlas.com/auth/google/callback
```

---

## 9. 체크리스트

### 설정 완료 체크리스트

- [ ] Google Cloud 프로젝트 생성
- [ ] OAuth 동의 화면 설정
- [ ] 테스트 사용자 등록
- [ ] OAuth 클라이언트 ID 생성
- [ ] 리디렉션 URI 설정 (`http://localhost:9601/auth/google/callback`)
- [ ] .env 파일에 GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET 설정
- [ ] .gitignore에 .env 추가 확인
