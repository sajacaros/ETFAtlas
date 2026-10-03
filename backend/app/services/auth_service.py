import secrets
from datetime import timedelta
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..models.user import User
from ..models.role import Role, UserRole
from ..models.invitation import Invitation
from ..utils.security import hash_password, verify_password
from ..utils.time import utcnow

INVITATION_TTL = timedelta(days=7)


class SetupAlreadyCompletedError(Exception):
    pass


class UsernameTakenError(Exception):
    pass


class InvalidInvitationError(Exception):
    """초대 토큰이 없거나, 이미 쓰였거나, 만료됨."""


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

    def register(self, username: str, password: str, name: str | None, invite_token: str) -> User:
        """초대 링크로 멤버 가입. 초대는 한 번만 쓸 수 있다."""
        # 같은 초대로 동시에 가입하는 경합 방지: 초대 행을 잠근 뒤 검사
        invitation = self.db.query(Invitation).filter(
            Invitation.token == invite_token
        ).with_for_update().first()
        if not self._is_usable(invitation):
            self.db.rollback()
            raise InvalidInvitationError()
        user = self._create_user(username, password, name, role_name="member", commit=False)
        invitation.used_at = utcnow()
        invitation.used_by = user.id
        self.db.commit()
        self.db.refresh(user)
        return user

    def invitation_valid(self, invite_token: str) -> bool:
        invitation = self.db.query(Invitation).filter(Invitation.token == invite_token).first()
        return self._is_usable(invitation)

    def create_invitation(self, created_by: int) -> Invitation:
        invitation = Invitation(
            token=secrets.token_urlsafe(24),
            created_by=created_by,
            expires_at=utcnow() + INVITATION_TTL,
        )
        self.db.add(invitation)
        self.db.commit()
        self.db.refresh(invitation)
        return invitation

    @staticmethod
    def _is_usable(invitation: Invitation | None) -> bool:
        return invitation is not None and invitation.used_at is None and invitation.expires_at > utcnow()

    def authenticate(self, username: str, password: str) -> Optional[User]:
        user = self.db.query(User).filter(User.username == username).first()
        if user and verify_password(password, user.password_hash):
            return user
        return None

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        return self.db.query(User).filter(User.id == user_id).first()

    def _create_user(
        self, username: str, password: str, name: str | None, role_name: str, commit: bool = True,
    ) -> User:
        if self.db.query(User.id).filter(User.username == username).first():
            self.db.rollback()
            raise UsernameTakenError()
        user = User(username=username, password_hash=hash_password(password), name=name or username)
        self.db.add(user)
        self.db.flush()
        role = self.db.query(Role).filter(Role.name == role_name).one()
        self.db.add(UserRole(user_id=user.id, role_id=role.id))
        if commit:
            self.db.commit()
            self.db.refresh(user)
        else:
            self.db.flush()
        return user


def is_admin(db: Session, user_id: int) -> bool:
    return db.query(UserRole).join(Role).filter(
        UserRole.user_id == user_id, Role.name == "admin"
    ).first() is not None
