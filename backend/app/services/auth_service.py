from typing import Optional
from sqlalchemy.orm import Session
from google.oauth2 import id_token
from google.auth.transport import requests
from ..models.user import User
from ..models.role import Role, UserRole
from ..config import get_settings

settings = get_settings()


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def verify_google_token(self, token: str) -> dict:
        try:
            idinfo = id_token.verify_oauth2_token(
                token,
                requests.Request(),
                settings.google_client_id
            )
            return {
                "google_id": idinfo["sub"],
                "email": idinfo["email"],
                "name": idinfo.get("name", ""),
                "picture": idinfo.get("picture", "")
            }
        except ValueError as e:
            raise ValueError(f"Invalid Google token: {str(e)}")

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

        # RDB 역할 할당
        role_name = "admin" if is_first else "member"
        role = self.db.query(Role).filter(Role.name == role_name).first()
        if role:
            self.db.add(UserRole(user_id=user.id, role_id=role.id))
            self.db.commit()

        return user

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()
