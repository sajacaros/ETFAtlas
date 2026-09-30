from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..models.user import User
from ..models.role import Role, UserRole
from ..utils.security import hash_password, verify_password


class SetupAlreadyCompletedError(Exception):
    pass


class UsernameTakenError(Exception):
    pass


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def setup_required(self) -> bool:
        return self.db.query(User.id).first() is None

    def setup_admin(self, username: str, password: str, name: str | None) -> User:
        """최초 설치 시 관리자 생성. 사용자가 이미 있으면 거부."""
        # 동시 setup 요청 경합 방지: 트랜잭션 동안 users 테이블 쓰기 잠금
        self.db.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))
        if not self.setup_required():
            self.db.rollback()
            raise SetupAlreadyCompletedError()
        return self._create_user(username, password, name, role_name="admin")

    def register(self, username: str, password: str, name: str | None) -> User:
        if self.setup_required():
            raise SetupAlreadyCompletedError()  # setup 전 일반 가입 불가
        return self._create_user(username, password, name, role_name="member")

    def authenticate(self, username: str, password: str) -> Optional[User]:
        user = self.db.query(User).filter(User.username == username).first()
        if user and verify_password(password, user.password_hash):
            return user
        return None

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def _create_user(self, username: str, password: str, name: str | None, role_name: str) -> User:
        if self.db.query(User.id).filter(User.username == username).first():
            self.db.rollback()
            raise UsernameTakenError()
        user = User(username=username, password_hash=hash_password(password), name=name or username)
        self.db.add(user)
        self.db.flush()
        role = self.db.query(Role).filter(Role.name == role_name).one()
        self.db.add(UserRole(user_id=user.id, role_id=role.id))
        self.db.commit()
        self.db.refresh(user)
        return user


def is_admin(db: Session, user_id: int) -> bool:
    return db.query(UserRole).join(Role).filter(
        UserRole.user_id == user_id, Role.name == "admin"
    ).first() is not None
