from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.auth_service import (
    AuthService, InvalidInvitationError, InvalidPasswordResetError, SetupAlreadyCompletedError,
    UsernameTakenError, is_admin,
)
from ..models.user import User
from ..utils.session import (
    SESSION_COOKIE, clear_session_cookie, create_session, get_current_user_id, revoke_session,
    set_session_cookie,
)

router = APIRouter()


class PasswordField(BaseModel):
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def _bcrypt_limit(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 72:  # bcrypt 입력 한도
            raise ValueError("password must be at most 72 bytes")
        return v


class CredentialsRequest(PasswordField):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")


class PasswordResetRequest(PasswordField):
    token: str = Field(min_length=1, max_length=64)


class PasswordResetStatusResponse(BaseModel):
    valid: bool
    username: str | None = None


class RegisterRequest(CredentialsRequest):
    name: str | None = Field(default=None, max_length=255)


class InviteRegisterRequest(RegisterRequest):
    invite_token: str = Field(min_length=1, max_length=64)


class InvitationStatusResponse(BaseModel):
    valid: bool


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupStatusResponse(BaseModel):
    setup_required: bool


class UserResponse(BaseModel):
    id: int
    username: str
    name: str | None
    is_admin: bool = False


def _user_response(db: Session, user: User) -> UserResponse:
    return UserResponse(id=user.id, username=user.username, name=user.name, is_admin=is_admin(db, user.id))


def _start_session(request: Request, response: Response, db: Session, user: User) -> UserResponse:
    """새 세션을 쿠키로 내려준다. 브라우저에 남아 있던 이전 세션은 폐기."""
    old_token = request.cookies.get(SESSION_COOKIE)
    if old_token:
        revoke_session(db, old_token)
    set_session_cookie(response, create_session(db, user.id))
    return _user_response(db, user)


@router.get("/setup-status", response_model=SetupStatusResponse)
async def setup_status(db: Session = Depends(get_db)):
    return SetupStatusResponse(setup_required=AuthService(db).setup_required())


@router.post("/setup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def setup(body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """최초 설치: 관리자 계정 생성 (사용자가 한 명도 없을 때만)"""
    try:
        user = AuthService(db).setup_admin(body.username, body.password, body.name)
    except SetupAlreadyCompletedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup already completed")
    except UsernameTakenError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    return _start_session(request, response, db, user)


@router.get("/invitations/{invite_token}", response_model=InvitationStatusResponse)
async def invitation_status(invite_token: str, db: Session = Depends(get_db)):
    """초대 링크가 아직 쓸 수 있는지 (가입 화면 진입 시 확인)"""
    return InvitationStatusResponse(valid=AuthService(db).invitation_valid(invite_token))


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: InviteRegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """초대 링크로만 가입할 수 있다"""
    try:
        user = AuthService(db).register(
            body.username, body.password, body.name, body.invite_token
        )
    except InvalidInvitationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid invitation")
    except UsernameTakenError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    return _start_session(request, response, db, user)


@router.post("/login", response_model=UserResponse)
async def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = AuthService(db).authenticate(body.username, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    return _start_session(request, response, db, user)


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    user = AuthService(db).get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _user_response(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """서버 세션을 폐기하고 쿠키를 지운다 (세션이 이미 없어도 성공)"""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_session(db, token)
    clear_session_cookie(response)


@router.get("/password-resets/{reset_token}", response_model=PasswordResetStatusResponse)
async def password_reset_status(reset_token: str, db: Session = Depends(get_db)):
    """재설정 링크가 아직 쓸 수 있는지와 대상 아이디 (재설정 화면 진입 시 확인)"""
    username = AuthService(db).password_reset_username(reset_token)
    return PasswordResetStatusResponse(valid=username is not None, username=username)


@router.post("/password-reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(body: PasswordResetRequest, db: Session = Depends(get_db)):
    """관리자가 발급한 링크로 비밀번호를 바꾼다. 그 회원의 기존 세션은 모두 끊기고 다시 로그인해야 한다."""
    try:
        AuthService(db).reset_password(body.token, body.password)
    except InvalidPasswordResetError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid password reset link")
