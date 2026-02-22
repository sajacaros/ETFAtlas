from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ..database import get_db
from ..services.auth_service import AuthService
from ..models.role import Role, UserRole
from ..utils.jwt import create_access_token, get_current_user_id

router = APIRouter()


class GoogleLoginRequest(BaseModel):
    token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    name: str | None
    picture: str | None
    is_admin: bool = False

    class Config:
        from_attributes = True


@router.post("/google", response_model=TokenResponse)
async def google_login(request: GoogleLoginRequest, db: Session = Depends(get_db)):
    auth_service = AuthService(db)
    try:
        google_data = auth_service.verify_google_token(request.token)
        user = auth_service.get_or_create_user(google_data)
        access_token = create_access_token(data={"sub": str(user.id)})
        return TokenResponse(access_token=access_token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    auth_service = AuthService(db)
    user = auth_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    is_admin = db.query(UserRole).join(Role).filter(
        UserRole.user_id == user.id, Role.name == "admin"
    ).first() is not None
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        picture=user.picture,
        is_admin=is_admin,
    )
