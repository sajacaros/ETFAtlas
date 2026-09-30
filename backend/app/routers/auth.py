from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.auth_service import (
    AuthService, SetupAlreadyCompletedError, UsernameTakenError, is_admin,
)
from ..utils.jwt import create_access_token, get_current_user_id

router = APIRouter()


class CredentialsRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def _bcrypt_limit(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:  # bcrypt 입력 한도
            raise ValueError("password must be at most 72 bytes")
        return v


class RegisterRequest(CredentialsRequest):
    name: str | None = Field(default=None, max_length=255)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SetupStatusResponse(BaseModel):
    setup_required: bool


class UserResponse(BaseModel):
    id: int
    username: str
    name: str | None
    is_admin: bool = False


def _token_for(user_id: int) -> TokenResponse:
    return TokenResponse(access_token=create_access_token(data={"sub": str(user_id)}))


@router.get("/setup-status", response_model=SetupStatusResponse)
async def setup_status(db: Session = Depends(get_db)):
    return SetupStatusResponse(setup_required=AuthService(db).setup_required())


@router.post("/setup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def setup(request: RegisterRequest, db: Session = Depends(get_db)):
    """최초 설치: 관리자 계정 생성 (사용자가 한 명도 없을 때만)"""
    try:
        user = AuthService(db).setup_admin(request.username, request.password, request.name)
    except SetupAlreadyCompletedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup already completed")
    except UsernameTakenError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    return _token_for(user.id)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = AuthService(db).register(request.username, request.password, request.name)
    except SetupAlreadyCompletedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup required first")
    except UsernameTakenError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    return _token_for(user.id)


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = AuthService(db).authenticate(request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    return _token_for(user.id)


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    user = AuthService(db).get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse(
        id=user.id,
        username=user.username,
        name=user.name,
        is_admin=is_admin(db, user.id),
    )
