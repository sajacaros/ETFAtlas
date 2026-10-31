"""로그인·가입·계정 API 스키마"""
from pydantic import BaseModel, Field, field_validator


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


class PasswordChangeRequest(PasswordField):
    """password가 새 비밀번호"""
    current_password: str = Field(min_length=1, max_length=72)


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


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
